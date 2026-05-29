#!/bin/bash
# =============================================================================
# Cria /opt/pli-hazardtrack/.env com:
#   - SRA_DB_PASSWORD lido do proprio container do SRA (nada e tipado)
#   - OPS_SECRET gerado aleatoriamente
#
# Idempotente: se o .env ja existe, faz backup antes.
# =============================================================================
set -euo pipefail

ENV_FILE="/opt/pli-hazardtrack/.env"
[[ "$ENV_FILE" == "/opt/pli-hazardtrack/.env" ]] || { echo "trava de path"; exit 1; }

# 1. extrair senha do SRA do proprio container (read-only)
SRA_PWD=$(docker exec sra-postgres bash -c 'echo -n "$POSTGRES_PASSWORD"')
SRA_USR=$(docker exec sra-postgres bash -c 'echo -n "$POSTGRES_USER"')
SRA_DB=$(docker exec sra-postgres bash -c 'echo -n "$POSTGRES_DB"')

if [[ -z "$SRA_PWD" || -z "$SRA_USR" ]]; then
    echo "nao consegui extrair credenciais do sra-postgres" >&2
    exit 1
fi

# 2. backup do .env anterior
if [[ -f "$ENV_FILE" ]]; then
    cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
fi

# 3. gera OPS_SECRET (mantem o anterior se houver, para nao invalidar sessoes)
OPS_SECRET=""
if [[ -f "$ENV_FILE" ]]; then
    OPS_SECRET=$(grep -E '^OPS_SECRET=' "$ENV_FILE" | cut -d= -f2- || true)
fi
if [[ -z "$OPS_SECRET" ]]; then
    OPS_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
fi

# 4. escreve .env
cat > "$ENV_FILE" <<EOF
# Gerado por setup_env_vm.sh em $(date -u +%Y-%m-%dT%H:%M:%SZ)
SRA_DB_HOST=sra-postgres
SRA_DB_PORT=5432
SRA_DB_NAME=${SRA_DB}
SRA_DB_USER=${SRA_USR}
SRA_DB_PASSWORD=${SRA_PWD}
SRA_RESET_URL=/recuperar-senha
OPS_SECRET=${OPS_SECRET}
EOF

chmod 600 "$ENV_FILE"
echo "ok: $ENV_FILE escrito (chmod 600)"
echo "  SRA_DB_USER=${SRA_USR}"
echo "  SRA_DB_NAME=${SRA_DB}"
echo "  OPS_SECRET=[gerado]"
