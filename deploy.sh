#!/bin/bash
# =============================================================
# SCADA GPU — Production Deploy Script
# Runs ON the production server (192.168.30.130)
# Usage: sudo bash /opt/scada/deploy.sh
# =============================================================
set -e
SCADA_DIR="${SCADA_DIR:-/opt/scada}"
cd "$SCADA_DIR"

echo "==========================================="
echo "  SCADA Deploy — $(date '+%Y-%m-%d %H:%M:%S')"
echo "==========================================="

# ---- 1. Git pull ----
echo ""
echo "[1/4] Pulling latest code..."
git pull origin main --ff-only
echo "  OK"

# ---- 2. Rebuild backend (fresh pip install) ----
echo ""
echo "[2/4] Building backend image..."
docker compose build backend
echo "  OK"

# ---- 3. Recreate backend (picks up new .env + new code + new image) ----
echo ""
echo "[3/4] Recreating backend container..."
docker compose up -d --force-recreate backend
echo "  Waiting for startup..."

# ---- 4. Health check ----
echo ""
echo "[4/4] Health check..."
HEALTHY=false
for i in $(seq 1 40); do
  HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "200" ]; then
    echo "  Backend healthy after ${i}s"
    HEALTHY=true
    break
  fi
  sleep 1
done

if [ "$HEALTHY" = "true" ]; then
  # Final API verification
  echo ""
  echo "--- API Status ---"
  curl -s http://localhost/health 2>/dev/null && echo ""
  curl -s http://localhost/api/bitrix24/status 2>/dev/null && echo ""
  echo ""
  echo "==========================================="
  echo "  DEPLOY SUCCESS"
  echo "==========================================="
else
  echo ""
  echo "  ERROR: Backend not healthy after 40s!"
  echo ""
  echo "--- Backend Logs ---"
  docker logs scada-backend --tail 40
  echo ""
  echo "==========================================="
  echo "  DEPLOY FAILED"
  echo "==========================================="
  exit 1
fi
