# Push-to-Talk Backend
P
Сервис принимает распознанный на устройстве текст, сохраняет его в SQLite и отдаёт историю
для проверки. Стек: FastAPI + SQLAlchemy 2 + Pydantic v2, база создаётся автоматически.

## Быстрый старт

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

`--host 0.0.0.0` обязателен: иначе телефон из локальной сети не достучится до сервиса.

Интерактивная документация — `http://<host>:8080/docs`.

## API

### `POST /api/speech`

Принимает реплику.

```bash
curl -X POST http://192.168.0.137:8002/api/speech \
  -H "Content-Type: application/json" \
  -d '{"text":"hello"}'
```

| Ситуация | Код | Тело |
|----------|-----|------|
| Текст принят | 200 | `{"status":"ok","id":1}` |
| Пустой текст или одни пробелы | 400 | `{"status":"error","message":"empty text"}` |
| Текст длиннее лимита | 400 | `{"status":"error","message":"text too long: 50000 > 10000"}` |
| Поля `text` нет или неверный тип | 422 | `{"status":"error","message":"validation error","detail":[...]}` |
| Непредвиденный сбой | 500 | `{"status":"error","message":"internal server error"}` |

Текст обрезается по краям перед сохранением, поэтому `"  привет  "` и `"привет"` дают
одинаковую запись.

### `GET /api/messages`

Последние сообщения, новые сверху. По умолчанию 50, параметр `limit` сужает выборку.

```bash
curl http://192.168.0.137:8002/api/messages
```

```json
[{"id": 1, "text": "Привет", "created_at": "2026-07-28T20:30:00+05:00", "status": "received"}]
```

`created_at` отдаётся с явным смещением `+05:00`, поэтому клиент не может принять
метку за UTC и показать её на пять часов раньше.

### `GET /api/health`

`{"status":"ok","version":"1.0.0"}` — проверка живости.

## Хранение

Таблица `speech_messages`:

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | INTEGER PK | автоинкремент |
| `text` | TEXT | реплика после обрезки пробелов |
| `created_at` | DATETIME | местное время Алматы (UTC+5), индексируется для сортировки истории |
| `status` | VARCHAR(32) | `received` |

Файл базы и его каталог создаются при первом запуске — отдельного шага миграции нет.

### Часовой пояс

Всё время сервиса — местное, Алматы. Смещение задано одной константой в
`app/timeutils.py`; Казахстан с 1 марта 2024 года живёт в едином поясе UTC+5 без
перехода на летнее время, поэтому фиксированного `+5` достаточно и пакет `tzdata`
на хосте не нужен. Пояс не зависит от системного `TZ` сервера: местное время
пишется и при `TZ=UTC`.

Один и тот же сдвиг применён в трёх местах — иначе они разошлись бы:

- `default` колонки (обычная вставка через ORM);
- `server_default` в DDL — `datetime('now', '+5 hours')` вместо `CURRENT_TIMESTAMP`,
  который в SQLite возвращает UTC;
- метки времени в `app.log`.

Строки, накопленные до перехода на местное время, сдвигает разовый скрипт
`deploy/migrate_created_at_to_almaty.py` — см. раздел о развёртывании.

## Конфигурация

Все параметры читаются из окружения при старте:

| Переменная | По умолчанию (Linux) | По умолчанию (прочие ОС) | Назначение |
|------------|----------------------|--------------------------|------------|
| `PTT_DATA_DIR` | `/opt/push-to-talk/data` | `backend/data` | каталог базы |
| `PTT_LOG_DIR` | `/opt/push-to-talk/logs` | `backend/logs` | каталог логов |
| `PTT_DATABASE_URL` | `sqlite:///<PTT_DATA_DIR>/speech.db` | то же | строка подключения |
| `PTT_MAX_TEXT_LENGTH` | `10000` | то же | лимит длины реплики |
| `PTT_HISTORY_LIMIT` | `50` | то же | размер выдачи `/api/messages` |
| `PTT_LOG_LEVEL` | `INFO` | то же | уровень логирования |
| `PTT_RUNTIME_DIR` | `backend/.runtime` | то же | базовая runtime-папка для Render/локального запуска |
| `PTT_KMS_COMMAND_URL` | пусто | то же | URL KMS endpoint `/api/pushtotalk/commands/` |
| `PTT_KMS_API_TOKEN` | пусто | то же | токен для отправки команд в KMS |
| `PTT_KMS_TIMEOUT_SECONDS` | `10` | то же | timeout отправки текста в KMS |

На Render без persistent disk не используйте `/opt/push-to-talk`: free web service не имеет права создавать этот каталог. Оставьте дефолт `backend/.runtime` или задайте `PTT_DATA_DIR`/`PTT_LOG_DIR` на путь подключённого Render Disk.

Путь `/opt/push-to-talk` существует только на POSIX-системах, поэтому на Windows и macOS
сервис по умолчанию пишет рядом с кодом. Боевое размещение задаётся явно:

```bash
export PTT_DATA_DIR=/opt/push-to-talk/data
export PTT_LOG_DIR=/opt/push-to-talk/logs
```

## Логи

