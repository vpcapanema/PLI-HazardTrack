"""
Contrato e protecao dos feeds publicos (/api/public/*).

Integradores externos devem enviar a chave configurada em PUBLIC_API_KEY
via cabecalho X-API-Key ou Authorization: Bearer <chave>.

Sem PUBLIC_API_KEY no ambiente, os endpoints permanecem abertos (dev/local).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from flask import Request, jsonify

API_VERSION = "1"
PUBLIC_API_KEY_ENV = "PUBLIC_API_KEY"


def public_api_key_configured() -> bool:
    return bool(_configured_key())


def _configured_key() -> str:
    return (os.environ.get(PUBLIC_API_KEY_ENV) or "").strip()


def extract_public_api_key(request: Request) -> str:
    header_key = (request.headers.get("X-API-Key") or "").strip()
    if header_key:
        return header_key
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def verify_public_api_access(request: Request) -> Optional[Tuple[Any, int]]:
    """Retorna resposta de erro (body, status) ou None se autorizado."""
    expected = _configured_key()
    if not expected:
        return None
    if request.method == "OPTIONS":
        return None
    provided = extract_public_api_key(request)
    if provided and provided == expected:
        return None
    return jsonify({
        "error": "unauthorized",
        "message": (
            "Chave de API publica ausente ou invalida. Envie o cabecalho "
            "X-API-Key ou Authorization: Bearer <chave>."
        ),
        "auth_required": True,
        "api_version": API_VERSION,
    }), 401


def apply_public_api_headers(response, *, max_age: int = 300):
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "X-API-Key, Authorization, Content-Type"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["X-Public-Api-Version"] = API_VERSION
    if public_api_key_configured():
        response.headers["X-Public-Api-Auth"] = "required"
    else:
        response.headers["X-Public-Api-Auth"] = "open"
    return response


def build_public_api_manifest(base_url: str) -> Dict[str, Any]:
    base = (base_url or "").rstrip("/")
    auth = {
        "required": public_api_key_configured(),
        "headers": ["X-API-Key", "Authorization: Bearer <token>"],
    }
    return {
        "api_version": API_VERSION,
        "modulo": "pli-hazardtrack-public",
        "auth": auth,
        "endpoints": {
            "ua_layers": {
                "url": f"{base}/api/public/ua-layers",
                "format": "GeoJSON",
                "params": {
                    "hazard": "geo|hidro|all",
                    "min_rd": "0..4",
                    "at": "ISO8601 (opcional)",
                },
            },
            "fire_risk_layers": {
                "url": f"{base}/api/public/fire-risk/layers",
                "format": "GeoJSON",
                "params": {
                    "horizonte": "observado|D+1|D+2|D+3",
                    "classe": "minimo|baixo|medio|alto|critico",
                },
            },
            "fire_risk_snapshot": {
                "url": f"{base}/api/public/fire-risk/snapshot",
                "format": "JSON",
            },
            "fire_risk_trecho": {
                "url": f"{base}/api/public/fire-risk/trecho/<trecho_id>",
                "format": "JSON",
                "params": {
                    "horizonte": "observado|D+1|D+2|D+3",
                },
            },
        },
    }
