#!/usr/bin/env sh
set -eu

PORT="${PORT:-8080}"
SERVICE_MODE="${SERVICE_MODE:-api}"

if [ "$SERVICE_MODE" = "scheduler" ]; then
  exec gunicorn \
    --bind ":${PORT}" \
    --workers "${GUNICORN_WORKERS:-1}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    scheduler:app
fi

exec uvicorn app_simple_gcs:app --host 0.0.0.0 --port "${PORT}"
