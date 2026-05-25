#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${AUTOHUNTER_BACKUP_DIR:-/var/backups/autohunter}"
RETENTION_DAYS="${AUTOHUNTER_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP_UTC="$(date -u +"%Y%m%d_%H%M%S")"
FINAL_FILE="${BACKUP_DIR}/autohunter_${TIMESTAMP_UTC}.sql.gz"
TMP_FILE="${BACKUP_DIR}/.autohunter_${TIMESTAMP_UTC}.sql.gz.tmp"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set. Backup aborted." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

cleanup_tmp() {
  rm -f "$TMP_FILE"
}
trap cleanup_tmp EXIT

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "ERROR: pg_dump command not found in PATH." >&2
  exit 1
fi

if ! pg_dump "$DATABASE_URL" --no-owner --no-privileges --format=plain --encoding=UTF8 | gzip -c > "$TMP_FILE"; then
  echo "ERROR: pg_dump failed. Backup file was not finalized." >&2
  exit 1
fi

mv -f "$TMP_FILE" "$FINAL_FILE"
trap - EXIT

if [[ "$RETENTION_DAYS" =~ ^-?[0-9]+$ ]] && (( RETENTION_DAYS > 0 )); then
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'autohunter_*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete || {
    echo "WARNING: retention cleanup failed for ${BACKUP_DIR}" >&2
  }
fi

if [[ -f "$FINAL_FILE" ]]; then
  SIZE_BYTES="$(wc -c < "$FINAL_FILE" | tr -d ' ')"
  echo "Backup completed successfully"
  echo "File: $FINAL_FILE"
  echo "Size bytes: $SIZE_BYTES"
  exit 0
fi

echo "ERROR: backup file not found after completion." >&2
exit 1
