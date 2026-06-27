"""
Area administrativa (/admin) com acesso restrito.

Autenticacao: SIGMA-PLI (PostgreSQL ou API HTTP) ou credenciais locais.
Configurar via env:
    ADMIN_USER / ADMIN_PASS   (dev e ambientes simples)
    ADMIN_SECRET              chave de sessao Flask
    SIGMA_API_BASE_URL        (opcional, producao integrada)

Tudo que importa para diagnosticar producao esta em uma unica resposta JSON
em /admin/api/diagnostics, organizada por responsabilidade:

    1. Visao geral (semaforos)
    2. Fontes externas (INPE/MERGE, basemap, Google Fonts)
    3. Plataforma e runtime (sistema, processo, dependencias)
    4. Pipeline de dados (scheduler, ciclos, qualidade)
    5. Modelo / metodologia (regioes, pontos, RA, limiares)
    6. Aplicacao web (rotas, assets versionados)
    7. Backend de autenticacao (saude da conexao com o SIGMA-PLI)
"""
from __future__ import annotations

import os
import platform
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

import requests
from flask import (
    Blueprint, current_app, jsonify, redirect, render_template,
    request, session, url_for
)

from .aggregator import state
from .merge_ingest import ingest
from .merge_inpe import (
    _eccodes_available, _hourly_url, INPE_BASE, PUBLISH_LAG_HOURS,
)
from . import admin_auth
from .admin_dashboard import build_report, collect_dashboard
from . import alert_controls
from .scheduler_registry import get_scheduler
from .sigma_auth import SigmaConnectionError

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin_user"):
            if request.path.startswith("/admin/api/"):
                return jsonify({"error": "auth required"}), 401
            return redirect(url_for("admin.login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Coleta de diagnostico
# ---------------------------------------------------------------------------

def _check_url(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Cheque rapido de uma URL. Retorna status + tempo + erro se houver."""
    t0 = time.monotonic()
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        dt = time.monotonic() - t0
        return {
            "url": url,
            "ok": 200 <= r.status_code < 400,
            "status": r.status_code,
            "elapsed_ms": int(dt * 1000),
            "error": None,
        }
    except Exception as e:  # noqa: BLE001
        dt = time.monotonic() - t0
        return {
            "url": url,
            "ok": False,
            "status": None,
            "elapsed_ms": int(dt * 1000),
            "error": str(e),
        }


def _process_memory_mb() -> Optional[float]:
    """RSS atual em MB, sem depender de psutil. Funciona em Linux."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024.0, 1)
    except Exception:
        pass
    return None


def _disk_usage_app(path: str = "/app") -> Optional[Dict[str, Any]]:
    try:
        import shutil
        total, used, free = shutil.disk_usage(path)
        return {
            "path": path,
            "total_mb": round(total / 1024 / 1024, 1),
            "used_mb": round(used / 1024 / 1024, 1),
            "free_mb": round(free / 1024 / 1024, 1),
        }
    except Exception:
        return None


def _safe_version(modname: str) -> Optional[str]:
    try:
        mod = __import__(modname)
        return getattr(mod, "__version__", None)
    except Exception:
        return None


def _registered_routes() -> List[Dict[str, Any]]:
    out = []
    for rule in current_app.url_map.iter_rules():
        methods = sorted(
            m for m in (rule.methods or set())
            if m not in {"HEAD", "OPTIONS"}
        )
        out.append({
            "rule": str(rule),
            "endpoint": rule.endpoint,
            "methods": methods,
        })
    out.sort(key=lambda r: r["rule"])
    return out


def collect_diagnostics() -> Dict[str, Any]:
    """Monta o blob de diagnostico por responsabilidade."""
    snap = state.get_snapshot()
    runtime = state.get_runtime()
    summary = snap.get("summary", {})

    # ---- 1. Visao geral / semaforos ----
    eccodes_ok = _eccodes_available()
    data_status = summary.get("data_status")
    overview = {
        "data_status": data_status,
        "data_source": summary.get("data_source"),
        "last_update": snap.get("timestamp_utc"),
        "points_loaded": len(snap.get("points", [])),
        "max_rd": summary.get("max_rd", 0),
        "max_rd_name": summary.get("max_rd_name"),
        "files_ok": summary.get("files_ok", 0),
        "missing_24h": summary.get("missing_24h"),
        "missing_96h": summary.get("missing_96h"),
        "uptime_s": runtime["uptime_s"],
        "cycle_count": runtime["cycle_count"],
        "cycle_success": runtime["cycle_success"],
        "cycle_fail": runtime["cycle_fail"],
        # Semaforos
        "lights": {
            "data": _light_for_data(
                data_status, summary.get("missing_24h", 0),
            ),
            "scheduler": "ok" if runtime["cycle_count"] > 0 else "warn",
            "eccodes": "ok" if eccodes_ok else "fail",
            "errors": "fail" if runtime["last_error"] else "ok",
        },
    }

    # ---- 2. Fontes externas ----
    now = datetime.now(timezone.utc)
    target = now.replace(minute=0, second=0, microsecond=0)
    sample_url = _hourly_url(target)
    carto_tile = (
        "https://a.basemaps.cartocdn.com/light_all/6/30/35.png"
    )
    google_fonts_url = (
        "https://fonts.googleapis.com/css2?family=Inter&display=swap"
    )
    external = {
        "merge_inpe": {
            "name": "MERGE / CPTEC / INPE",
            "role": "Chuva acumulada e intensidade horaria (modelo principal)",
            "base_url": INPE_BASE,
            "publish_lag_hours": PUBLISH_LAG_HOURS,
            "sample_url": sample_url,
            "reachability": _check_url(sample_url, timeout=8.0),
            "notes": (
                "Producao do INPE costuma ter latencia de ~3h entre "
                "observacao e disponibilizacao. Em tempestades essa "
                "latencia pode subir."
            ),
        },
        "basemap_carto": {
            "name": "Basemap CARTO Light",
            "role": "Tiles de base para o mapa Leaflet",
            "sample_url": carto_tile,
            "reachability": _check_url(carto_tile, timeout=5.0),
        },
        "google_fonts": {
            "name": "Google Fonts (Inter / Poppins)",
            "role": "Fontes da interface",
            "sample_url": google_fonts_url,
            "reachability": _check_url(
                google_fonts_url,
                timeout=5.0,
            ),
            "notes": "Self-host opcional ainda nao aplicado.",
        },
    }

    # ---- 3. Plataforma e runtime ----
    plat = {
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "system": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "hostname": socket.gethostname(),
        },
        "process": {
            "pid": os.getpid(),
            "memory_rss_mb": _process_memory_mb(),
            "disk": _disk_usage_app(),
            "started_at": runtime["started_at"],
            "uptime_s": runtime["uptime_s"],
        },
        "dependencies": {
            "flask": _safe_version("flask"),
            "flask_cors": _safe_version("flask_cors"),
            "apscheduler": _safe_version("apscheduler"),
            "requests": _safe_version("requests"),
            "numpy": _safe_version("numpy"),
            "shapely": _safe_version("shapely"),
            "eccodes_python": _safe_version("eccodes"),
            "eccodes_lib_loaded": eccodes_ok,
            "gunicorn": _safe_version("gunicorn"),
        },
        "env_flags": {

            "SAMAEG_DEGRADED_24H": os.environ.get("SAMAEG_DEGRADED_24H", "6"),
            "SAMAEG_USE_MANUAL_RA": os.environ.get(
                "SAMAEG_USE_MANUAL_RA", "0",
            ),
            "SAMAEG_WORKERS": os.environ.get("SAMAEG_WORKERS", "12"),
            "SAMAEG_DECODE_WORKERS": os.environ.get(
                "SAMAEG_DECODE_WORKERS", "6"
            ),
            "SAMAEG_INGEST_INTERVAL_S": os.environ.get(
                "SAMAEG_INGEST_INTERVAL_S", "120"
            ),
            "RENDER": os.environ.get("RENDER", ""),
            "RENDER_SERVICE_NAME": os.environ.get("RENDER_SERVICE_NAME", ""),
            "RENDER_GIT_COMMIT": os.environ.get("RENDER_GIT_COMMIT", ""),
            "RENDER_GIT_BRANCH": os.environ.get("RENDER_GIT_BRANCH", ""),
        },
    }

    # ---- 4. Pipeline de dados ----
    pipeline = {
        "scheduler": {
            "interval_min": 10,
            "cycle_count": runtime["cycle_count"],
            "cycle_success": runtime["cycle_success"],
            "cycle_fail": runtime["cycle_fail"],
            "last_started_at": runtime["last_cycle_started_at"],
            "last_finished_at": runtime["last_cycle_finished_at"],
            "last_duration_s": runtime["last_cycle_duration_s"],
            "last_error": runtime["last_error"],
            "last_error_at": runtime["last_error_at"],

            "degraded_threshold_h": runtime["degraded_threshold"],
        },
        "merge_ingest": ingest.status(),
        "data_quality": {
            "data_status": data_status,
            "files_ok": summary.get("files_ok", 0),
            "missing_24h": summary.get("missing_24h"),
            "missing_96h": summary.get("missing_96h"),
            "max_rd": summary.get("max_rd", 0),
            "by_level": summary.get("by_level"),
        },
        "history": runtime["history"],
    }

    # ---- 5. Modelo / metodologia ----
    regions = snap.get("regions", [])
    points = snap.get("points", []) or []
    by_region: Dict[str, int] = {}
    for p in points:
        key = p.get("region_name") or "Fora de cobertura"
        by_region[key] = by_region.get(key, 0) + 1
    methodology = {
        "regions": [
            {
                "id": r.get("id"),
                "nome": r.get("nome"),
                "rodovia": r.get("rodovia"),
                "k_geo": r.get("k_geo"),
            }
            for r in regions
        ],
        "points_total": len(points),
        "points_by_region": by_region,
        "ra_mode": (
            "manual"
            if os.environ.get("SAMAEG_USE_MANUAL_RA") == "1"
            else "neutralized (RA=1)"
        ),
        "formulas": {
            "envoltoria_critica": "I = K * Ac96h^(-0.9)",
            "cpc": "CPC = I_observada / I_envoltoria",
            "rd": (
                "RD = matriz oficial RA x ICC; "
                "RD final = max(RD_geo, RD_hid)"
            ),
        },
        "niveis": {
            "0": "Monitoramento",
            "1": "Observacao",
            "2": "Atencao",
            "3": "Alerta",
            "4": "Alerta Maximo",
        },
    }

    # ---- 6. Aplicacao web ----
    web = {
        "routes": _registered_routes(),
        "static_assets": {
            "leaflet": "/static/vendor/leaflet/leaflet.js",
            "leaflet_css": "/static/vendor/leaflet/leaflet.css",
            "leaflet_heat": "/static/vendor/leaflet/leaflet-heat.js",
            "favicon": "/static/favicon.svg",
            "app_js": "/static/app.js",
            "style_css": "/static/style.css",
        },
        "session": {
            "user": session.get("admin_user"),
            "remote_addr": request.remote_addr,
            "user_agent": request.headers.get("User-Agent"),
        },
    }

    # ---- 7. Backend de autenticacao (SIGMA-PLI) ----
    auth_backend = {
        **admin_auth.auth_backend_diag(),
        "session": {
            "user": session.get("admin_user"),
            "remote_addr": request.remote_addr,
            "user_agent": request.headers.get("User-Agent"),
        },
    }

    return {
        "generated_at": now.isoformat(),
        "overview": overview,
        "external_sources": external,
        "platform": plat,
        "pipeline": pipeline,
        "methodology": methodology,
        "web": web,
        "auth_backend": auth_backend,
    }


def _light_for_data(status: Optional[str], _missing_24h: int) -> str:
    if status == "ok":
        return "ok"
    if status in {"degraded", "loading"}:
        return "warn"
    return "fail"


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@admin_bp.route("/", methods=["GET"])
def root():
    """Root do /admin: redireciona para o status (com auth) ou login."""
    if session.get("admin_user"):
        return redirect(url_for("admin.status_page"))
    return redirect(url_for("admin.login_page"))


@admin_bp.route("/login", methods=["GET"])
def login_page():
    if session.get("admin_user"):
        next_url = request.args.get("next", "/admin/status")
        return redirect(next_url)
    next_url = request.args.get("next", "/admin/status")
    return render_template(
        "admin_login.html",
        next_url=next_url,
        backend_configured=admin_auth.auth_configured(),
    )


@admin_bp.route("/api/auth/context", methods=["GET"])
def api_auth_context():
    return jsonify(admin_auth.auth_context())


@admin_bp.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    if not admin_auth.auth_configured():
        return jsonify({
            "error": (
                "Acesso restrito nao configurado "
                "(defina SIGMA_POSTGRES_* ou ADMIN_USER/ADMIN_PASS no .env)."
            ),
        }), 503

    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    next_url = (
        str(body.get("next", "/admin/status")).strip()
        or "/admin/status"
    )

    if not next_url.startswith("/admin"):
        next_url = "/admin/status"

    try:
        user = admin_auth.authenticate(username, password)
    except SigmaConnectionError as exc:
        return jsonify({
            "error": "Servico de autenticacao indisponivel.",
            "detail": str(exc),
        }), 503

    if not user:
        return jsonify({"error": "Usuario ou senha invalidos."}), 401

    session.clear()
    session["admin_user"] = admin_auth.session_payload(user)
    session.permanent = True
    return jsonify({
        "ok": True,
        "username": user.username,
        "redirect": next_url,
    })


@admin_bp.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return redirect(url_for("admin.login_page"))


@admin_bp.route("/status", methods=["GET"])
@_login_required
def status_page():
    return render_template("admin_status.html")


@admin_bp.route("/api/dashboard", methods=["GET"])
@_login_required
def api_dashboard():
    return jsonify(collect_dashboard())


@admin_bp.route("/api/reports/export", methods=["GET"])
@_login_required
def api_report_export():
    report_type = request.args.get("type", "overview")
    try:
        ctype, filename, body = build_report(report_type)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    from flask import Response
    return Response(
        body,
        mimetype=ctype,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@admin_bp.route("/api/diagnostics", methods=["GET"])
@_login_required
def api_diagnostics():
    return jsonify(collect_diagnostics())


@admin_bp.route("/api/alert-controls", methods=["GET"])
@_login_required
def api_alert_controls_get():
    return jsonify(alert_controls.get_state())


@admin_bp.route("/api/alert-controls", methods=["POST"])
@_login_required
def api_alert_controls_set():
    body = request.get_json(silent=True) or {}
    system = str(body.get("system", "")).strip()
    if system not in ("geo_monitoring", "fire_monitoring"):
        return jsonify({
            "error": "system invalido (geo_monitoring | fire_monitoring)",
        }), 400
    if "enabled" not in body:
        return jsonify({"error": "campo 'enabled' obrigatorio"}), 400
    enabled = bool(body.get("enabled"))
    user = session.get("admin_user") or {}
    actor = user.get("username") or user.get("email") or "admin"
    state_out = alert_controls.set_system(system, enabled, actor=actor)
    alert_controls.apply_to_scheduler(get_scheduler())
    if system == "fire_monitoring" and enabled:
        from core import fire_pipeline
        threading.Thread(
            target=fire_pipeline.bootstrap_initial,
            daemon=True,
            name="fire-enable-bootstrap",
        ).start()
    elif system == "geo_monitoring" and enabled:
        from core.merge_ingest import ingest
        ingest.start()
        ingest.resume()
        threading.Thread(
            target=state.update,
            daemon=True,
            name="geo-enable-update",
        ).start()
    return jsonify(state_out)
