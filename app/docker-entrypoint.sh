#!/bin/sh
set -e

echo "[entrypoint] applying database migrations..."
alembic upgrade head

echo "[entrypoint] starting uvicorn..."
exec uvicorn lunair.main:app --host 0.0.0.0 --port 8000
