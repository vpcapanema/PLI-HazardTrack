#!/usr/bin/env bash
# Atualiza PLI-HazardTrack na VM (sync GitHub + container + health).
set -eu

APP_DIR="/opt/pli-hazardtrack"
COMPOSE_FILE="docker-compose.vm.yml"
NGINX_SRC="$APP_DIR/.deploy/nginx-host/pli-hazardtrack"
NGINX_DST="/etc/nginx/sites-available/pli-hazardtrack"
PUBLIC_HOST="pli-hazardtrack.56-125-163-194.sslip.io"
EXPECTED_REPO_FRAGMENT="vpcapanema/PLI-HazardTrack"
RUNTIME_RE='^(Dockerfile|docker-compose\.vm\.yml|requirements|app\.py|core/|static/|templates/|data/ua_)'

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
info() { printf "  \033[1;34m·\033[0m %s\n" "$1"; }
warn() { printf "  \033[1;33m!\033[0m %s\n" "$1"; }
die()  { printf "  \033[1;31m✗\033[0m %s\n" "$1"; exit 1; }

[[ "$APP_DIR" == "/opt/pli-hazardtrack" ]] || die "diretorio inesperado: $APP_DIR"
[[ -d "$APP_DIR/.git" ]] || die "clone git nao encontrado em $APP_DIR"

cd "$APP_DIR"

ACTUAL_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
[[ "$ACTUAL_REMOTE" == *"$EXPECTED_REPO_FRAGMENT"* ]] || \
    die "remote inesperado: $ACTUAL_REMOTE"
ok "repositorio confirmado"

step "Sincronizando com o GitHub (origin/main)"
OLD_SHA=$(git rev-parse --short HEAD)
git fetch origin main
# Descarta divergencias locais na VM — deploy deve espelhar o GitHub
if [[ -f docker-compose.vm.yml ]] && \
    ! git ls-files --error-unmatch docker-compose.vm.yml >/dev/null 2>&1; then
    rm -f docker-compose.vm.yml
    info "removido docker-compose.vm.yml local (substituido pelo do repo)"
fi
git reset --hard origin/main
NEW_SHA=$(git rev-parse --short HEAD)
if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
    info "ja estava na versao $NEW_SHA"
else
    ok "codigo atualizado: $OLD_SHA -> $NEW_SHA"
    info "arquivos alterados:"
    git diff --name-only "$OLD_SHA" "$NEW_SHA" | sed 's/^/    /'
fi

[[ -f "$COMPOSE_FILE" ]] || die "docker-compose.vm.yml nao encontrado"

step "Verificando proxy Nginx"
if [[ -f "$NGINX_SRC" ]]; then
    if ! sudo cmp -s "$NGINX_SRC" "$NGINX_DST" 2>/dev/null; then
        sudo cp "$NGINX_DST" "${NGINX_DST}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
        sudo cp "$NGINX_SRC" "$NGINX_DST"
        sudo nginx -t
        sudo systemctl reload nginx
        ok "Nginx recarregado"
    else
        ok "Nginx ja estava atualizado"
    fi
else
    warn "config nginx nao encontrada em $NGINX_SRC"
fi

NEED_BUILD=0
if [[ "$OLD_SHA" != "$NEW_SHA" ]]; then
    if git diff --name-only "$OLD_SHA" "$NEW_SHA" | grep -qE "$RUNTIME_RE"; then
        NEED_BUILD=1
    else
        info "mudancas sem runtime — rebuild nao necessario"
    fi
fi

if [[ "$NEED_BUILD" -eq 1 ]]; then
    step "Reconstruindo imagem Docker (ARM64)"
    info "isso pode levar 1-3 minutos..."
    docker compose -f "$COMPOSE_FILE" build --pull
    ok "imagem pronta"
else
    step "Reutilizando imagem existente"
    ok "pulando rebuild"
fi

step "Reiniciando container"
docker compose -f "$COMPOSE_FILE" up -d --force-recreate
ok "container pli_hazardtrack_app em execucao"

step "Aguardando aplicacao ficar saudavel (ate 120 s)"
HEALTH_OK=0
for i in $(seq 1 24); do
    if curl -fsS http://127.0.0.1:5050/api/health >/dev/null 2>&1; then
        HEALTH_OK=1
        ok "healthcheck interno OK (tentativa $i)"
        break
    fi
    printf "  · aguardando... (%ds)\n" "$((i * 5))"
    sleep 5
done
[[ "${HEALTH_OK//[$'\r\n']/}" == "1" ]] \
    || die "app nao respondeu em /api/health"

step "Volume MERGE cache (disco persistente Docker)"
MERGE_VOL="pli_hazardtrack_merge_cache"
docker volume inspect "$MERGE_VOL" >/dev/null 2>&1 \
    || die "volume $MERGE_VOL ausente"
MOUNTED=$(
    docker inspect pli_hazardtrack_app \
        --format '{{range .Mounts}}{{if eq .Destination "/app/data/_cache/merge"}}{{.Name}}{{end}}{{end}}' \
        2>/dev/null || true
)
[[ "$MOUNTED" == "$MERGE_VOL" ]] \
    || die "container sem volume $MERGE_VOL em /app/data/_cache/merge"
ok "volume $MERGE_VOL montado"

step "Estatisticas do cache MERGE em disco"
if docker exec pli_hazardtrack_app python - <<'PY' 2>/dev/null; then
from core.merge_cache import disk_stats
import json
print(json.dumps(disk_stats(), indent=2))
PY
    ok "stats lidas do container"
else
    warn "nao foi possivel ler stats do cache (container ainda subindo?)"
fi

step "Testando URL publica (ate 120 s)"
PUB_OK=0
PUB_CODE="000"
for i in $(seq 1 24); do
    PUB_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
        -H "Host: $PUBLIC_HOST" \
        http://127.0.0.1/api/health 2>/dev/null || echo "000")
    if [[ "$PUB_CODE" == "200" ]]; then
        PUB_OK=1
        ok "proxy publico OK (HTTP $PUB_CODE, tentativa $i)"
        break
    fi
    printf "  · aguardando proxy... (%ds, HTTP %s)\n" "$((i * 5))" \
        "$PUB_CODE"
    sleep 5
done
[[ "$PUB_OK" -eq 1 ]] \
    || warn "proxy retornou HTTP $PUB_CODE (app interna pode estar OK)"

docker image prune -f >/dev/null 2>&1 || true

printf "\n\033[1;32m════════════════════════════════════════\033[0m\n"
printf "\033[1;32m  DEPLOY NA VM CONCLUIDO\033[0m\n"
printf "\033[1;32m════════════════════════════════════════\033[0m\n"
echo "  commit:  $NEW_SHA"
echo "  url:     http://$PUBLIC_HOST"
echo ""
