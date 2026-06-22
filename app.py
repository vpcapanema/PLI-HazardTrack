"""
SAMAEG-PLI - Sistema Automatizado de Monitoramento,
Analise e Alerta Geodinamico
Versao 0.1 - Backend Flask + scheduler
"""

import logging
import multiprocessing
import os
import secrets
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

import core.env  # noqa: F401  pylint: disable=unused-import
from core.aggregator import state
from core.admin import admin_bp
from core.actions import get_summary_actions, get_protocolo_completo
from core.merge_ingest import ingest
from core.ua_public_feed import build_ua_layers_geojson
from core.public_api import (
    apply_public_api_headers,
    build_public_api_manifest,
    public_api_key_configured,
    verify_public_api_access,
)
from core.zones import get_zones_geo, get_zones_hidro

_DEV_LOG = os.environ.get("SAMAEG_DEV_LOG") == "1"
_DEV_COLOR = os.environ.get("SAMAEG_DEV_COLOR") == "1"


class _Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    GRAY = "\033[90m"


def _enable_windows_vt() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(h, mode.value | 4)
    except Exception:
        pass


class _DevColorFormatter(logging.Formatter):
    """Cores no terminal dev: verde ok, vermelho erro, amarelo aviso."""

    def format(self, record: logging.LogRecord) -> str:
        plain = super().format(record)
        if not _DEV_COLOR or not sys.stdout.isatty():
            return plain
        msg = record.getMessage()
        level = record.levelno

        if level >= logging.ERROR:
            return f"{_Ansi.BOLD}{_Ansi.RED}{plain}{_Ansi.RESET}"
        if level >= logging.WARNING:
            return f"{_Ansi.YELLOW}{plain}{_Ansi.RESET}"

        if "[boot " in msg and "/5]" in msg:
            if "INDISPONIVEL" in msg or "Falha" in msg:
                color = _Ansi.RED
            elif any(
                k in msg for k in ("prontas", "disponivel", "configurado")
            ):
                color = _Ansi.GREEN
            else:
                color = _Ansi.CYAN
            return f"\n{_Ansi.BOLD}{color}{plain}{_Ansi.RESET}"

        if msg.startswith("===") or "Servidor HTTP" in msg:
            return (
                f"\n{_Ansi.BOLD}{_Ansi.MAGENTA}{plain}{_Ansi.RESET}\n"
            )

        if "[http]" in msg:
            if "-> 2" in plain or "-> 3" in plain:
                return f"{_Ansi.GREEN}{plain}{_Ansi.RESET}"
            if "-> 4" in plain or "-> 5" in plain:
                return f"{_Ansi.RED}{plain}{_Ansi.RESET}"
            return f"{_Ansi.GRAY}{plain}{_Ansi.RESET}"

        if "INDISPONIVEL" in msg or "Falha" in msg:
            return f"{_Ansi.RED}{plain}{_Ansi.RESET}"

        if any(
            k in msg for k in ("ativo", "disponivel", "prontas", "iniciado")
        ):
            return f"{_Ansi.GREEN}{plain}{_Ansi.RESET}"

        if any(
            k in msg for k in (
                "Aguardando", "em andamento", "loading", "mantendo",
            )
        ):
            return f"{_Ansi.YELLOW}{plain}{_Ansi.RESET}"

        if "Running on" in msg:
            return f"\n{_Ansi.BOLD}{_Ansi.GREEN}{plain}{_Ansi.RESET}\n"

        return plain


def _setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    if _DEV_LOG and _DEV_COLOR:
        _enable_windows_vt()
        handler.setFormatter(_DevColorFormatter(fmt))
    else:
        handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)


_setup_logging()
log = logging.getLogger("samaeg")

# Silencia o ruido do health check (keep-alive bate a cada 10 min).


class _HideHealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "/api/health" not in msg


for _name in ("werkzeug", "gunicorn.access"):
    logging.getLogger(_name).addFilter(_HideHealthFilter())

