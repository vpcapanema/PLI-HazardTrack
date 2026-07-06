"""Autenticacao da area /admin — sessao Flask (local ou SIGMA-PLI)."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass

from . import sigma_auth

log = logging.getLogger("admin_auth")

GESTOR_PROFILE = "GESTOR"


@dataclass(frozen=True)
class AdminUser:
    user_id: str
    username: str
    tipo_usuario: str
    email: str | None = None
    full_name: str | None = None


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def auth_configured() -> bool:
    if sigma_auth.sigma_configured():
        return True
    return bool(_env("ADMIN_USER") and _env("ADMIN_PASS"))


def authenticate(username: str, password: str) -> AdminUser | None:
    identifier = (username or "").strip()
    if not identifier or not password:
        return None

    if sigma_auth.sigma_configured():
        user = sigma_auth.authenticate_gestor(identifier, password)
        if user:
            return AdminUser(
                user_id=user.id,
                username=user.username,
                tipo_usuario=user.tipo_usuario,
                email=user.email,
                full_name=getattr(user, "full_name", user.username),
            )
        return None

    local_user = _env("ADMIN_USER")
    local_pass = _env("ADMIN_PASS")
    if local_user and local_pass:
        user_ok = secrets.compare_digest(identifier, local_user)
        pass_ok = secrets.compare_digest(password, local_pass)
        if user_ok and pass_ok:
            return AdminUser(
                user_id="local",
                username=identifier,
                tipo_usuario=GESTOR_PROFILE,
                full_name=identifier,
            )
    return None


def session_payload(user: AdminUser) -> dict:
    return {
        "id": user.user_id,
        "username": user.username,
        "full_name": user.full_name or user.username,
        "tipo_usuario": user.tipo_usuario,
        "email": user.email,
    }


def auth_context() -> dict:
    local = bool(_env("ADMIN_USER") and _env("ADMIN_PASS"))
    links = sigma_auth.sigma_auth_links() if sigma_auth.sigma_configured() else None
    return {
        "sigma_configured": auth_configured(),
        "local_configured": local,
        "profile": GESTOR_PROFILE if sigma_auth.sigma_configured() else "admin",
        "identifier": {
            "label": "Usuário",
            "placeholder": "admin"
            if local
            else ("gestor.silva ou gestor.silva@orgao.gov.br"),
            "hint": "",
        },
        "password": {
            "label": "Senha",
            "placeholder": "Sua senha",
            "hint": "",
        },
        "sigma_links": links,
    }


def auth_backend_diag() -> dict:
    if sigma_auth.sigma_configured():
        mode = "sigma_api" if sigma_auth.sigma_api_configured() else "sigma_db"
        provider = "SIGMA-PLI (API HTTP ou PostgreSQL read-only)"
        health = sigma_auth.healthcheck()
    else:
        mode = "local"
        provider = "Credenciais locais (ADMIN_USER / ADMIN_PASS)"
        health = {
            "configured": True,
            "ok": bool(_env("ADMIN_USER") and _env("ADMIN_PASS")),
            "mode": "local",
            "error": None,
        }
    return {
        "provider": provider,
        "configured": auth_configured(),
        "role_required": GESTOR_PROFILE if mode != "local" else "admin",
        "mode": mode,
        "sigma_links": sigma_auth.sigma_auth_links(),
        "health": health,
    }
