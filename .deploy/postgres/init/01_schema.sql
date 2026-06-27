-- Schema minimo para autenticacao /admin (SIGMA-PLI read-only).
-- Em producao na VM, o dump de sigma_pli_qr53 substitui isto via migrate.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS usuarios;

CREATE TABLE IF NOT EXISTS usuarios.usuario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) NOT NULL,
    email_institucional VARCHAR(255),
    password_hash TEXT NOT NULL,
    tipo_usuario VARCHAR(32) NOT NULL DEFAULT 'GESTOR',
    ativo BOOLEAN NOT NULL DEFAULT true,
    bloqueado_ate TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS usuario_username_lower_idx
    ON usuarios.usuario (LOWER(username));

CREATE INDEX IF NOT EXISTS usuario_email_lower_idx
    ON usuarios.usuario (LOWER(email_institucional));
