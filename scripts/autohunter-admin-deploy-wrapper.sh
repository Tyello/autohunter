#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/autohunter/repo"
EXPECTED_BRANCH="main"
SERVICES=("autohunter-bot" "autohunter-scheduler")

START_MS=$(date +%s%3N)
TMP_STDOUT=$(mktemp)
TMP_STDERR=$(mktemp)
cleanup(){ rm -f "$TMP_STDOUT" "$TMP_STDERR"; }
trap cleanup EXIT

json_fail() {
  local etype="$1"
  local emsg="$2"
  local end_ms=$(date +%s%3N)
  local dur=$((end_ms-START_MS))
  jq -n \
    --arg status "failed" \
    --arg et "$etype" \
    --arg em "$emsg" \
    --arg out "$(tail -c 2000 "$TMP_STDOUT" 2>/dev/null || true)" \
    --arg err "$(tail -c 2000 "$TMP_STDERR" 2>/dev/null || true)" \
    --argjson dur "$dur" \
    '{ok:false,status:$status,error_type:$et,error_message:$em,duration_ms:$dur,stdout_tail:$out,stderr_tail:$err}'
}

cd "$REPO_DIR" || { json_fail "repo" "repo_not_found"; exit 1; }

branch=$(git rev-parse --abbrev-ref HEAD 2>>"$TMP_STDERR" || true)
before=$(git rev-parse HEAD 2>>"$TMP_STDERR" || true)
if [[ "$branch" != "$EXPECTED_BRANCH" ]]; then
  json_fail "branch_mismatch" "expected=$EXPECTED_BRANCH got=$branch"
  exit 1
fi

git fetch origin "$EXPECTED_BRANCH" >>"$TMP_STDOUT" 2>>"$TMP_STDERR" || { json_fail "git_fetch" "git fetch failed"; exit 1; }
git pull --ff-only origin "$EXPECTED_BRANCH" >>"$TMP_STDOUT" 2>>"$TMP_STDERR" || { json_fail "git_pull" "git pull --ff-only failed"; exit 1; }
after=$(git rev-parse HEAD 2>>"$TMP_STDERR" || true)

services_json='[]'
for svc in "${SERVICES[@]}"; do
  systemctl restart "$svc" >>"$TMP_STDOUT" 2>>"$TMP_STDERR" || { json_fail "service_restart" "restart failed: $svc"; exit 1; }
  if systemctl is-active --quiet "$svc"; then
    services_json=$(jq --arg n "$svc" '. + [{name:$n,status:"active"}]' <<<"$services_json")
  else
    services_json=$(jq --arg n "$svc" '. + [{name:$n,status:"inactive"}]' <<<"$services_json")
    json_fail "service_health" "service inactive: $svc"
    exit 1
  fi
done

END_MS=$(date +%s%3N)
DUR=$((END_MS-START_MS))
PULLED=false
[[ "$before" != "$after" ]] && PULLED=true

jq -n \
  --arg branch "$branch" \
  --arg before "$before" \
  --arg after "$after" \
  --argjson pulled "$PULLED" \
  --arg status "success" \
  --arg out "$(tail -c 2000 "$TMP_STDOUT" 2>/dev/null || true)" \
  --arg err "$(tail -c 2000 "$TMP_STDERR" 2>/dev/null || true)" \
  --argjson duration "$DUR" \
  --argjson services "$services_json" \
  '{ok:true,status:$status,before_commit:$before,after_commit:$after,pulled:$pulled,branch:$branch,services:$services,duration_ms:$duration,stdout_tail:$out,stderr_tail:$err}'