`<PTT_LOG_DIR>/app.log`, ротация по 5 МБ, 5 файлов истории.

```
2026-07-28 20:30:10 INFO app.services.speech_service Сообщение сохранено id=1 text_length=15 status=received
2026-07-28 20:30:10 INFO app.request POST /api/speech status=200 duration_ms=4.2
```

Время в логе — местное (Алматы), как и `created_at` в базе.

Сам текст реплики в лог не попадает — только его длина. Заголовок `Authorization`
не логируется ни на сервере, ни в клиенте.

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

61 тест, покрытие `app/` — 100 % (порог в `pytest.ini` — 80 %). Каждый тест получает
собственную временную базу и каталог логов, поэтому боевые данные не затрагиваются и
порядок выполнения не важен.

Покрыты: контракт обоих эндпоинтов, валидация (пустой текст, отсутствующее поле,
битый JSON, 50 000 символов), автосоздание базы, сохранение и порядок истории,
часовой пояс (запись, DDL-умолчание, ответ API, логи, разовая миграция),
сквозной сценарий «запрос → SQLite → история» и обработка непредвиденного сбоя.

## Развёртывание как сервиса (systemd)

Скрипт `deploy/install.sh` делает всё сам и идемпотентен — повторный запуск обновляет код и
перезапускает сервис, не трогая накопленную базу.

```bash
# 1. Скопировать код на сервер (без .venv, data, logs и кэшей)
rsync -av --exclude .venv --exclude data --exclude logs --exclude __pycache__ \
      backend/ root@<host>:/opt/push-to-talk/backend/

# 2. Установить и запустить
ssh root@<host> 'bash /opt/push-to-talk/backend/deploy/install.sh'
```

Что делает скрипт:

- ставит системного пользователя `ptt` и запускает сервис от него, а не от root;
- создаёт `/opt/push-to-talk/{data,logs}` и передаёт их владение `ptt`;
- собирает venv и ставит зависимости из `requirements.txt`;
- пишет юнит `/etc/systemd/system/push-to-talk.service` с `Restart=always`, автозапуском
  и ограничениями (`ProtectSystem=strict`, `NoNewPrivileges`, запись только в data и logs);
- переводит накопленные `created_at` из UTC в пояс Алматы скриптом
  `deploy/migrate_created_at_to_almaty.py`: сдвиг на +5 часов выполняется ровно один
  раз, отметка о нём хранится в таблице `applied_migrations` той же базы, поэтому
  повторные деплои строки больше не трогают;
- открывает порт в `ufw`/`firewalld`, если те активны;
- дожидается ответа `/api/health` и падает с диагностикой, если сервис не поднялся.

Параметры: `PTT_ROOT` (по умолчанию `/opt/push-to-talk`), `PTT_PORT` (`8080`),
`PTT_USER` (`ptt`).

Управление:

```bash
systemctl status push-to-talk
journalctl -u push-to-talk -f      # логи процесса
tail -f /opt/push-to-talk/logs/app.log   # логи приложения
```

### Требования к хосту

`python3` с рабочим `ensurepip`. На Debian/Ubuntu модуль `venv` присутствует, но без пакета
`python3-venv` создание окружения падает на `ensurepip is not available` — проверка
`python3 -m venv --help` этого не показывает. Ставится заранее:

```bash
apt install -y python3-venv
```

## Безопасность

MVP рассчитан на локальную сеть: авторизации нет, HTTPS не терминируется, учётные данные
нигде не хранятся. Клиент уже готов к появлению аутентификации — в нём есть
`AuthInterceptor`, который добавит `Authorization: Bearer <token>`, как только
`AuthTokenProvider` начнёт возвращать токен. Перед выносом сервиса за пределы локальной
сети нужно добавить проверку токена на стороне backend-а и TLS.
## MQTT route to Voice Gateway

PushToTalk can publish recognized text to the shared MQTT command bus. The
`services/voice-gateway` service consumes that topic and forwards commands to
KMS. This makes the phone backend reusable for other projects later.

If `PTT_MQTT_HOST` is empty, PushToTalk keeps the old direct KMS fallback through
`PTT_KMS_COMMAND_URL`.

Render variables for HiveMQ Cloud:

```env
PTT_MQTT_HOST=b6b2dc99ffe5473fb6c82721c186d30f.s1.eu.hivemq.cloud
PTT_MQTT_PORT=8883
PTT_MQTT_USERNAME=<hivemq username>
PTT_MQTT_PASSWORD=<hivemq password>
PTT_MQTT_TLS=true
PTT_MQTT_TOPIC=voice/commands/recognized
PTT_MQTT_CLIENT_ID=pushtotalk-backend
PTT_MQTT_PROJECT=kms
PTT_MQTT_TIMEOUT_SECONDS=10
```

The published JSON looks like this:

```json
{
  "project": "kms",
  "source": "pushtotalk-whisper",
  "request_id": "ptt-unique-id",
  "device_id": "pushtotalk-backend",
  "text": "Партия DEMO-B-0012 закончила замес, передать на формовку",
  "confidence": null,
  "metadata": {
    "producer": "pushtotalk-backend"
  }
}
```
