# Docker setup

Этот файл описывает запуск Bakery QMS/KMS локально через Docker Compose.

## Что запускается

- `web` - Django + Gunicorn.
- `db` - PostgreSQL 16.
- Docker volumes для базы данных, `staticfiles` и `media`.

## Первый запуск

Скопируйте пример env:

```powershell
copy .env.docker.example .env
```

Для Linux/macOS:

```bash
cp .env.docker.example .env
```

Поменяйте в `.env` минимум:

```env
SECRET_KEY=your-long-random-secret
DEBUG=False
ALLOWED_HOSTS=127.0.0.1,localhost
DB_PASSWORD=your-local-db-password
RUN_SEED=True
```

Запустите:

```bash
docker compose up --build
```

Сайт будет доступен:

```text
http://127.0.0.1:8000/
```

## Что делает контейнер при старте

`web` ждёт PostgreSQL, затем выполняет:

```text
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

Если в `.env` указано:

```env
RUN_SEED=True
```

то дополнительно запускается:

```text
python manage.py seed_bakery
```

## Демо-логины

После `seed_bakery` доступны:

- `admin / Admin123!`
- `dispatcher / Dispatch123!`
- `technologist / Tech123!`
- `mixing / Mix123!`
- `forming / Form123!`
- `proofing / Proof123!`
- `oven / Oven123!`
- `warehouse / Stock123!`
- `manager / Manager123!`
- `auditor / Auditor123!`

## Полезные команды

Логи приложения:

```bash
docker compose logs -f web
```

Создать суперпользователя:

```bash
docker compose exec web python manage.py createsuperuser
```

Заполнить демо-данные вручную:

```bash
docker compose exec web python manage.py seed_bakery
```

Запустить тесты:

```bash
docker compose exec web python manage.py test
```

Остановить контейнеры:

```bash
docker compose down
```

Остановить и удалить локальную Docker-БД, статику и media:

```bash
docker compose down -v
```

## Process Mining

Если нужно отправлять CSV-логи во внешний Process Mining, заполните:

```env
PROCESS_MINING_EVENT_LOG_URL=
PROCESS_MINING_API_TOKEN=
PROCESS_MINING_SOURCE=kms_bakery
PROCESS_MINING_SCHEMA_VERSION=1.0
```

Экспорт вручную:

```bash
docker compose exec web python manage.py export_process_events --batch-size 100
```

Проверка очереди событий:

```bash
docker compose exec web python manage.py process_event_status
```

## Важно для публичного GitHub

Не коммитьте настоящий `.env`. В репозитории должны лежать только:

- `.env.example`
- `.env.docker.example`

Локальная база, загруженные файлы и секреты исключены через `.gitignore` и `.dockerignore`.
