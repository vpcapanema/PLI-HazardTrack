"""Autenticacao de gestores contra o SIGMA-PLI (API HTTP ou PostgreSQL)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import psycopg
import requests
from psycopg.rows import dict_row

from .sigma_password import verify_password

log = logging.getLogger("sigma_auth")

GESTOR_PROFILE = "GESTOR"
DEFAULT_SIGMA_PUBLIC_BASE_URL = "http://56.125.163.194"
DEFAULT_SIGMA_API_BASE_URL = DEFAULT_SIGMA_PUBLIC_BASE_URL


class SigmaConnectionError(Exception):
    """SIGMA indisponivel (rede ou servico)."""


_LOOKUP_SQL = """
SELECT
        u.id::text,
        u.username,
        u.email_institucional,
        u.password_hash,
        u.tipo_usuario,
        u.ativo,
        u.bloqueado_ate,
        COALESCE(NULLIF(TRIM(p.nome_completo), ''), u.username) AS nome_completo
FROM usuarios.usuario u
LEFT JOIN cadastro.pessoa p ON p.id = u.pessoa_id
WHERE (
        LOWER(u.username) = LOWER(%(identifier)s)
        OR LOWER(u.email_institucional) = LOWER(%(identifier)s)
)
  AND UPPER(tipo_usuario) = %(profile)s
    AND u.ativo = true
