#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${AUTOHUNTER_BACKUP_DIR:-/var/backups/autohunter}"
MAX_AGE_HOURS="${AUTOHUNTER_BACKUP_MAX_AGE_HOURS:-30}"

if [[ ! "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] || (( MAX_AGE_HOURS <= 0 )); then
  echo "ERROR: AUTOHUNTER_BACKUP_MAX_AGE_HOURS must be a positive integer." >&2
  exit 1
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "CRITICAL: backup directory not found: $BACKUP_DIR"
  exit 1
fi

LATEST_FILE="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'autohunter_*.sql.gz' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"

if [[ -z "$LATEST_FILE" ]]; then
  echo "CRITICAL: no backup files found in $BACKUP_DIR"
  exit 1
fi

LATEST_EPOCH="$(stat -c %Y "$LATEST_FILE")"
NOW_EPOCH="$(date +%s)"
AGE_SECONDS=$((NOW_EPOCH - LATEST_EPOCH))
MAX_AGE_SECONDS=$((MAX_AGE_HOURS * 3600))
AGE_HOURS=$((AGE_SECONDS / 3600))

if (( AGE_SECONDS <= MAX_AGE_SECONDS )); then
  echo "OK: latest backup is recent (${AGE_HOURS}h old): $LATEST_FILE"
  exit 0
fi

echo "WARNING: latest backup is stale (${AGE_HOURS}h old, max ${MAX_AGE_HOURS}h): $LATEST_FILE"
exit 2