app = Flask(__name__, template_folder="templates", static_folder="static")
# Sessao Flask para /admin. Em prod, defina ADMIN_SECRET via env var.
# Sem ADMIN_SECRET, geramos um random por processo (cookies caem ao reiniciar).
app.config["SECRET_KEY"] = (
    os.environ.get("ADMIN_SECRET") or secrets.token_hex(32)
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Em producao (Render = HTTPS) marca o cookie como secure
if os.environ.get("RENDER") or os.environ.get("FORCE_HTTPS_COOKIES") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True
app.permanent_session_lifetime = timedelta(hours=12)

CORS(app)

# Atras do Nginx do host (acesso via http://IP/hazardtrack/ ou subdominio).
# X-Forwarded-Prefix faz Flask gerar URLs ja com o prefixo correto.
app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
    app.wsgi_app,
    x_for=1, x_proto=1, x_host=1, x_prefix=1,
)

app.register_blueprint(admin_bp)


@app.after_request
def _log_dev_request(response):
    """Log amigavel de requisicoes do frontend (modo dev)."""
    if not _DEV_LOG:
        return response
    path = request.path or ""
    if path.startswith("/static/") or path == "/api/health":
        return response
    log.info(
        "[http] %s %s -> %s",
        request.method,
        path,
        response.status_code,
    )
    return response


# ============================================================================
# INICIALIZACAO: rodar primeira atualizacao + agendar refresh
# ============================================================================
_BOOTSTRAP_DONE = threading.Event()
_BOOTSTRAP_LOCK = threading.Lock()


def _is_main_process() -> bool:
    """Evita bootstrap em filhos do ProcessPool (Windows reimporta app.py)."""
    return multiprocessing.current_process().name == "MainProcess"


def _bootstrap():
    """Primeiro ciclo + scheduler. Chamado uma unica vez por processo."""
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_DONE.is_set():
            return
        _BOOTSTRAP_DONE.set()

    if _DEV_LOG:
        log.info("=== Boot PLI-HazardTrack (modo dev) ===")

    log.info("SAMAEG-PLI iniciando...")

    if _DEV_LOG:
        log.info("[boot 1/5] Malha UA - carregando unidades de analise...")
    geo = get_zones_geo()
    hid = get_zones_hidro()
    if _DEV_LOG:
        log.info(
            "[boot 1/5] UAs prontas: encosta=%d inundacao=%d",
            len(geo), len(hid),
        )

    if _DEV_LOG:
        try:
            from core.merge_inpe import _eccodes_available
            ecc = _eccodes_available()
        except Exception:
            ecc = False
        log.info(
            "[boot 2/5] MERGE/INPE (CPTEC) - decodificador eccodes: %s",
            "disponivel" if ecc else "INDISPONIVEL",
        )
        log.info(
            "[boot 3/5] Ingest MERGE - fonte HTTP cpdc.inpe.br "
            "(nao usa banco local)",
        )
        sigma_api = os.environ.get("SIGMA_API_BASE_URL")
        sigma_db = os.environ.get("SIGMA_POSTGRES_HOST") or os.environ.get(
            "SIGMA_DATABASE_URL"
        )
        admin_local = os.environ.get("ADMIN_USER")
        if admin_local:
            log.info("[boot 4/5] Login /admin: credenciais locais (.env)")
        elif sigma_api or sigma_db:
            log.info("[boot 4/5] Login /admin (SIGMA-PLI): configurado")
        else:
            log.info(
                "[boot 4/5] Login /admin: nao configurado "
                "(defina SIGMA_POSTGRES_* ou ADMIN_USER/ADMIN_PASS no .env)",
            )

    coords = [(p["lat"], p["lon"]) for p in geo]
    ingest.configure(coords)
    from core.merge_leader import try_acquire_merge_leader

    if not try_acquire_merge_leader():
        ingest.start_disk_sync()
        log.info(
            "Worker secundario: ingest/scheduler no lider; sync disco ativo",
        )
        return

    ingest.start()

    if _DEV_LOG:
        log.info("[boot 5/5] Scheduler e primeiro ciclo de RD...")

    # Primeiro update em background para nao bloquear o boot do gunicorn
    def _first_update():
        try:
            state.update()
        except Exception as e:
            log.exception("Falha no primeiro update: %s", e)

    threading.Thread(
        target=_first_update, daemon=True
    ).start()

    scheduler = BackgroundScheduler(daemon=True)
    # Atualizacao a cada 10 minutos (MERGE horario tem latencia ~3h, mas como
    # pode ter
    # republicacao, atualizamos com mais frequencia para nao perder)
    scheduler.add_job(state.update, "interval", minutes=10, id="merge_refresh")

    # --- Risco de fogo (queimadas): runner automatico, isolado do MERGE -----
    if os.environ.get("QUEIMADAS_AUTO", "1") != "0":
        from core import fire_pipeline

        threading.Thread(
            target=fire_pipeline.bootstrap_initial, daemon=True
        ).start()
        try:
            fire_poll_min = int(
                os.environ.get("QUEIMADAS_POLL_MIN", "30") or 30
            )
        except ValueError:
            fire_poll_min = 30
        scheduler.add_job(
            fire_pipeline.poll_and_maybe_run,
            "interval",
            minutes=fire_poll_min,
            id="fire_refresh",
            max_instances=1,
            coalesce=True,
        )
        log.info(
            "Scheduler de risco de fogo ativo (poll a cada %d min)",
            fire_poll_min,
        )

    scheduler.start()
    log.info("Scheduler ativo (refresh a cada 10 min)")
    if _DEV_LOG:
        log.info(
            "Aguardando /api/health - ingest MERGE pode levar 1-3 min "
            "na 1a carga",
        )


