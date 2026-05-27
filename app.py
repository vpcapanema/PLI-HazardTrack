"""
SAMAEG-PLI - Sistema Automatizado de Monitoramento, Analise e Alerta Geodinamico
Versao 0.1 - Backend Flask + scheduler
"""

import logging
import os
import threading
from flask import Flask, render_template, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

from core.aggregator import state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
log = logging.getLogger("samaeg")

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)


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

    threading.Thread(target=_first_update, daemon=True).start()

    scheduler = BackgroundScheduler(daemon=True)
    # Atualizacao a cada 10 minutos (MERGE horario tem latencia ~3h, mas como pode ter
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


@app.route("/api/health")
def api_health():
    snap = state.get_snapshot()
    return jsonify({
        "status": "ok",
        "last_update": snap["timestamp_utc"],
        "points_loaded": len(snap["points"]),
        "regions": len(snap["regions"]),
        "max_rd": snap["summary"]["max_rd"]
    })


# ============================================================================
# MAIN (modo desenvolvimento local)
# ============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    log.info("Servidor pronto em http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
