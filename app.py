"""
SAMAEG-PLI - Sistema Automatizado de Monitoramento,
Analise e Alerta Geodinamico
Versao 0.1 - Backend Flask + scheduler
"""

import logging
import multiprocessing
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler

from core.aggregator import state
from core.ops import ops_bp
from core.actions import get_summary_actions, get_protocolo_completo
from core.merge_ingest import ingest
from core.zones import get_zones_geo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
log = logging.getLogger("samaeg")

# Silencia o ruido do health check (keep-alive bate a cada 10 min).


class _HideHealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "/api/health" not in msg


for _name in ("werkzeug", "gunicorn.access"):
    logging.getLogger(_name).addFilter(_HideHealthFilter())

app = Flask(__name__, template_folder="templates", static_folder="static")
# Sessao Flask para a pagina /ops. Em prod, defina OPS_SECRET via env var.
# Sem OPS_SECRET, geramos um random por processo (cookies caem ao reiniciar).
app.config["SECRET_KEY"] = (
    os.environ.get("OPS_SECRET") or secrets.token_hex(32)
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

app.register_blueprint(ops_bp)


# ============================================================================
# INICIALIZACAO: rodar primeira atualizacao + agendar refresh
# ============================================================================
_initialized = False
_init_lock = threading.Lock()


def _is_main_process() -> bool:
    """Evita bootstrap em filhos do ProcessPool (Windows reimporta app.py)."""
    return multiprocessing.current_process().name == "MainProcess"


def _bootstrap():
    """Primeiro ciclo + scheduler. Chamado uma unica vez por processo."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    log.info("SAMAEG-PLI iniciando...")

    coords = [(p["lat"], p["lon"]) for p in get_zones_geo()]
    ingest.configure(coords)
    ingest.start()

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
    scheduler.start()
    log.info("Scheduler ativo (refresh a cada 10 min)")


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
    return render_template("index.html")


@app.route("/api/history-hints")
def api_history_hints():
    """Datas sugeridas com alerta elevado (validacao / backtest documentado)."""
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
    from datetime import datetime, timezone
    from core.forecast_wrf_prec_hourly import fetch_forecast_accum_batch

    snap = state.get_snapshot()
    summary = snap.get("summary", {})
    points = snap.get("points_geo") or snap.get("points", [])
    coords = [(p["lat"], p["lon"]) for p in points]
    now_utc = datetime.now(timezone.utc)
    forecast = fetch_forecast_accum_batch(coords, now_utc)
    out = []
    for p, f in zip(points, forecast):
        entry = {
            "id": p["id"],
            "nome": p["nome"],
            "lat": p["lat"],
            "lon": p["lon"],
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
    log.info("Servidor pronto em http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
