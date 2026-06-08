"""
Backend de autenticacao da pagina /ops contra o BANCO DE DADOS do SRA.

IMPORTANTE: este modulo NAO conversa com a aplicacao SRA. Ele abre conexao
TCP direta com o Postgres (`sra-postgres`) e le a tabela `users` em modo
SOMENTE LEITURA. A aplicacao SRA nao e chamada em nenhum momento - nem no
login, nem no diagnostico, nem na recuperacao de senha (essa ultima
redireciona o navegador do usuario para a tela de recuperacao do SRA, mas
quem responde nao somos nos).

Politica:
- SOMENTE LEITURA. O PLI-HazardTrack nao escreve nem altera nada no banco.
- Reusa o usuario do Postgres que o proprio SRA ja usa - NAO cria role nova.
- Login do /ops aceita SOMENTE usuarios com `users.role = 'admin'`.
- Comparacao bcrypt acontece dentro do PLI (mesma lib que gera o hash).
- Pool minimo (1-3 conexoes); login e operacao rara.
- Se a conexao com o banco cai, o /ops nao loga ninguem (fail-closed).

Configuracao via env (todas obrigatorias para habilitar):
    SRA_DB_HOST       host do Postgres do SRA  (ex: sra-postgres)
    SRA_DB_PORT       5432
    SRA_DB_NAME       sra
    SRA_DB_USER       usuario do Postgres (ex: sra_user)
    SRA_DB_PASSWORD   senha
"""
from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Optional

import bcrypt
import psycopg
from psycopg_pool import ConnectionPool

log = logging.getLogger("sra_auth")


# Perfil unico aceito no PLI-HazardTrack (decisao do produto)
OPS_ROLE = "admin"

# URL da pagina de recuperacao de senha do SRA. Quando o SRA estiver em
# producao com dominio proprio, sobrescreva via env SRA_RESET_URL.
DEFAULT_SRA_RESET_URL = "/recuperar-senha"


# Query unica usada no login. Nao seleciona email2/created_at/notificacoes_ativas
# para minimizar superficie do GRANT no SRA.
_AUTH_QUERY = """
SELECT id, email, nome, role, password_hash
FROM users
WHERE lower(email) = lower(%s) AND role = %s
LIMIT 1
"""


class SraAuthBackend:
    """Cliente de autenticacao read-only contra o Postgres do SRA."""

    def __init__(self) -> None:
        self._pool: Optional[ConnectionPool] = None
        self._pool_lock = Lock()
        self._dsn = self._build_dsn()

    # ------------------------------------------------------------------
    # Configuracao
    # ------------------------------------------------------------------

    def _build_dsn(self) -> Optional[str]:
        host = os.environ.get("SRA_DB_HOST", "").strip()
        if not host:
            return None
        port = os.environ.get("SRA_DB_PORT", "5432").strip() or "5432"
        name = os.environ.get("SRA_DB_NAME", "sra").strip() or "sra"
        user = os.environ.get("SRA_DB_USER", "").strip()
        pw = os.environ.get("SRA_DB_PASSWORD", "")
        if not user or not pw:
            return None
        # Connect timeout curto: nao queremos travar a UI no login
        return (
            f"host={host} port={port} dbname={name} "
            f"user={user} password={pw} "
            "connect_timeout=5 application_name=pli-hazardtrack-ops"
        )

    @property
    def configured(self) -> bool:
        """True se as variaveis de ambiente estao todas presentes."""
        return self._dsn is not None

    @property
    def reset_password_url(self) -> str:
        """URL para 'esqueci minha senha' que aponta para o SRA."""
        return os.environ.get("SRA_RESET_URL", DEFAULT_SRA_RESET_URL)

    # ------------------------------------------------------------------
    # Pool (lazy)
    # ------------------------------------------------------------------

    def _get_pool(self) -> Optional[ConnectionPool]:
        if not self.configured:
            return None
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    if self._dsn is None:
                        return None
                    self._pool = ConnectionPool(
                        conninfo=self._dsn,
                        min_size=1,
                        max_size=3,
                        timeout=5.0,
                        kwargs={"autocommit": True, "row_factory": psycopg.rows.dict_row},
                        open=True,
                    )
                    log.info("pool de conexao com o Postgres do SRA inicializado")
        return self._pool

    def healthcheck(self) -> dict:
        """Diagnostico para a pagina /ops (em si mesma)."""
        if not self.configured:
            return {"configured": False, "ok": False, "error": "env nao definida"}
        try:
            pool = self._get_pool()
            if pool is None:
                return {"configured": False, "ok": False, "error": "pool nao disponivel"}
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 AS ok")
                    cur.fetchone()
            return {"configured": True, "ok": True, "error": None}
        except Exception as e:
            return {"configured": True, "ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Autenticacao
    # ------------------------------------------------------------------

    def authenticate(
        self, email: str, password: str
    ) -> Optional[dict]:
        """
        Valida credenciais contra o banco do SRA. Retorna dict do usuario
        em caso de sucesso, None caso contrario.

        - SO aceita usuarios com role 'admin' no SRA.
        - Compara bcrypt em tempo (relativamente) constante.
        - Loga sucesso/falha sem expor a senha.
        """
        email = (email or "").strip()
        password = password or ""

        if not email or not password:
            return None
        if not self.configured:
            log.warning("ops auth: SRA_DB_* nao configurado")
            return None

        try:
            pool = self._get_pool()
            if pool is None:
                return None
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(_AUTH_QUERY, (email, OPS_ROLE))
                    row = cur.fetchone()
        except Exception as e:
            log.error("ops auth: erro ao consultar Postgres: %s", e)
            return None

        if not row:
            log.info("ops auth falha: admin nao encontrado email=%s", email)
            return None

        try:
            ok = bcrypt.checkpw(
                password.encode("utf-8"),
                row["password_hash"].encode("utf-8"),  # type: ignore[call-overload]
            )
        except Exception as e:
            log.error("ops auth: erro no bcrypt: %s", e)
            return None

        if not ok:
            log.info("ops auth falha: senha invalida email=%s", email)
            return None

        log.info("ops auth ok: id=%s email=%s", row["id"], email)  # type: ignore[call-overload]
        return {
            "id": row["id"],  # type: ignore[call-overload]
            "email": row["email"],  # type: ignore[call-overload]
            "nome": row["nome"],  # type: ignore[call-overload]
            "role": row["role"],  # type: ignore[call-overload]
        }


# Singleton acessado pelo blueprint /ops
sra_auth = SraAuthBackend()
