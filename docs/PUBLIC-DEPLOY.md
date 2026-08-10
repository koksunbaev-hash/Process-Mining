# Постоянный адрес в интернете

Как вывести стенд наружу под своим доменом — так же, как сейчас работает
временный `qms.kzt.asia`.

---

## Как это устроено

Виртуалка стоит за NAT, белого адреса у неё нет и не будет. Поэтому наружу
смотрит не она, а арендованный сервер с публичным адресом, а между ними —
постоянный туннель:

```
интернет ──► VPS (публичный IP)          ──WireGuard──►  виртуалка
             Caddy: TLS, сертификаты                     10.66.66.32
                                                              │
                                                         nginx :443
                                                          ├─ :443   QMS
                                                          ├─ :8443  аналитика
                                                          └─ :10000 бэкенд приложения
```

Три свойства этой схемы, ради которых она и выбрана:

- **На вашем роутере ничего не открывается.** Соединение устанавливает
  виртуалка, изнутри наружу. Ни проброса портов, ни белого IP.
- **Сертификаты сами.** Caddy получает их у Let's Encrypt при первом запросе и
  продлевает без напоминаний.
- **Рейт-лимиты остаются в силе.** Caddy передаёт трафик в nginx виртуалки, а
  не в приложение напрямую, поэтому «12 попыток входа в минуту» действуют и
  снаружи. Проверено: после шестого запроса подряд начинается `429`.

Проверить, что туннель жив:

```bash
ip -brief addr show wg0
```

Должен показать `10.66.66.32/32`.

---

## 0. Что сделать до того, как адрес станет постоянным

Временный адрес прощает многое. Постоянный разойдётся по ссылкам, попадёт в
поисковики и будет сканироваться круглосуточно.

### 0.1 Сменить пароли

`admin` / `Admin123!` и ещё девять учётных записей напечатаны в публичном
репозитории — их знает любой, кто открыл `seed_bakery.py`.

```bash
cd ~/Process-Mining && docker compose exec -T qms python manage.py shell -c "
import secrets, string
from django.contrib.auth import get_user_model
alphabet = string.ascii_letters + string.digits
for u in get_user_model().objects.order_by('username'):
    pwd = ''.join(secrets.choice(alphabet) for _ in range(16))
    u.set_password(pwd); u.save()
    print(u.username, pwd, sep='\t')
"
```

Вывод — в менеджер паролей, один раз. После этого **не запускать**
`seed_bakery --reset-passwords`: он вернёт пароли из репозитория.

### 0.1a Заменить утёкшие секреты

**10 августа пять копий `.env` попали в публичный репозиторий** — `.env.bak` и
четыре файла с отметкой времени. Из репозитория они убраны, но это **не значит,
что они исчезли**: объекты остаются доступны по идентификатору коммита, а
публичный репозиторий читают не только люди. Единственная настоящая починка —
заменить значения.

Порядок по убыванию ущерба:

| Секрет | Что открывает | Где менять |
|---|---|---|
| `ONEC_URL`, `ONEC_USER`, `ONEC_PASSWORD` | **боевую базу 1С чужой компании** | у владельца базы, сразу |
| `DB_PASSWORD` | Postgres с заказами и партиями | `.env` + `ALTER USER` в базе |
| `SECRET_KEY` | подделку сессий и подписей Django | `.env`, все сессии слетят |
| `PM_API_KEYS` | приём событий и распознавание | `.env`, обе стороны разом |
| `PM_CALLBACK_SECRET` | подделку результата распознавания | `.env`, обе стороны разом |
| `PUSHTOTALK_API_TOKEN` | создание команд от имени телефона | `.env`, бэкенд и QMS |

Первая строка — не ваша собственность и не терпит отлагательства: это доступ к
бухгалтерии живого предприятия. Сообщить владельцу базы и сменить пароль там.

Дальше — генерация новых:

```bash
cd ~/Process-Mining
for k in SECRET_KEY PM_API_KEYS PM_CALLBACK_SECRET PUSHTOTALK_API_TOKEN; do
  echo "$k=$(openssl rand -hex 32)"
done
```

Вписать в `.env`, заменив старые строки, затем пароль базы привести в
соответствие (иначе QMS не поднимется — на эти грабли уже наступали):

