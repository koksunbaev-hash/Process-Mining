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

# Defaults would give one sync worker with a 30s timeout, and a single slow
# request then freezes the whole site - which is exactly what happened: the
# voice widget polls every 400ms while the upload makes a blocking outbound
# call, so one stuck request took the QMS down with it.
#
# Threads matter more than processes here: the slow parts are waiting on the
# analytics service over HTTP, not burning CPU.
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers ${GUNICORN_WORKERS:-3} \
  --threads ${GUNICORN_THREADS:-4} \
  --timeout ${GUNICORN_TIMEOUT:-60} \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --access-logfile - \
  --error-logfile -
