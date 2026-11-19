#!/bin/sh
set -e

python -m app.db.wait
alembic upgrade head

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  python seed.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
