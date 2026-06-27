#!/usr/bin/env bash
# Sobe PostgreSQL dedicado (pli_hazzardtracker_db) e garante schema/dados.
# Migracao do legado: apenas LEITURA em sigma_pli_db / sigma_pli_qr53.
set -eu

APP_DIR="/opt/pli-hazardtrack"
COMPOSE_FILE="docker-compose.vm.yml"
ENV_FILE="$APP_DIR/.env"
DB_SVC="pli-hazardtrack-db"
DB_CTN="pli_hazzardtracker_db"
LEGACY_CTN="sigma_pli_db"
LEGACY_SRC_DB="sigma_pli_qr53"
TARGET_DB="pli_hazzardtracker_db"

ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
info() { printf "  \033[1;34m·\033[0m %s\n" "$1"; }
warn() { printf "  \033[1;33m!\033[0m %s\n" "$1"; }
die()  { printf "  \033[1;31m✗\033[0m %s\n" "$1"; exit 1; }

[[ -f "$ENV_FILE" ]] || die ".env ausente em $ENV_FILE"

read_env() {
    grep -E "^${1}=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true
}

SIGMA_POSTGRES_USER="$(read_env SIGMA_POSTGRES_USER)"
SIGMA_POSTGRES_PASSWORD="$(read_env SIGMA_POSTGRES_PASSWORD)"
SIGMA_POSTGRES_USER="${SIGMA_POSTGRES_USER:-sigma_user}"
[[ -n "$SIGMA_POSTGRES_PASSWORD" ]] \
    || die "SIGMA_POSTGRES_PASSWORD obrigatorio no .env"

cd "$APP_DIR"

info "subindo $DB_SVC (PostgreSQL dedicado: $TARGET_DB)"
docker compose -f "$COMPOSE_FILE" up -d "$DB_SVC"

for i in $(seq 1 30); do
    if docker exec "$DB_CTN" pg_isready -U "$SIGMA_POSTGRES_USER" \
        -d "$TARGET_DB" >/dev/null 2>&1; then
        ok "PostgreSQL pronto ($DB_CTN / $TARGET_DB)"
        break
    fi
    sleep 2
done
docker exec "$DB_CTN" pg_isready -U "$SIGMA_POSTGRES_USER" \
    -d "$TARGET_DB" >/dev/null 2>&1 \
    || die "PostgreSQL nao respondeu"

# Volume antigo pode ter sido init como sigma_pli_qr53 — renomeia in-place.
HAS_TARGET=$(
    docker exec "$DB_CTN" psql -U "$SIGMA_POSTGRES_USER" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${TARGET_DB}'" \
        2>/dev/null | tr -d '[:space:]'
)
HAS_OLD=$(
    docker exec "$DB_CTN" psql -U "$SIGMA_POSTGRES_USER" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${LEGACY_SRC_DB}'" \
        2>/dev/null | tr -d '[:space:]'
)
if [[ "$HAS_TARGET" != "1" && "$HAS_OLD" == "1" ]]; then
    info "renomeando banco local ${LEGACY_SRC_DB} -> ${TARGET_DB}"
    docker exec "$DB_CTN" psql -U "$SIGMA_POSTGRES_USER" -d postgres -c \
        "ALTER DATABASE ${LEGACY_SRC_DB} RENAME TO ${TARGET_DB};"
fi

HAS_TABLE=$(
    docker exec "$DB_CTN" psql -U "$SIGMA_POSTGRES_USER" \
        -d "$TARGET_DB" -tAc \
        "SELECT to_regclass('usuarios.usuario')" 2>/dev/null \
        | tr -d '[:space:]'
)

if [[ -n "$HAS_TABLE" ]]; then
    ok "schema usuarios.usuario presente em $TARGET_DB"
    exit 0
fi

info "banco vazio — preparando schema/dados"

if docker ps --format '{{.Names}}' | grep -qx "$LEGACY_CTN"; then
    info "copiando ${LEGACY_SRC_DB} de ${LEGACY_CTN} (somente leitura)"
    if docker exec "$LEGACY_CTN" pg_dump -U postgres \
        -d "$LEGACY_SRC_DB" -Fc \
        | docker exec -i "$DB_CTN" pg_restore \
            -U "$SIGMA_POSTGRES_USER" \
            -d "$TARGET_DB" \
            --no-owner --role="$SIGMA_POSTGRES_USER" \
            --clean --if-exists; then
        ok "copia concluida (${LEGACY_SRC_DB} -> ${TARGET_DB})"
        exit 0
    fi
    warn "pg_restore falhou — tentando schema minimo"
fi

info "aplicando schema minimo"
docker exec -i "$DB_CTN" psql -U "$SIGMA_POSTGRES_USER" \
    -d "$TARGET_DB" \
    < "$APP_DIR/.deploy/postgres/init/01_schema.sql"

ok "schema minimo aplicado (gestor via bootstrap apos app subir)"
