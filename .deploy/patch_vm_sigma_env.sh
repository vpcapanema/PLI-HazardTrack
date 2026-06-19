#!/usr/bin/env bash
# Adiciona credenciais SIGMA ao .env da VM (idempotente).
set -eu

ENV_FILE="/opt/pli-hazardtrack/.env"
[[ "$ENV_FILE" == "/opt/pli-hazardtrack/.env" ]] || exit 1

cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"

# Migra OPS_SECRET legado -> ADMIN_SECRET
if grep -q '^OPS_SECRET=' "$ENV_FILE" && ! grep -q '^ADMIN_SECRET=' "$ENV_FILE"; then
    OPS_VAL=$(grep -E '^OPS_SECRET=' "$ENV_FILE" | cut -d= -f2-)
    printf '\nADMIN_SECRET=%s\n' "$OPS_VAL" >> "$ENV_FILE"
fi

append_if_missing() {
    local key="$1"
    local val="$2"
    if ! grep -q "^${key}=" "$ENV_FILE"; then
        printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
    fi
}

append_if_missing SIGMA_POSTGRES_HOST "172.17.0.1"
append_if_missing SIGMA_POSTGRES_PORT "5433"
append_if_missing SIGMA_POSTGRES_DATABASE "sigma_pli_qr53"
append_if_missing SIGMA_POSTGRES_USER "sigma_user"
append_if_missing SIGMA_POSTGRES_PASSWORD "Malditas131533***"
append_if_missing SIGMA_POSTGRES_SSLMODE "disable"

chmod 600 "$ENV_FILE"
echo "ok: variaveis SIGMA presentes em $ENV_FILE"
