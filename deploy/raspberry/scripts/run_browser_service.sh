#!/usr/bin/env bash
set -e

APP_DIR="${APP_DIR:-/opt/autohunter}"
cd "$APP_DIR"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
  PYTHON_BIN="venv/bin/python"
elif [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m uvicorn app.browser_service.main:app --host 0.0.0.0 --port 7001 --workers 1