```bash
set -a; . ./.env; set +a
docker compose exec -T db psql -U "$DB_USER" -d postgres <<SQL
ALTER USER "$DB_USER" WITH PASSWORD '$DB_PASSWORD';
SQL
docker compose up -d
```

**Проверить, что дубликатов ключей не появилось снова:**

```bash
grep -oE '^[A-Z_]+=' .env | sort | uniq -d
```

Пусто — хорошо. Иначе при следующем пересоздании контейнеров секреты разъедутся.

**И не класть копии `.env` рядом с ним.** Правило в `.gitignore` теперь
закрывает любое имя, начинающееся с `.env`, но бэкапы лучше держать вне
каталога репозитория совсем.

### 0.2 Проверить `.env`

```bash
cd ~/Process-Mining
grep -c '^[A-Z_]*=' .env
grep -oE '^[A-Z_]+=' .env | sort | uniq -d | tr -d '='
```

Вторая команда должна не вывести ничего. **Дубликаты ключей — это то, из-за
чего 7 августа стенд лежал дважды:** при пересоздании контейнера действует
последнее вхождение, и оно разъезжается с тем, что помнит работающий процесс.

Значения, которые не должны остаться шаблонными: `SECRET_KEY`, `PM_API_KEYS`,
`PM_CALLBACK_SECRET`, `PUSHTOTALK_API_TOKEN`, `DB_PASSWORD`.

### 0.3 Погасить лишнее

```bash
pgrep -a ngrok && pkill ngrok
```

Туннель на порт 8080 выставлял сервер распознавания в интернет без всякой
авторизации. После перехода на NeMo он не нужен.

---

## 1. Домен

Купить у любого регистратора. Ориентир: `.kz` — от 2000 тенге в год,
международные `.com` / `.dev` — около 10–15 долларов.

Создать **A-запись** на публичный адрес VPS:

```
qms.вашдомен.kz.    A    185.197.249.105
```

Проверить, что разошлось (обычно минуты, изредка до часа):

```bash
dig +short qms.вашдомен.kz
```

Должен ответить адресом VPS.

---

## 2. Если VPS ваш — добавить сайт в Caddy

На VPS, в `/etc/caddy/Caddyfile`:

```
qms.вашдомен.kz {
    reverse_proxy https://10.66.66.32 {
        transport http {
            tls
            tls_insecure_skip_verify
        }
    }
}
```

`tls_insecure_skip_verify` — потому что у nginx на виртуалке самоподписанный
сертификат, а хоп идёт внутри туннеля, где некому подделываться. Наружный
сертификат, который видит браузер, выпускает Caddy, и он настоящий.

Заголовок `Host` Caddy передаёт как есть, поэтому Django увидит именно ваше
имя — это важно для следующего шага.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Аналитику и бэкенд приложения — теми же блоками, меняется только порт:

```
pm.вашдомен.kz {
    reverse_proxy https://10.66.66.32:8443 {
        transport http { tls; tls_insecure_skip_verify }
    }
}

ptt.вашдомен.kz {
    reverse_proxy https://10.66.66.32:10000 {
        transport http { tls; tls_insecure_skip_verify }
    }
}
```

---

## 3. Если VPS нужен свой

Подойдёт самый дешёвый: он только принимает соединения и передаёт их в
туннель, ничего не считает. Один-два гигабайта памяти, около 5 долларов в
месяц. Ubuntu 24.04.

### 3.1 WireGuard на VPS

```bash
sudo apt update && sudo apt install -y wireguard
wg genkey | sudo tee /etc/wireguard/server.key | wg pubkey | sudo tee /etc/wireguard/server.pub
sudo chmod 600 /etc/wireguard/server.key
```

`/etc/wireguard/wg0.conf`:

```ini
[Interface]
Address = 10.66.66.1/24
ListenPort = 51820
PrivateKey = <содержимое server.key>

[Peer]
# виртуалка
PublicKey = <публичный ключ виртуалки, см. 3.2>
AllowedIPs = 10.66.66.32/32
```

```bash
sudo systemctl enable --now wg-quick@wg0
```

### 3.2 WireGuard на виртуалке

```bash
sudo apt install -y wireguard
wg genkey | sudo tee /etc/wireguard/vm.key | wg pubkey | sudo tee /etc/wireguard/vm.pub
sudo chmod 600 /etc/wireguard/vm.key
cat /etc/wireguard/vm.pub    # этот ключ вписать в конфиг VPS
```

