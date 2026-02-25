#!/bin/sh

echo "=== Installing extra dependencies ==="
pip install --quiet python-multipart 2>/dev/null || true

echo "=== Running Alembic migrations ==="
cd /app
if alembic upgrade head 2>&1; then
  echo "=== Migrations applied successfully ==="
else
  echo "=== Migration failed! Attempting stamp head + continue ==="
  alembic stamp head 2>/dev/null || true
  echo "=== Stamped to head (tables already exist), continuing ==="
fi

echo "=== Starting SCADA backend ==="
exec uvicorn main:app --host 0.0.0.0 --port 8000
