#!/usr/bin/env bash
# Detecta push em origin/main e roda update_vm.sh somente quando ha commit novo.
set -eu

APP_DIR="/opt/pli-hazardtrack"
BRANCH="main"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/auto-deploy.log"
LOCK_FILE="/tmp/pli-hazardtrack-auto-deploy.lock"

mkdir -p "$LOG_DIR"

log() {
    printf '%s %s\n' "$(date -Is)" "$1" >>"$LOG_FILE"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "skip: deploy anterior ainda em execucao"
    exit 0
fi

[[ -d "$APP_DIR/.git" ]] || {
    log "erro: clone git ausente em $APP_DIR"
    exit 1
}

cd "$APP_DIR"

if ! git fetch origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
    log "erro: git fetch falhou"
    exit 1
fi

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/$BRANCH")

if [[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]; then
    exit 0
fi

log "novo commit: ${LOCAL_SHA:0:7} -> ${REMOTE_SHA:0:7}"
if bash "$APP_DIR/.deploy/update_vm.sh" >>"$LOG_FILE" 2>&1; then
    log "deploy concluido: $(git rev-parse --short HEAD)"
else
    log "erro: update_vm.sh falhou (exit $?)"
    exit 1
fi
