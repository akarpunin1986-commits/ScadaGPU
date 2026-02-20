#!/bin/sh
set -e

echo "=== Running Alembic migrations ==="
cd /app
alembic upgrade head
echo "=== Migrations complete ==="

echo "=== Starting SCADA backend ==="
exec uvicorn main:app --host 0.0.0.0 --port 8000