LIMIT 2
"""

_FULL_NAME_BY_USER_ID_SQL = """
SELECT NULLIF(TRIM(p.nome_completo), '') AS nome_completo
FROM usuarios.usuario u
LEFT JOIN cadastro.pessoa p ON p.id = u.pessoa_id
WHERE u.id::text = %(user_id)s
LIMIT 1
"""


@dataclass(frozen=True)
class SigmaUser:
    id: str
    username: str
    email: str | None
    tipo_usuario: str
    full_name: str


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def sigma_api_base_url() -> str:
    configured = os.environ.get("SIGMA_API_BASE_URL")
    if configured is None:
        return DEFAULT_SIGMA_API_BASE_URL
    return configured.strip().rstrip("/")


def sigma_public_base_url() -> str:
    return (
        _env("SIGMA_PUBLIC_BASE_URL")
        or sigma_api_base_url()
        or DEFAULT_SIGMA_PUBLIC_BASE_URL
    ).rstrip("/")


def sigma_database_dsn() -> str:
    """DSN PostgreSQL do SIGMA (usuarios.usuario)."""
    url = _env("SIGMA_DATABASE_URL")
    if url:
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
            if url.startswith(prefix):
                return "postgresql://" + url.split(prefix, 1)[1]
        return url

    host = _env("SIGMA_POSTGRES_HOST")
    password = _env("SIGMA_POSTGRES_PASSWORD")
    if host and password:
        user = quote_plus(_env("SIGMA_POSTGRES_USER", "sigma_user"))
        pw = quote_plus(password)
        port = _env("SIGMA_POSTGRES_PORT", "5433") or "5433"
        db = _env("SIGMA_POSTGRES_DATABASE", "sigma_pli_qr53") or "sigma_pli_qr53"
        sslmode = _env("SIGMA_POSTGRES_SSLMODE", "disable") or "disable"
        return f"postgresql://{user}:{pw}@{host}:{port}/{db}?sslmode={sslmode}"
    return ""


def _connect_sigma_db(*args: Any, **kwargs: Any) -> Any:
    return psycopg.connect(*args, **kwargs)


def sigma_api_configured() -> bool:
    return bool(sigma_api_base_url())


def sigma_db_configured() -> bool:
    return bool(sigma_database_dsn())


def sigma_configured() -> bool:
    return sigma_api_configured() or sigma_db_configured()


def sigma_auth_links() -> dict[str, str] | None:
    base = sigma_public_base_url()
    if not base:
        return None
    return {
        "cadastro": f"{base}/cadastro",
        "cadastro_sigma": f"{base}/cadastro",
        "recuperar_senha": f"{base}/auth/recuperacao-senha-acesso-geral",
        "login_gestor": f"{base}/?next=/plataforma",
        "login_sigma": f"{base}/?next=/plataforma",
        "selecionar_perfil": f"{base}/auth/selecionar-perfil",
    }


def _row_blocked(row: dict[str, Any]) -> bool:
    until = row.get("bloqueado_ate")
    if until is None:
        return False
    if isinstance(until, datetime):
        dt = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        return dt > datetime.now(timezone.utc)
    return False


def _api_user_name(user: dict[str, Any]) -> str:
    for key in ("nome_completo", "full_name", "nome"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(user.get("username") or "")


def _lookup_full_name_by_user_id(user_id: object) -> str | None:
    dsn = sigma_database_dsn()
    if not dsn or not user_id:
        return None
    try:
        conn = _connect_sigma_db(dsn, row_factory=dict_row, connect_timeout=5)
        try:
            row = getattr(conn, "execute")(
                _FULL_NAME_BY_USER_ID_SQL, {"user_id": str(user_id)}
            ).fetchone()
        finally:
            getattr(conn, "close")()
    except Exception:
        log.warning("Nao foi possivel buscar nome completo no SIGMA", exc_info=True)
        return None
    if not row:
        return None
    name = row.get("nome_completo")
    return str(name).strip() if name else None


def _authenticate_gestor_via_api(
    identifier: str,
    password: str,
) -> SigmaUser | None:
    base = sigma_api_base_url().rstrip("/")
    url = f"{base}/api/auth/login"
    payload = {
        "identifier": identifier.strip(),
        "password": password,
        "tipo_usuario": GESTOR_PROFILE,
    }

    try:
        response = requests.post(url, json=payload, timeout=12.0)
    except requests.Timeout as exc:
        log.warning("SIGMA API timeout: %s", url)
        raise SigmaConnectionError("SIGMA indisponivel (timeout).") from exc
    except requests.RequestException as exc:
        log.warning("SIGMA API erro de rede: %s", exc)
        raise SigmaConnectionError("SIGMA indisponivel.") from exc

    if response.status_code == 401:
        return None
    if response.status_code == 429:
        log.warning("Rate limit no login SIGMA para identifier=%s", identifier)
        return None
    if response.status_code >= 500:
        raise SigmaConnectionError("SIGMA indisponivel.")

    if response.status_code != 200:
        log.warning(
            "Login SIGMA resposta inesperada (%s): %s",
            response.status_code,
            response.text[:300],
        )
        return None

    try:
        data = response.json()
    except ValueError as exc:
        raise SigmaConnectionError("Resposta invalida do SIGMA.") from exc

    user = data.get("user")
    if not isinstance(user, dict):
        return None

    tipo = str(user.get("tipo_usuario", "")).strip().upper()
    if tipo != GESTOR_PROFILE:
        return None

    user_id = user.get("id")
    username = user.get("username")
    if not user_id or not username:
        return None

    email = user.get("email_institucional")
    full_name = _lookup_full_name_by_user_id(user_id) or _api_user_name(user)
    return SigmaUser(
        id=str(user_id),
        username=str(username),
        email=str(email) if email else None,
        tipo_usuario=tipo,
        full_name=full_name,
    )


def _authenticate_gestor_via_db(
    identifier: str,
    password: str,
) -> SigmaUser | None:
    params = {"identifier": identifier.strip(), "profile": GESTOR_PROFILE}
    dsn = sigma_database_dsn()

    try:
        conn = _connect_sigma_db(dsn, row_factory=dict_row, connect_timeout=8)
        try:
            rows = getattr(conn, "execute")(_LOOKUP_SQL, params).fetchall()
        finally:
            getattr(conn, "close")()
    except Exception as exc:
        err_name = type(exc).__name__
        if (
            "Connection" in err_name
            or "Timeout" in err_name
            or "Operational" in err_name
        ):
            log.warning("SIGMA DB indisponivel: %s", exc)
            raise SigmaConnectionError("Banco SIGMA indisponivel.") from exc
        log.exception("Falha ao consultar usuarios.usuario no SIGMA")
        raise SigmaConnectionError("Erro ao consultar banco SIGMA.") from exc

    if not rows:
        return None
    if len(rows) > 1:
        log.warning("Login ambiguo para identifier=%s (multiplos gestores)", identifier)
        return None

    row = rows[0]
    if _row_blocked(row):
        return None

    pwd_hash = row.get("password_hash")
    if not verify_password(password, pwd_hash):
        return None

    return SigmaUser(
        id=str(row["id"]),
        username=row["username"],
        email=row.get("email_institucional"),
        tipo_usuario=str(row.get("tipo_usuario") or GESTOR_PROFILE),
        full_name=str(row.get("nome_completo") or row["username"]),
    )


def authenticate_gestor(identifier: str, password: str) -> SigmaUser | None:
    """Valida credenciais no SIGMA. Prefere API HTTP; fallback PostgreSQL."""
    if not sigma_configured():
        log.warning("SIGMA nao configurado para autenticacao.")
        return None

    if sigma_api_configured():
        return _authenticate_gestor_via_api(identifier, password)

    return _authenticate_gestor_via_db(identifier, password)


def healthcheck() -> dict:
    """Diagnostico rapido do backend SIGMA."""
    if not sigma_configured():
        return {"configured": False, "ok": False, "error": "env nao definida"}

    if sigma_api_configured():
        base = sigma_api_base_url().rstrip("/")
        try:
            r = requests.get(f"{base}/api/health", timeout=5.0)
            ok = r.status_code < 500
            return {
                "configured": True,
                "ok": ok,
                "mode": "api",
                "error": None if ok else f"HTTP {r.status_code}",
            }
        except Exception as e:
            return {
                "configured": True,
                "ok": False,
                "mode": "api",
                "error": str(e),
            }

    dsn = sigma_database_dsn()
    try:
        conn = _connect_sigma_db(dsn, connect_timeout=5)
        try:
            with getattr(conn, "cursor")() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
        finally:
            getattr(conn, "close")()
        return {"configured": True, "ok": True, "mode": "db", "error": None}
    except Exception as e:
        return {
            "configured": True,
            "ok": False,
            "mode": "db",
            "error": str(e),
        }
