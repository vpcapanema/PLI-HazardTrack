#!/bin/bash
# =============================================================================
# Adiciona o location /hazardtrack/ ao Nginx do host (no server default
# do sigma-pli). Permite acessar a app pelo IP direto:
#
#     http://56.125.163.194/hazardtrack/
#
# Estrategia segura:
#   1. backup do sigma-pli (timestamped)
#   2. adiciona location DENTRO do server bloco default, antes do "location /"
#   3. nginx -t (testa)
#   4. se ok, reload; se falhar, restaura o backup
#
# Idempotente: se o location ja existe, sai sem fazer nada.
# =============================================================================
set -euo pipefail

SIGMA="/etc/nginx/sites-available/sigma-pli"
TS="$(date +%Y%m%d-%H%M%S)"
BAK="${SIGMA}.bak.${TS}"

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[1;32m[ok]\033[0m %s\n" "$1"; }
warn() { printf "    \033[1;33m[!!]\033[0m %s\n" "$1"; }
die()  { printf "    \033[1;31m[X]\033[0m %s\n" "$1"; exit 1; }

[[ -f "$SIGMA" ]] || die "$SIGMA nao existe"

# Idempotencia: ja instalado?
if sudo grep -q "location /hazardtrack/" "$SIGMA"; then
    ok "location /hazardtrack/ ja existe em $SIGMA - nada a fazer"
    exit 0
fi

step "backup -> $BAK"
sudo cp "$SIGMA" "$BAK"
ok "backup feito"

step "inserindo location /hazardtrack/ antes do 'location /'"
# Insere o bloco antes da PRIMEIRA ocorrencia de "    location / {" no arquivo
# (que esta no server default, antes do server fad-stats).
# Usa sed com flag de "primeira ocorrencia": 0,/.../{}
BLOCK='    # ----- PLI-HazardTrack (acesso por path) -----\
    location /hazardtrack/ {\
        proxy_pass http://127.0.0.1:5050/;\
        proxy_http_version 1.1;\
        proxy_set_header Host              $host;\
        proxy_set_header X-Real-IP         $remote_addr;\
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto $scheme;\
        proxy_set_header X-Forwarded-Prefix /hazardtrack;\
        proxy_set_header Connection "";\
        proxy_connect_timeout  10s;\
        proxy_send_timeout     120s;\
        proxy_read_timeout     120s;\
    }\
'

# Insere antes da primeira "    location / {" sem espaços extras
sudo sed -i "0,/^    location \/ {/{s|^    location / {|${BLOCK}    location / {|}" "$SIGMA"

if ! sudo grep -q "location /hazardtrack/" "$SIGMA"; then
    sudo cp "$BAK" "$SIGMA"
    die "falha ao inserir o bloco - sigma-pli restaurado do backup"
fi
ok "bloco inserido"

step "validando nginx (sudo nginx -t)"
if ! sudo nginx -t 2>&1; then
    warn "nginx -t falhou - restaurando backup"
    sudo cp "$BAK" "$SIGMA"
    sudo nginx -t
    die "abortado, sigma-pli intacto"
fi
ok "nginx -t passou"

step "recarregando nginx"
sudo systemctl reload nginx
ok "reload feito"

step "testando rota /hazardtrack/api/health"
sleep 1
status=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/hazardtrack/api/health || echo "000")
echo "    HTTP $status"
[[ "$status" == "200" ]] && ok "OK" || warn "status nao foi 200 (verifique /var/log/nginx/error.log)"

echo
echo "Pronto. Acesso publico:"
echo "  http://56.125.163.194/hazardtrack/"
echo
echo "Para reverter:"
echo "  sudo cp $BAK $SIGMA && sudo nginx -t && sudo systemctl reload nginx"