def initialize():
    """Compatibilidade: usado pelo modo dev (python app.py)."""
    _bootstrap()


# Sob gunicorn o bloco __main__ nao roda; iniciamos no import do modulo.
# Em ambiente de testes, definir SAMAEG_DISABLE_BOOTSTRAP=1 para pular.
if (
    os.environ.get("SAMAEG_DISABLE_BOOTSTRAP") != "1"
    and _is_main_process()
):
    _bootstrap()


# ============================================================================
# ROTAS
# ============================================================================
@app.route("/")
def index():
    return render_template(
        "index.html",
        public_api_key=os.environ.get("PUBLIC_API_KEY", "").strip(),
        public_api_auth_required=public_api_key_configured(),
    )


def _doc_page(active: str):
    return render_template(
        f"docs/{active}.html",
        active=active,
        public_api_key=os.environ.get("PUBLIC_API_KEY", "").strip(),
        public_api_auth_required=public_api_key_configured(),
    )


@app.route("/docs/ajuda")
def docs_ajuda():
    """Guia publico de interpretacao do mapa."""
    return _doc_page("ajuda")


@app.route("/docs/glossario")
def docs_glossario():
    """Glossario tecnico publico."""
    return _doc_page("glossario")


@app.route("/docs/api")
def docs_api():
    """Documentacao da API publica."""
    return _doc_page("api")


@app.before_request
def _guard_public_api():
    path = request.path or ""
    if not path.startswith("/api/public"):
        return None
    denied = verify_public_api_access(request)
    if denied is not None:
        resp, status = denied
        return apply_public_api_headers(resp), status
    return None


@app.route("/api/history-hints")
def api_history_hints():
    """Datas sugeridas com alerta elevado (validacao / backtest)."""
    from core.history_hints import get_history_hints
    return jsonify(get_history_hints())


@app.route("/api/snapshot")
def api_snapshot():
    """Retorna o snapshot completo do estado atual."""
    at_raw = request.args.get("at")
    if at_raw:
        as_of = _parse_snapshot_at(at_raw)
        if as_of is None:
            return jsonify({
                "summary": {
                    "data_status": "no_data",
                    "message": "Parametro 'at' invalido (use ISO 8601).",
                },
            }), 400
        return jsonify(state.compute_snapshot_at(as_of))
    return jsonify(state.get_snapshot())


