#!/bin/bash
# =============================================================================
# Bootstrap PLI-HazardTrack na VM AWS (rodar UMA VEZ)
#
# Migra /opt/pli-hazardtrack de "diretorio com compose solto" para
# "clone git completo", de forma segura e idempotente.
#
# Travas de seguranca - este script NUNCA toca em:
#   /home/ubuntu/sigma-pli-repo
#   /home/ubuntu/sigma-pli-deploy
#   /home/ubuntu/fad-stats-repo
#   /home/ubuntu/FADSTATS2
#   /home/ubuntu/sra-app
#   /etc/nginx/sites-enabled/sigma-pli   (arquivo do Sigma)
#
# Tudo do PLI-HazardTrack vive APENAS em:
#   /opt/pli-hazardtrack            (codigo)
#   /etc/nginx/sites-enabled/pli-hazardtrack  (nginx)
#   container pli_hazardtrack_app
#   rede pli_hazardtrack_net
#   volume pli_hazardtrack_cache
#
# Uso na VM:
#   curl -fsSL https://raw.githubusercontent.com/vpcapanema/PLI-HazardTrack/main/.deploy/bootstrap_vm.sh -o /tmp/bootstrap_vm.sh
#   bash /tmp/bootstrap_vm.sh
# =============================================================================
set -euo pipefail

APP_DIR="/opt/pli-hazardtrack"
REPO_URL="https://github.com/vpcapanema/PLI-HazardTrack.git"
EXPECTED_REPO_FRAGMENT="vpcapanema/PLI-HazardTrack"
BRANCH="main"

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[1;32m[ok]\033[0m %s\n" "$1"; }
warn() { printf "    \033[1;33m[!!]\033[0m %s\n" "$1"; }
die()  { printf "    \033[1;31m[X]\033[0m %s\n" "$1"; exit 1; }

# --- TRAVAS DE SEGURANCA ----------------------------------------------------
[[ "$APP_DIR" == "/opt/pli-hazardtrack" ]] || die "APP_DIR fora do esperado"
[[ -d "$APP_DIR" ]] || die "$APP_DIR nao existe (rode o deploy_vm.sh primeiro)"

# Garantir que NUNCA estamos operando em algum repo do Sigma/FAD/SRA
case "$APP_DIR" in
    *sigma*|*fad*|*sra*|/home/ubuntu/*)
        die "PATH SUSPEITO: $APP_DIR - abortando para nao mexer em outros projetos"
        ;;
esac
ok "travas de seguranca: caminho seguro ($APP_DIR)"

# --- 1. preserva o que ja esta la --------------------------------------------
step "preservando arquivos atuais (compose, .env)"
TMP_KEEP=$(mktemp -d)
[[ -f "$APP_DIR/.env" ]]                    && cp "$APP_DIR/.env"                    "$TMP_KEEP/"
[[ -f "$APP_DIR/docker-compose.vm.yml" ]]   && cp "$APP_DIR/docker-compose.vm.yml"   "$TMP_KEEP/"
ok "salvos em $TMP_KEEP"

# --- 2. derruba container se estiver up (precisa do compose acessivel) -------
step "derrubando container atual (se houver)"
if docker compose -f "$TMP_KEEP/docker-compose.vm.yml" ps --quiet 2>/dev/null | grep -q .; then
    docker compose -f "$TMP_KEEP/docker-compose.vm.yml" down
    ok "container derrubado"
else
    ok "nenhum container ativo via compose"
fi

# --- 3. limpa /opt/pli-hazardtrack (so isso, nada fora) ----------------------
step "limpando $APP_DIR"
[[ "$APP_DIR" == "/opt/pli-hazardtrack" ]] || die "trava redundante - APP_DIR mudou"
sudo rm -rf "$APP_DIR"
ok "diretorio limpo"

# --- 4. clona o repo --------------------------------------------------------
step "clonando $REPO_URL em $APP_DIR"
sudo mkdir -p "$(dirname "$APP_DIR")"
sudo git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
sudo chown -R "$USER:$USER" "$APP_DIR"
ok "clone feito"

# Validacao: confirmar que e o repo certo
cd "$APP_DIR"
ACTUAL_REMOTE=$(git remote get-url origin)
if [[ "$ACTUAL_REMOTE" != *"$EXPECTED_REPO_FRAGMENT"* ]]; then
    die "remote inesperado: $ACTUAL_REMOTE (esperava conter $EXPECTED_REPO_FRAGMENT)"
fi
ok "repo confirmado: $ACTUAL_REMOTE"

# --- 5. restaura .env --------------------------------------------------------
step "restaurando .env (se havia)"
if [[ -f "$TMP_KEEP/.env" ]]; then
    cp "$TMP_KEEP/.env" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    ok ".env restaurado (chmod 600)"
else
    warn "nao havia .env - crie um a partir de .env.example se for usar /ops"
fi
rm -rf "$TMP_KEEP"

# --- 6. build e up ----------------------------------------------------------
step "buildando imagem nativa ARM64 e subindo"
cd "$APP_DIR"
docker compose -f docker-compose.vm.yml build --pull
docker compose -f docker-compose.vm.yml up -d
ok "container subindo"

# --- 7. healthcheck ---------------------------------------------------------
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

step "BOOTSTRAP CONCLUIDO"
echo "  diretorio:    $APP_DIR  (clone git, branch $BRANCH)"
echo "  proximas atualizacoes:  bash $APP_DIR/.deploy/update_vm.sh"
echo "  url publica:  http://pli-hazardtrack.56-125-163-194.sslip.io"
