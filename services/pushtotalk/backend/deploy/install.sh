#!/usr/bin/env bash
#
# Разворачивает Push-to-Talk backend на Linux-хосте как systemd-сервис.
#
# Скрипт идемпотентен: повторный запуск обновляет код и перезапускает сервис,
# не трогая уже накопленную базу.
#
# Запуск на сервере (код должен быть уже скопирован в /opt/push-to-talk/backend):
#     sudo bash /opt/push-to-talk/backend/deploy/install.sh
#
set -euo pipefail

ROOT="${PTT_ROOT:-/opt/push-to-talk}"
APP_DIR="$ROOT/backend"
DATA_DIR="$ROOT/data"
LOG_DIR="$ROOT/logs"
VENV="$APP_DIR/.venv"
PORT="${PTT_PORT:-8080}"
SERVICE="push-to-talk"
RUN_USER="${PTT_USER:-ptt}"

log() { printf '\n>>> %s\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
    echo "Нужны права root: sudo bash $0" >&2
    exit 1
fi

log "Проверка Python"
PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
    echo "python3 не найден. Установите его: apt install -y python3 python3-venv" >&2
    exit 1
fi
"$PYTHON" --version

log "Служебный пользователь $RUN_USER"
# Сервис не должен работать от root: у него нет причин иметь такие права.
if ! id -u "$RUN_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$RUN_USER"
    echo "создан"
else
    echo "уже есть"
fi

log "Каталоги"
mkdir -p "$DATA_DIR" "$LOG_DIR"
chown -R "$RUN_USER:$RUN_USER" "$DATA_DIR" "$LOG_DIR"
echo "$DATA_DIR"
echo "$LOG_DIR"

log "Виртуальное окружение и зависимости"
if [[ ! -x "$VENV/bin/python" ]]; then
    "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"

log "Перевод накопленных created_at в пояс Алматы (UTC+5)"
# Скрипт отмечает себя в базе, поэтому при повторных деплоях сдвига не будет.
"$VENV/bin/python" "$APP_DIR/deploy/migrate_created_at_to_almaty.py" "$DATA_DIR/speech.db"
chown -R "$RUN_USER:$RUN_USER" "$DATA_DIR"

log "systemd-юнит /etc/systemd/system/$SERVICE.service"
cat >"/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=Push-to-Talk backend
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=PTT_DATA_DIR=$DATA_DIR
Environment=PTT_LOG_DIR=$LOG_DIR
ExecStart=$VENV/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3

# База и логи — единственное, что сервису нужно писать.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR $LOG_DIR

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

log "Открытие порта $PORT (если есть firewall)"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow "$PORT/tcp" >/dev/null && echo "ufw: правило добавлено"
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null
    firewall-cmd --reload >/dev/null
    echo "firewalld: правило добавлено"
else
    echo "активный firewall не найден — пропущено"
fi

log "Проверка"
for _ in $(seq 1 20); do
    if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null; then
        break
    fi
    sleep 1
done

if curl -sf "http://127.0.0.1:$PORT/api/health"; then
    echo
    echo
    echo "Сервис поднят. Статус:  systemctl status $SERVICE"
    echo "Логи сервиса:           journalctl -u $SERVICE -f"
    echo "Логи приложения:        $LOG_DIR/app.log"
else
    echo
    echo "Сервис не отвечает. Диагностика:" >&2
    systemctl status "$SERVICE" --no-pager || true
    journalctl -u "$SERVICE" -n 40 --no-pager || true
    exit 1
fi