def _parse_snapshot_at(raw: str) -> Optional[datetime]:
    """Interpreta ?at= para consulta historica (UTC ou offset)."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@app.route("/api/progress")
def api_progress():
    """Progresso de download dos GRIBs do MERGE/INPE (arquivo a arquivo).

    Usado pela UI no primeiro ciclo para mostrar, em tempo real, cada GRIB
    horario sendo baixado do servidor INPE (dado real, sem fallback).
    """
    from core.merge_inpe import get_download_progress
    return jsonify(get_download_progress())


@app.route("/api/progress/stream")
def api_progress_stream():
    """Server-Sent Events: empurra progresso ao inves de pollar 1-2 req/s.

    A UI abre uma EventSource e recebe cada mudanca em push (versao
    monotonica acordada por Condition em core.merge_inpe). Sem mudanca,
    mantem a conexao viva com comentario `: keepalive` a cada ~15s. Cai
    pro polling do `/api/progress` se SSE falhar no cliente.
    """
    import json as _json
    import time as _time
    from flask import Response

    from core.merge_inpe import (
        get_download_progress,
        get_progress_version,
        wait_for_progress_change,
    )

    def generate():
        # Hint para proxies (nginx) nao bufferizarem o stream
        yield "retry: 5000\n\n"
        last_version = -1
        last_sent_at = 0.0
        # Rate limit: no maximo 1 evento real a cada 100ms (10/s).
        min_gap_s = 0.1
        try:
            while True:
                try:
                    new_version = wait_for_progress_change(
                        last_version, timeout_s=15.0,
                    )
                except GeneratorExit:
                    return
                if new_version == last_version:
                    try:
                        yield ": keepalive\n\n"
                    except (GeneratorExit, BrokenPipeError, ConnectionResetError):
                        return
                    continue
                gap = _time.monotonic() - last_sent_at
                if gap < min_gap_s:
                    _time.sleep(min_gap_s - gap)
                last_version = get_progress_version()
                payload = get_download_progress()
                payload["_version"] = last_version
                try:
                    data = _json.dumps(payload, default=str)
                except (TypeError, ValueError):
                    continue
                try:
                    yield f"data: {data}\n\n"
                except (GeneratorExit, BrokenPipeError, ConnectionResetError):
                    return
                last_sent_at = _time.monotonic()
        except GeneratorExit:
            return

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["X-Accel-Buffering"] = "no"  # nginx
    resp.headers["Connection"] = "keep-alive"
    return resp


@app.route("/api/road-network")
def api_road_network():
    """Serve a malha rodoviaria DER completa (GeoJSON otimizado para mapa)."""
    from flask import send_from_directory
    static_data = os.path.join(os.path.dirname(__file__), "static", "data")
    return send_from_directory(static_data, "malha_der.geojson",
                               mimetype="application/geo+json")


@app.route("/api/road-stats")
def api_road_stats():
    """Estatisticas e listas de filtros da malha."""
    from flask import send_from_directory
    static_data = os.path.join(os.path.dirname(__file__), "static", "data")
    return send_from_directory(static_data, "malha_der_stats.json",
                               mimetype="application/json")


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Forca atualizacao manual."""
    state.update()
    return jsonify({"ok": True, "snapshot": state.get_snapshot()["summary"]})


