#!/usr/bin/env sh
set -eu

# Container entrypoint for the application image. It optionally runs Alembic
# migrations, then launches either the provided command or the default uvicorn
# server defined for this chassis.
cd /app

# Keep the SQLite data directory present for local and volume-backed runs.
mkdir -p /app/data

# In-memory rate limiting is per-process, so multi-worker deployments must use a
# shared backend to enforce limits consistently.
if [ "${APP_RATE_LIMIT_ENABLED:-false}" = "true" ] && \
   [ -z "${APP_RATE_LIMIT_STORAGE_URL:-}" ] && \
   [ "${UVICORN_WORKERS:-1}" != "1" ]; then
  echo "APP_RATE_LIMIT_STORAGE_URL is required when APP_RATE_LIMIT_ENABLED=true and UVICORN_WORKERS>1." >&2
  exit 1
fi

# Migrations stay opt-in so production restarts do not implicitly change schema.
if [ "${RUN_DB_MIGRATIONS:-false}" = "true" ]; then
  echo "Applying Alembic migrations..."
  alembic -c alembic.ini upgrade head
fi

# If no explicit command is provided, start the API with the container defaults.
# Workers default to 1 so orchestrated environments (Kubernetes, Swarm) can
# manage replication at the infrastructure level.  Set UVICORN_WORKERS >1 for
# single-server or Docker Compose deployments that need multi-core utilisation.
if [ "$#" -eq 0 ]; then
  set -- \
    uvicorn main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}" \
    --workers "${UVICORN_WORKERS:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${UVICORN_FORWARDED_ALLOW_IPS:-127.0.0.1}" \
    --no-access-log
fi

# Replace the shell so PID 1 remains tini and signals reach uvicorn directly.
exec "$@"
