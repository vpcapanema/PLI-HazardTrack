#!/bin/bash
# =============================================================================
# Atualizar PLI-HazardTrack na VM AWS
#
# Workflow:
#   (local)  git commit && git push
#   (vm)     bash /opt/pli-hazardtrack/.deploy/update_vm.sh
#
# Pressupoe que /opt/pli-hazardtrack ja e um clone do repo (rodar bootstrap
# antes da primeira vez).
#
# O script:
#   1. git pull (mantem .env intocado - esta no .gitignore)
#   2. rebuilda a imagem nativamente na VM (ARM64)
#   3. recria o container com a imagem nova (downtime ~5s)
#   4. recarrega Nginx do host se a config mudou (sigma-pli intocado)
#   5. valida healthcheck publico
#
# Reverter em caso de problema:
#   cd /opt/pli-hazardtrack
#   git log --oneline -5         # ve os ultimos commits
#   git reset --hard <sha>       # volta pro commit anterior
#   bash .deploy/update_vm.sh
# =============================================================================
set -euo pipefail

APP_DIR="/opt/pli-hazardtrack"
NGINX_SRC="$APP_DIR/.deploy/nginx-host/pli-hazardtrack"
NGINX_DST="/etc/nginx/sites-available/pli-hazardtrack"
EXPECTED_REPO_FRAGMENT="vpcapanema/PLI-HazardTrack"

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[1;32m[ok]\033[0m %s\n" "$1"; }
warn() { printf "    \033[1;33m[!!]\033[0m %s\n" "$1"; }
die()  { printf "    \033[1;31m[X]\033[0m %s\n" "$1"; exit 1; }

# --- TRAVAS DE SEGURANCA ----------------------------------------------------
# Esta VM tem outros repos (sigma-pli-repo, fad-stats-repo, sra-app).
# Estas checagens garantem que a gente NUNCA opere fora do PLI-HazardTrack.
[[ "$APP_DIR" == "/opt/pli-hazardtrack" ]] || die "APP_DIR fora do esperado: $APP_DIR"
[[ -d "$APP_DIR/.git" ]] || die "$APP_DIR nao e um clone git (rode bootstrap_vm.sh primeiro)"

cd "$APP_DIR"

ACTUAL_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [[ "$ACTUAL_REMOTE" != *"$EXPECTED_REPO_FRAGMENT"* ]]; then
    die "remote git inesperado em $APP_DIR: '$ACTUAL_REMOTE' (esperava conter '$EXPECTED_REPO_FRAGMENT')"
fi
ok "repo verificado: $ACTUAL_REMOTE"

# --- 1. git pull -------------------------------------------------------------
step "git pull (branch atual: $(git branch --show-current))"
OLD_SHA=$(git rev-parse --short HEAD)
git fetch --quiet origin
git pull --ff-only
NEW_SHA=$(git rev-parse --short HEAD)
if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
    warn "ja esta atualizado ($NEW_SHA) - prosseguindo mesmo assim para garantir build"
else
    ok "atualizado: $OLD_SHA -> $NEW_SHA"
fi

# --- 2. nginx config ---------------------------------------------------------
step "verificando config Nginx do host"
if [[ -f "$NGINX_SRC" ]]; then
    if ! sudo cmp -s "$NGINX_SRC" "$NGINX_DST" 2>/dev/null; then
        sudo cp "$NGINX_DST" "${NGINX_DST}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
        sudo cp "$NGINX_SRC" "$NGINX_DST"
        sudo nginx -t
        sudo systemctl reload nginx
        ok "nginx reconfigurado e recarregado"
    else
        ok "nginx config inalterada"
    fi
fi

# --- 3. rebuild da imagem (nativo na VM, ARM64) ------------------------------
step "rebuildando imagem da app (build nativo ARM64)"
docker compose -f docker-compose.vm.yml build --pull
ok "imagem reconstruida"

# --- 4. recria container -----------------------------------------------------
step "recriando container"
docker compose -f docker-compose.vm.yml up -d --force-recreate
ok "container recriado"

# --- 5. healthcheck ----------------------------------------------------------
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

step "testando acesso publico"
curl -s -o /dev/null -w "  status=%{http_code} time=%{time_total}s\n" \
    -H "Host: pli-hazardtrack.56-125-163-194.sslip.io" \
    http://127.0.0.1/api/health || true

# --- 6. limpeza opcional de imagens antigas ---------------------------------
step "limpando imagens orfas (sem container)"
docker image prune -f --filter "label=maintainer!=skip" >/dev/null
ok "limpeza ok"

step "ATUALIZACAO CONCLUIDA"
echo "  commit:       $NEW_SHA"
echo "  url:          http://pli-hazardtrack.56-125-163-194.sslip.io"
echo "  logs:         docker compose -f $APP_DIR/docker-compose.vm.yml logs -f --tail=200"