def _snapshot_points(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pontos do snapshot (geo + hidro) para APIs legadas."""
    geo = snap.get("points_geo") or []
    hidro = snap.get("points_hidro") or []
    if geo or hidro:
        return geo + hidro
    return snap.get("points", [])


@app.route("/api/actions")
def api_actions():
    """Retorna acoes operacionais por nivel para o snapshot atual."""
    snap = _snapshot_for_request()
    return jsonify(get_summary_actions(_snapshot_points(snap)))


def _snapshot_for_request():
    """Snapshot ao vivo ou historico (?at= ISO UTC)."""
    at_raw = request.args.get("at")
    if at_raw:
        as_of = _parse_snapshot_at(at_raw)
        if as_of is None:
            return {
                "summary": {
                    "data_status": "no_data",
                    "historical": True,
                    "message": "Parametro 'at' invalido.",
                },
                "points_geo": [],
                "points_hidro": [],
            }
        return state.compute_snapshot_at(as_of)
    return state.get_snapshot()


@app.route("/acoes")
def acoes_page():
    """Pagina dedicada de Acoes Operacionais de Contingencia (PPDC).

    Aberta pelo botao "Acoes necessarias" do painel lateral quando o
    nivel operacional exige acoes. Mostra, de forma detalhada e amigavel,
    o que cada orgao deve fazer agora, os trechos que exigem atencao e o
    protocolo PPDC completo (referencia, todos os niveis).
    """
    snap = _snapshot_for_request()
    points = _snapshot_points(snap)
    summary = snap.get("summary", {})
    historical = bool(summary.get("historical"))
    consulted_at = summary.get("consulted_at") or snap.get("timestamp_utc")
    return render_template(
        "acoes.html",
        actions=get_summary_actions(points),
        protocolo=get_protocolo_completo(),
        timestamp_utc=snap.get("timestamp_utc"),
        data_status=summary.get("data_status"),
        max_rd_name=summary.get("max_rd_name"),
        historical=historical,
        consulted_at=consulted_at,
    )


@app.route("/api/forecast")
def api_forecast():
    """
    Previsao WRF horaria (mesmo modulo do aggregator/RD).

    Janelas alinhadas ao Produto 6 (secao 4.5.3):
      - ac24h_forecast_mm: +24h futuras (composicao geologica)
      - ac6h_forecast_mm:  +6h futuras (composicao hidrologica)
    """
    from core.forecast_wrf_prec_hourly import fetch_forecast_accum_batch

    snap = state.get_snapshot()
    summary = snap.get("summary", {})
    points = snap.get("points_geo") or snap.get("points", [])
    coords = [(p["lat"], p["lon"]) for p in points]
    now_utc = datetime.now(timezone.utc)
    forecast = fetch_forecast_accum_batch(coords, now_utc) or []
    out = []
    for p, f in zip(points, forecast):
        entry = {
            "ua_id": p["ua_id"],
            "sigla_rodovia": p.get("sigla_rodovia"),
            "km_inicial": p.get("km_inicial"),
            "km_final": p.get("km_final"),
            "regiao_id": p.get("regiao_id"),
            "lat": p.get("centroide_lat") or p.get("lat"),
            "lon": p.get("centroide_lon") or p.get("lon"),
        }
        if f is not None:
            entry.update({
                "ac24h_forecast_mm": f.ac24h_mm,
                "ac6h_forecast_mm": f.ac6h_mm,
                "intensity_forecast_mmh": round(f.ac24h_mm / 24.0, 1),
                "forecast_time": f.run_utc.isoformat(),
                "source": f.source,
            })
        else:
            entry["forecast"] = None
        out.append(entry)
    src = (
        forecast[0].source
        if forecast and forecast[0] is not None
        else "INPE/CPTEC WRF prec (horario)"
    )
    return jsonify({
        "forecast": out,
        "source": src,
        "rd_basis": summary.get("rd_basis"),
        "forecast_ok": summary.get("forecast_ok"),
        "forecast_count": summary.get("forecast_count"),
    })


@app.route("/api/timeline")
def api_timeline():
    """Animacao temporal (Linha do Tempo) - Anexo C, secao 3.4.2.

    Reconstroi o RD de cada zona hora-a-hora nas ultimas 96 h (chuva
    observada do MERGE/INPE, janela movel). Operacao cara: roda sob
    demanda (botao Reproduzir) e usa cache curto no backend.
    """
    try:
        frames = int(request.args.get("frames", 96))
    except (TypeError, ValueError):
        frames = 96
    return jsonify(state.build_timeline(frames=frames))


@app.route("/api/public")
def api_public_manifest():
    """Catalogo dos feeds publicos e requisitos de autenticacao."""
    base = request.url_root.rstrip("/")
    prefix = request.headers.get("X-Forwarded-Prefix")
    if prefix:
        base += prefix.rstrip("/")
    resp = jsonify(build_public_api_manifest(base))
    return apply_public_api_headers(resp, max_age=600)


@app.route("/api/public/ua-layers")
def api_public_ua_layers():
    """Feed publico GeoJSON das UAs com RD e chuva em tempo real.

    Query params:
      hazard=geo|hidro|all   (default all)
      min_rd=0..4            filtra UAs com RD >= min_rd
      at=ISO8601             snapshot historico (UTC)
    """
    snap = _snapshot_for_request()
    hazard = request.args.get("hazard", "all")
    min_rd_raw = request.args.get("min_rd")
    min_rd = None
    if min_rd_raw is not None and str(min_rd_raw).strip() != "":
        try:
            min_rd = int(min_rd_raw)
        except ValueError:
            return jsonify({
                "type": "FeatureCollection",
                "metadata": {
                    "error": "Parametro min_rd invalido (use 0..4).",
                },
                "features": [],
            }), 400
        if min_rd < 0 or min_rd > 4:
            return jsonify({
                "type": "FeatureCollection",
                "metadata": {
                    "error": "Parametro min_rd fora do intervalo 0..4.",
                },
                "features": [],
            }), 400

    body = build_ua_layers_geojson(snap, hazard=hazard, min_rd=min_rd)
    resp = jsonify(body)
    resp.headers["Content-Type"] = "application/geo+json; charset=utf-8"
    return apply_public_api_headers(resp, max_age=30)


@app.route("/api/public/fire-risk/layers")
def api_public_fire_risk_layers():
    """Feed publico GeoJSON do risco estadual de queimadas por trecho DER."""
    from core.fire_risk import get_fire_risk_geojson

    horizonte = request.args.get("horizonte", "observado")
    min_class = request.args.get("classe")
    body = get_fire_risk_geojson(horizonte=horizonte, min_class=min_class)
    resp = jsonify(body)
    resp.headers["Content-Type"] = "application/geo+json; charset=utf-8"
    return apply_public_api_headers(resp, max_age=300)


@app.route("/api/public/fire-risk/snapshot")
def api_public_fire_risk_snapshot():
    """Resumo estadual do ultimo produto de risco de queimadas publicado."""
    from core.fire_risk import get_fire_risk_snapshot

    resp = jsonify(get_fire_risk_snapshot())
    return apply_public_api_headers(resp, max_age=300)


@app.route("/api/public/fire-risk/trecho/<trecho_id>")
def api_public_fire_risk_trecho(trecho_id):
    """Detalhe de risco de queimadas para um trecho DER-SP."""
    from core.fire_risk import get_fire_risk_by_trecho

    horizonte = request.args.get("horizonte", "observado")
    body = get_fire_risk_by_trecho(trecho_id, horizonte=horizonte)
    if body is None:
        return jsonify({
            "error": "trecho_id nao encontrado",
            "trecho_id": trecho_id,
        }), 404
    resp = jsonify(body)
    return apply_public_api_headers(resp, max_age=300)


@app.route("/api/health")
def api_health():
    """Diagnostico operacional. Inclui dependencias criticas para debug rapido
em prod."""
    try:
        from core.merge_inpe import _eccodes_available
        eccodes_ok = bool(_eccodes_available())
    except Exception:
        eccodes_ok = False

    snap = state.get_snapshot()
    summary = snap.get("summary", {})
    return jsonify({
        "status": "ok",
        "last_update": snap.get("timestamp_utc"),
        "points_loaded": len(_snapshot_points(snap)),
        "points_geo": len(snap.get("points_geo") or []),
        "points_hidro": len(snap.get("points_hidro") or []),
        "regions": len(snap.get("regions", [])),
        "max_rd": summary.get("max_rd", 0),
        "data_status": summary.get("data_status"),
        "data_source": summary.get("data_source"),
        "degraded": summary.get("degraded", False),
        "files_ok": summary.get("files_ok", 0),
        "missing_24h": summary.get("missing_24h"),
        "missing_96h": summary.get("missing_96h"),
        "deps": {
            "eccodes": eccodes_ok,
        },
        "ingest": ingest.status(),
        "notifier": _notifier_status(),
    })


def _notifier_status():
    try:
        from core.notifier import notifier
        return notifier.get_status()
    except Exception:
        return {"enabled_email": False, "enabled_webhook": False}


# ============================================================================
# MAIN (modo desenvolvimento local)
# ============================================================================
if __name__ == "__main__":
    multiprocessing.freeze_support()
    port = int(os.environ.get("PORT", 5050))
    if _DEV_LOG:
        log.info("=== Servidor HTTP em http://localhost:%d ===", port)
        log.info("Pressione Ctrl+C para encerrar")
    else:
        log.info("Servidor pronto em http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
