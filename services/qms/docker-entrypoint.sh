#!/usr/bin/env sh
set -eu

if [ -n "${DB_HOST:-}" ]; then
  echo "Waiting for database ${DB_HOST}:${DB_PORT:-5432}..."
  until nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
    sleep 1
  done
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ "${RUN_SEED:-False}" = "True" ] || [ "${RUN_SEED:-False}" = "true" ] || [ "${RUN_SEED:-False}" = "1" ]; then
  python manage.py seed_bakery
fi

exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}
