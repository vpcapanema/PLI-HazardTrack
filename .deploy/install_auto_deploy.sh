#!/usr/bin/env bash
# Instala timer systemd que detecta push em origin/main e atualiza a VM.
set -eu

APP_DIR="/opt/pli-hazardtrack"
SERVICE_SRC="$APP_DIR/.deploy/systemd/pli-hazardtrack-watch.service"
TIMER_SRC="$APP_DIR/.deploy/systemd/pli-hazardtrack-watch.timer"
WATCH_SRC="$APP_DIR/.deploy/watch_and_update.sh"

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
die()  { printf "  \033[1;31m✗\033[0m %s\n" "$1"; exit 1; }

[[ -f "$WATCH_SRC" ]] || die "watch_and_update.sh nao encontrado — faca git pull antes"
[[ -f "$SERVICE_SRC" ]] || die "unit service nao encontrada"
[[ -f "$TIMER_SRC" ]] || die "unit timer nao encontrada"

chmod +x "$WATCH_SRC"
sed -i 's/\r$//' "$WATCH_SRC" 2>/dev/null || true
mkdir -p "$APP_DIR/logs"

step "Instalando units systemd"
sudo cp "$SERVICE_SRC" /etc/systemd/system/pli-hazardtrack-watch.service
sudo cp "$TIMER_SRC" /etc/systemd/system/pli-hazardtrack-watch.timer
sudo systemctl daemon-reload
sudo systemctl enable pli-hazardtrack-watch.timer
sudo systemctl restart pli-hazardtrack-watch.timer
ok "timer ativo (checagem a cada 2 min)"

step "Status"
systemctl status pli-hazardtrack-watch.timer --no-pager || true
ok "log: $APP_DIR/logs/auto-deploy.log"
echo ""
echo "Fluxo: commit + push no GitHub -> VM detecta em ate 2 min -> update_vm.sh"
