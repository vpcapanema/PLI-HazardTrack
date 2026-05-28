#!/bin/bash
# =============================================================================
# Deploy do PLI-HazardTrack na VM AWS - script idempotente
#
# Pressupoe que ja foram transferidos para /tmp/pli-hazardtrack/:
#   - pli-hazardtrack-app-arm64.tar     (imagem da app)
#   - docker-compose.vm.yml             (stack)
#   - pli-hazardtrack                   (config nginx do host)
#   - .env                              (segredos OPS_*; opcional)
#
# Uso na VM:
#   cd /tmp/pli-hazardtrack
#   bash deploy_vm.sh
#
# O script NAO toca em /etc/nginx/sites-enabled/sigma-pli.
# Tudo e aditivo - se algo der errado, basta:
#   docker compose -f /opt/pli-hazardtrack/docker-compose.vm.yml down
#   sudo rm /etc/nginx/sites-enabled/pli-hazardtrack
#   sudo systemctl reload nginx
# =============================================================================
set -euo pipefail

APP_DIR="/opt/pli-hazardtrack"
NGINX_AVAILABLE="/etc/nginx/sites-available/pli-hazardtrack"
NGINX_ENABLED="/etc/nginx/sites-enabled/pli-hazardtrack"
SRC_DIR="$(pwd)"

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[1;32m[ok]\033[0m %s\n" "$1"; }
warn() { printf "    \033[1;33m[!!]\033[0m %s\n" "$1"; }

# --- 0. checagens basicas -----------------------------------------------------
step "checando pre-requisitos"
command -v docker >/dev/null || { echo "docker nao instalado"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 nao disponivel"; exit 1; }
[[ -f "$SRC_DIR/pli-hazardtrack-app-arm64.tar" ]] || { echo "imagem ARM64 nao encontrada em $SRC_DIR"; exit 1; }
[[ -f "$SRC_DIR/docker-compose.vm.yml" ]] || { echo "compose nao encontrado em $SRC_DIR"; exit 1; }
[[ -f "$SRC_DIR/pli-hazardtrack" ]] || { echo "config nginx nao encontrada em $SRC_DIR"; exit 1; }
ok "tudo presente"

# --- 1. carrega imagem ARM64 no Docker da VM ---------------------------------
step "carregando imagem da app no Docker"
docker load -i "$SRC_DIR/pli-hazardtrack-app-arm64.tar"
ok "imagem pli-hazardtrack-app:latest disponivel"

# --- 2. instala stack em /opt/pli-hazardtrack --------------------------------
step "instalando stack em $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo cp "$SRC_DIR/docker-compose.vm.yml" "$APP_DIR/docker-compose.vm.yml"
if [[ -f "$SRC_DIR/.env" ]]; then
    sudo cp "$SRC_DIR/.env" "$APP_DIR/.env"
    sudo chmod 600 "$APP_DIR/.env"
    ok ".env instalado (chmod 600)"
else
    warn "sem .env - OPS_PASS/OPS_SECRET ficam vazios; /ops nao vai logar"
fi
sudo chown -R "$USER:$USER" "$APP_DIR"
ok "stack em $APP_DIR"

# --- 3. instala virtual host do Nginx (NAO mexe no sigma-pli) ----------------
step "instalando virtual host no Nginx do host"
if [[ -f "$NGINX_AVAILABLE" ]]; then
    sudo cp "$NGINX_AVAILABLE" "${NGINX_AVAILABLE}.bak.$(date +%Y%m%d%H%M%S)"
    ok "backup do anterior feito"
fi
sudo cp "$SRC_DIR/pli-hazardtrack" "$NGINX_AVAILABLE"
sudo chown root:root "$NGINX_AVAILABLE"
sudo chmod 644 "$NGINX_AVAILABLE"

if [[ ! -L "$NGINX_ENABLED" ]]; then
    sudo ln -s "$NGINX_AVAILABLE" "$NGINX_ENABLED"
    ok "symlink criado em sites-enabled"
else
    ok "symlink ja existe"
fi

step "validando nginx"
sudo nginx -t

step "recarregando nginx"
sudo systemctl reload nginx
ok "nginx recarregado (sigma-pli intocado)"

# --- 4. sobe o container da app ----------------------------------------------
step "subindo container da app"
cd "$APP_DIR"
docker compose -f docker-compose.vm.yml up -d
ok "container subindo"

# --- 5. aguarda healthcheck --------------------------------------------------
step "aguardando healthcheck (max 90s)"
for i in {1..18}; do
    sleep 5
    if curl -fsS http://127.0.0.1:5050/api/health >/dev/null 2>&1; then
        ok "app respondendo em 127.0.0.1:5050"
        break
    fi
    printf "."
done
echo

# --- 6. validacao final (publico) --------------------------------------------
step "testando acesso pelo Nginx (Host: pli-hazardtrack.56-125-163-194.sslip.io)"
curl -s -o /dev/null -w "  status=%{http_code} time=%{time_total}s\n" \
    -H "Host: pli-hazardtrack.56-125-163-194.sslip.io" \
    http://127.0.0.1/api/health || true

step "PRONTO"
echo "  URL publica:  http://pli-hazardtrack.56-125-163-194.sslip.io"
echo "  Logs app:     docker compose -f $APP_DIR/docker-compose.vm.yml logs -f --tail=200"
echo "  Status:       docker compose -f $APP_DIR/docker-compose.vm.yml ps"
