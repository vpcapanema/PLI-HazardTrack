#!/usr/bin/env bash
# Ajusta .env da VM para PostgreSQL dedicado pli_hazzardtracker_db.
set -eu

ENV_FILE="/opt/pli-hazardtrack/.env"
[[ "$ENV_FILE" == "/opt/pli-hazardtrack/.env" ]] || exit 1
[[ -f "$ENV_FILE" ]] || { echo "erro: $ENV_FILE ausente"; exit 1; }

cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"

if grep -q '^OPS_SECRET=' "$ENV_FILE" && ! grep -q '^ADMIN_SECRET=' "$ENV_FILE"; then
    OPS_VAL=$(grep -E '^OPS_SECRET=' "$ENV_FILE" | cut -d= -f2-)
    printf '\nADMIN_SECRET=%s\n' "$OPS_VAL" >> "$ENV_FILE"
fi

set_or_replace() {
    local key="$1"
    local val="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
    fi
}

set_or_replace SIGMA_POSTGRES_HOST "pli-hazardtrack-db"
set_or_replace SIGMA_POSTGRES_PORT "5432"
set_or_replace SIGMA_POSTGRES_DATABASE "pli_hazzardtracker_db"
set_or_replace SIGMA_POSTGRES_USER "sigma_user"
set_or_replace SIGMA_POSTGRES_SSLMODE "disable"

if ! grep -q '^SIGMA_POSTGRES_PASSWORD=' "$ENV_FILE" \
    || [[ -z "$(grep '^SIGMA_POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)" ]]; then
    echo "erro: defina SIGMA_POSTGRES_PASSWORD no $ENV_FILE antes do deploy"
    exit 1
fi

chmod 600 "$ENV_FILE"
echo "ok: .env -> pli-hazardtrack-db:5432 / pli_hazzardtracker_db"