`/etc/wireguard/wg0.conf`:

```ini
[Interface]
Address = 10.66.66.32/24
PrivateKey = <содержимое vm.key>

[Peer]
PublicKey = <содержимое server.pub с VPS>
Endpoint = <публичный IP VPS>:51820
AllowedIPs = 10.66.66.0/24
# Обязательно: виртуалка за NAT, и без периодических пакетов соединение
# закроется со стороны роутера через минуту тишины.
PersistentKeepalive = 25
```

```bash
sudo systemctl enable --now wg-quick@wg0
ping -c3 10.66.66.1
```

### 3.3 Caddy на VPS

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Дальше — `Caddyfile` из раздела 2.

### 3.4 Firewall на VPS

Наружу открыты ровно три порта:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80,443/tcp
sudo ufw allow 51820/udp
sudo ufw enable
```

---

## 4. Сказать Django новое имя

Django отвечает `400 Bad Request` на любой незнакомый `Host` — именно это вы
видели, когда домен пропал из `.env`.

В `~/Process-Mining/.env`:

```
ALLOWED_HOSTS=127.0.0.1,localhost,qms,192.168.0.137,qms.вашдомен.kz
CSRF_TRUSTED_ORIGINS=https://qms.вашдомен.kz,https://192.168.0.137
```

Имя хоста — **без** схемы и слэша. В `CSRF_TRUSTED_ORIGINS` — наоборот, со
схемой. `qms` в списке оставить обязательно: по этому имени внутрь стучится
callback распознавания.

```bash
cd ~/Process-Mining && docker compose up -d qms
```

---

## 5. Проверка

```bash
# страница входа отдаётся
curl -sS -o /dev/null -w '%{http_code} %{url_effective}\n' -L https://qms.вашдомен.kz/

# сертификат настоящий и не истёк
curl -sSI https://qms.вашдомен.kz/ | head -1

# куки помечены Secure
curl -sSI https://qms.вашдомен.kz/login/ | grep -i set-cookie

# рейт-лимит на входе работает
for i in $(seq 1 20); do printf "%s " $(curl -s -o /dev/null -w '%{http_code}' https://qms.вашдомен.kz/login/); done; echo
```

Ожидается: `200` на страницу входа, `Secure` в куке, и `429` в хвосте
последней строки. Если `429` не появляются — трафик идёт мимо nginx, и лимиты
надо повторить в Caddy.

---

## 6. Когда адрес устоялся — включить HSTS

```
SECURE_HSTS_SECONDS=31536000
```

```bash
docker compose up -d qms
```

Не раньше: браузер запомнит требование HTTPS на год, и отменой настройки это
не отыгрывается.

---

## Откат

Убрать блок из `Caddyfile`, `systemctl reload caddy` — адрес перестаёт
отвечать. Стек продолжает работать в локальной сети и в туннеле.

Полностью погасить туннель:

```bash
sudo systemctl stop wg-quick@wg0
```

---

## Что остаётся небезопасным

Публикация не чинит того, что записано в [HANDOFF](HANDOFF.md).

- **`tenant` фильтрует, но не изолирует.** Один API-ключ технически способен
  прочитать данные другого тенанта. Пока ключ один — не эксплуатируется, но
  раздавать ключи разным заказчикам нельзя.
- **Плечо «приложение → бэкенд» без авторизации.** В Android-клиенте стоит
  `NoAuthTokenProvider`. Пока телефоны в локальной сети — терпимо; публиковать
  порт 10000 наружу до появления токена нельзя.
- **Событийный лог невосстановим.** QMS помечает отправленное событие `SENT` и
  больше не отправляет. Умрёт диск аналитики — лог не пересчитается ниоткуда.
  Нужен бэкап `pm.db` наравне с Postgres.
- **Бэкапов нет.** Ни базы, ни томов. Для стенда терпимо, для предприятия нет.

## Чего не делать

- **Не выставлять наружу Proxmox.** Его веб-интерфейс на 8006 — это доступ ко
  всем виртуалкам разом.
- **Не пробрасывать порты на роутере.** Туннель даёт то же самое, и виртуалка
  при этом не светится сканерам.
- **Не возвращать `BIND_ADDR=0.0.0.0`.** Это открывает приложения по обычному
  http, включая страницу входа.
