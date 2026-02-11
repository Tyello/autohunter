#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/autohunter}"
cd "$APP_DIR"

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONUNBUFFERED=1

python -m app.cli.run_scheduler
