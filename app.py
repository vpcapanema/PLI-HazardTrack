"""
SAMAEG-PLI - Sistema Automatizado de Monitoramento,
Analise e Alerta Geodinamico
Versao 0.1 - Backend Flask + scheduler
"""

import logging
import os
import secrets
import threading
from datetime import timedelta

from flask import Flask, render_template, jsonify
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler

from core.aggregator import state
from core.ops import ops_bp
from core.actions import get_summary_actions

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
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1, x_proto=1, x_host=1, x_prefix=1,
)

app.register_blueprint(ops_bp)


# ============================================================================
# INICIALIZACAO: rodar primeira atualizacao + agendar refresh
# ============================================================================
_initialized = False
_init_lock = threading.Lock()


def _bootstrap():
    """Primeiro ciclo + scheduler. Chamado uma unica vez por processo."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    log.info("SAMAEG-PLI iniciando...")

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
if os.environ.get("SAMAEG_DISABLE_BOOTSTRAP") != "1":
    _bootstrap()


# ============================================================================
# ROTAS
# ============================================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/snapshot")
def api_snapshot():
    """Retorna o snapshot completo do estado atual."""
    return jsonify(state.get_snapshot())


@app.route("/api/road-network")
def api_road_network():
    """Serve a malha rodoviaria DER otimizada (GeoJSON)."""
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


@app.route("/api/actions")
def api_actions():
    """Retorna acoes operacionais por nivel para o snapshot atual."""
    snap = state.get_snapshot()
    points = snap.get("points", [])
    return jsonify(get_summary_actions(points))


@app.route("/api/forecast")
def api_forecast():
    """Retorna previsao meteorologica para os pontos de monitoramento."""
    from core.forecast_cptec import fetch_forecast_batch
    points = state.get_snapshot().get("points", [])
    coords = [(p["lat"], p["lon"]) for p in points]
    forecast = fetch_forecast_batch(coords)
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
                "ac24h_forecast_mm": f.ac24h_forecast_mm,
                "intensity_forecast_mmh": f.intensity_forecast_mmh,
                "forecast_time": (
                    f.forecast_time.isoformat() if f.forecast_time else None
                ),
                "cidade": f.cidade,
                "source": f.source,
            })
        else:
            entry["forecast"] = None
        out.append(entry)
    return jsonify({"forecast": out, "source": "CPTEC/INPE"})


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
        "points_loaded": len(snap.get("points", [])),
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
    })


# ============================================================================
# MAIN (modo desenvolvimento local)
# ============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    log.info("Servidor pronto em http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
