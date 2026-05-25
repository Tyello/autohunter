#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${AUTOHUNTER_BACKUP_DIR:-/var/backups/autohunter}"
RETENTION_DAYS="${AUTOHUNTER_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP_UTC="$(date -u +"%Y%m%d_%H%M%S")"
FINAL_FILE="${BACKUP_DIR}/autohunter_${TIMESTAMP_UTC}.sql.gz"
TMP_FILE="${BACKUP_DIR}/.autohunter_${TIMESTAMP_UTC}.sql.gz.tmp"

load_env_if_exists() {
  local env_file="$1"
  if [[ -z "$env_file" || ! -f "$env_file" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    line="${line#export }"
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      local key="${BASH_REMATCH[1]}"
      local value="${BASH_REMATCH[2]}"
      if [[ -z "${!key+x}" ]]; then
        export "$key=$value"
      fi
    fi
  done < "$env_file"
}

# Precedência para cron/manual:
# 1) AUTOHUNTER_ENV_FILE (se apontar para arquivo existente)
# 2) /etc/default/autohunter
# 3) /home/autohunter/autohunter/.env
# 4) ./.env
# Variáveis já exportadas no ambiente têm precedência e não são sobrescritas.
load_env_if_exists "${AUTOHUNTER_ENV_FILE:-}"
load_env_if_exists "/etc/default/autohunter"
load_env_if_exists "/home/autohunter/autohunter/.env"
load_env_if_exists "./.env"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set after loading env files. Backup aborted." >&2
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
