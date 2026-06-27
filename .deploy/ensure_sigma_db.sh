#!/usr/bin/env bash
# Sobe PostgreSQL dedicado do PLI-HazardTrack e garante dados sigma_pli_qr53.
set -eu

APP_DIR="/opt/pli-hazardtrack"
COMPOSE_FILE="docker-compose.vm.yml"
ENV_FILE="$APP_DIR/.env"
DB_SVC="sigma-db"
DB_CTN="pli_sigma_db"
LEGACY_CTN="sigma_pli_db"

ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
info() { printf "  \033[1;34m·\033[0m %s\n" "$1"; }
warn() { printf "  \033[1;33m!\033[0m %s\n" "$1"; }
die()  { printf "  \033[1;31m✗\033[0m %s\n" "$1"; exit 1; }

[[ -f "$ENV_FILE" ]] || die ".env ausente em $ENV_FILE"
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${SIGMA_POSTGRES_USER:=sigma_user}"
: "${SIGMA_POSTGRES_DATABASE:=sigma_pli_qr53}"
: "${SIGMA_POSTGRES_PASSWORD:?SIGMA_POSTGRES_PASSWORD obrigatorio no .env}"

cd "$APP_DIR"

info "subindo $DB_SVC (PostgreSQL dedicado)"
docker compose -f "$COMPOSE_FILE" up -d "$DB_SVC"

for i in $(seq 1 30); do
    if docker exec "$DB_CTN" pg_isready -U "$SIGMA_POSTGRES_USER" \
        -d "$SIGMA_POSTGRES_DATABASE" >/dev/null 2>&1; then
        ok "PostgreSQL pronto ($DB_CTN)"
        break
    fi
    sleep 2
done
docker exec "$DB_CTN" pg_isready -U "$SIGMA_POSTGRES_USER" \
    -d "$SIGMA_POSTGRES_DATABASE" >/dev/null 2>&1 \
    || die "PostgreSQL nao respondeu"

HAS_TABLE=$(
    docker exec "$DB_CTN" psql -U "$SIGMA_POSTGRES_USER" \
        -d "$SIGMA_POSTGRES_DATABASE" -tAc \
        "SELECT to_regclass('usuarios.usuario')" 2>/dev/null \
        | tr -d '[:space:]'
)

if [[ -n "$HAS_TABLE" ]]; then
    ok "schema usuarios.usuario presente"
    exit 0
fi

info "banco vazio — preparando schema/dados"

if docker ps --format '{{.Names}}' | grep -qx "$LEGACY_CTN"; then
    info "migrando $SIGMA_POSTGRES_DATABASE de $LEGACY_CTN"
    if docker exec "$LEGACY_CTN" pg_dump -U postgres \
        -d "$SIGMA_POSTGRES_DATABASE" -Fc \
        | docker exec -i "$DB_CTN" pg_restore \
            -U "$SIGMA_POSTGRES_USER" \
            -d "$SIGMA_POSTGRES_DATABASE" \
            --no-owner --role="$SIGMA_POSTGRES_USER" \
            --clean --if-exists; then
        ok "migracao concluida a partir de $LEGACY_CTN"
        exit 0
    fi
    warn "pg_restore falhou — tentando schema minimo"
fi

info "aplicando schema minimo"
docker exec -i "$DB_CTN" psql -U "$SIGMA_POSTGRES_USER" \
    -d "$SIGMA_POSTGRES_DATABASE" \
    < "$APP_DIR/.deploy/postgres/init/01_schema.sql"

ok "schema minimo aplicado (gestor via bootstrap apos app subir)"
