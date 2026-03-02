#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/autohunter}"
cd "$APP_DIR"

# Prefer project virtualenvs in order: .venv, venv, fallback to system python.
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  PYTHON_BIN=".venv/bin/python"
elif [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
  PYTHON_BIN="venv/bin/python"
elif [ -x "/opt/autohunter/.venv/bin/python" ]; then
  PYTHON_BIN="/opt/autohunter/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

export PYTHONUNBUFFERED=1

# Load environment variables from .env if present (without printing values).
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
