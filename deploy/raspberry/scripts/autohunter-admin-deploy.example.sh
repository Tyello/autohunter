#!/usr/bin/env bash
set -euo pipefail

# Exemplo de wrapper privilegiado para instalar em /usr/local/bin/autohunter-admin-deploy
# Mantenha fora do repositório em produção, com owner root:root e chmod 750.

APP_USER="autohunter"
APP_HOME="/home/autohunter"
APP_DIR="/opt/autohunter"
BRANCH="main"

run_as_app() {
  /usr/bin/sudo -u "$APP_USER" env \
    HOME="$APP_HOME" \
    XDG_CONFIG_HOME="$APP_HOME/.config" \
    GIT_CONFIG_NOSYSTEM=1 \
    "$@"
}

before_commit="$(run_as_app /usr/bin/git -C "$APP_DIR" rev-parse HEAD)"
run_as_app /usr/bin/git -C "$APP_DIR" fetch origin "$BRANCH"
run_as_app /usr/bin/git -C "$APP_DIR" reset --hard "origin/$BRANCH"
after_commit="$(run_as_app /usr/bin/git -C "$APP_DIR" rev-parse HEAD)"

/usr/bin/systemctl restart autohunter-api.service autohunter-bot.service autohunter-scheduler.service

cat <<JSON
{"ok":true,"status":"success","branch":"$BRANCH","before_commit":"$before_commit","after_commit":"$after_commit"}
JSON
