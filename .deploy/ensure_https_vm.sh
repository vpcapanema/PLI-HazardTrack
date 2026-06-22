#!/usr/bin/env bash
# Emite/renova certificado Let's Encrypt e ativa vhost HTTPS no Nginx.
set -eu

APP_DIR="${APP_DIR:-/opt/pli-hazardtrack}"
PUBLIC_HOST="${PUBLIC_HOST:-pli-hazardtrack.56-125-163-194.sslip.io}"
WEBROOT="/var/www/certbot"
SNIPPET_SRC="$APP_DIR/.deploy/nginx-host/pli-hazardtrack-locations.conf"
SNIPPET_DST="/etc/nginx/snippets/pli-hazardtrack-locations.conf"
SSL_PARAMS_SRC="$APP_DIR/.deploy/nginx-host/pli-hazardtrack-ssl-params.conf"
SSL_PARAMS_DST="/etc/nginx/snippets/pli-hazardtrack-ssl-params.conf"
NGINX_HTTPS_SRC="$APP_DIR/.deploy/nginx-host/pli-hazardtrack"
NGINX_HTTP_SRC="$APP_DIR/.deploy/nginx-host/pli-hazardtrack-http-bootstrap"
NGINX_DST="/etc/nginx/sites-available/pli-hazardtrack"
CERT_DIR="/etc/letsencrypt/live/$PUBLIC_HOST"

step() { printf "\n\033[1;36mâ–¶ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32mâœ“\033[0m %s\n" "$1"; }
info() { printf "  \033[1;34mÂ·\033[0m %s\n" "$1"; }
warn() { printf "  \033[1;33m!\033[0m %s\n" "$1"; }

certbot_email() {
    if [[ -n "${CERTBOT_EMAIL:-}" ]]; then
        echo "$CERTBOT_EMAIL"
        return
    fi
    if [[ -f "$APP_DIR/.env" ]]; then
        local line
        line=$(grep -E '^CERTBOT_EMAIL=' "$APP_DIR/.env" 2>/dev/null \
            | tail -n 1 || true)
        if [[ -n "$line" ]]; then
            echo "${line#CERTBOT_EMAIL=}" | tr -d '"'"'"
            return
        fi
    fi
    echo "admin@${PUBLIC_HOST}"
}

install_certbot() {
    if command -v certbot >/dev/null 2>&1; then
        return
    fi
    info "instalando certbot..."
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot
}

ensure_dhparam() {
    sudo mkdir -p /etc/letsencrypt
    if [[ ! -f /etc/letsencrypt/ssl-dhparams.pem ]]; then
        info "gerando dhparam (2048 bits, uma vez)..."
        sudo openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048
    fi
}

deploy_snippet() {
    sudo mkdir -p /etc/nginx/snippets
    sudo cp "$SNIPPET_SRC" "$SNIPPET_DST"
    sudo cp "$SSL_PARAMS_SRC" "$SSL_PARAMS_DST"
}

reload_nginx() {
    sudo nginx -t
    sudo systemctl reload nginx
}

deploy_http_bootstrap() {
    sudo cp "$NGINX_HTTP_SRC" "$NGINX_DST"
    reload_nginx
}

deploy_https_vhost() {
    sudo cp "$NGINX_HTTPS_SRC" "$NGINX_DST"
    reload_nginx
}

recover_broken_nginx() {
    if sudo nginx -t 2>/dev/null; then
        return
    fi
    warn "nginx invalido â€” restaurando HTTP bootstrap"
    deploy_snippet
    deploy_http_bootstrap
}

obtain_certificate() {
    local email
    email=$(certbot_email)
    sudo mkdir -p "$WEBROOT"
    info "solicitando certificado Let's Encrypt para $PUBLIC_HOST"
    info "email de contato: $email"
    sudo certbot certonly --webroot -w "$WEBROOT" \
        -d "$PUBLIC_HOST" \
        --non-interactive --agree-tos \
        --email "$email" \
        --no-eff-email \
        --keep-until-expiring
}

step "Preparando snippet Nginx"
deploy_snippet
ok "snippets instalados"

recover_broken_nginx

step "Certificado TLS (Let's Encrypt)"
install_certbot
ensure_dhparam
sudo mkdir -p "$WEBROOT"

if sudo test -f "$CERT_DIR/fullchain.pem"; then
    ok "certificado ja presente em $CERT_DIR"
    sudo certbot renew --quiet --no-random-sleep-on-renew 2>/dev/null \
        || warn "renovacao nao executada (verifique certbot)"
else
    deploy_http_bootstrap
    ok "nginx HTTP bootstrap (ACME) ativo"
    if obtain_certificate; then
        ok "certificado emitido"
    else
        warn "nao foi possivel emitir TLS â€” app continua em HTTP"
        warn "confira: porta 443 aberta no SG AWS, DNS/sslip.io, CERTBOT_EMAIL"
        exit 0
    fi
fi

step "Ativando HTTPS no Nginx"
deploy_https_vhost
ok "vhost HTTPS ativo"

if ! sudo systemctl is-enabled certbot.timer >/dev/null 2>&1; then
    sudo systemctl enable certbot.timer 2>/dev/null || true
    sudo systemctl start certbot.timer 2>/dev/null || true
fi

ok "https://$PUBLIC_HOST"
