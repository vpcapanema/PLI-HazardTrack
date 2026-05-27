"""
SAMAEG-PLI - Sistema Automatizado de Monitoramento, Analise e Alerta Geodinamico
Versao 0.1 - Backend Flask + scheduler
"""

import logging
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

def initialize():
    log.info("SAMAEG-PLI iniciando...")
    state.update()  # primeiro ciclo
    scheduler = BackgroundScheduler(daemon=True)
    # Atualizacao a cada 10 minutos (MERGE horario tem latencia ~3h, mas como pode ter
    # republicacao, atualizamos com mais frequencia para nao perder)
    scheduler.add_job(state.update, "interval", minutes=10, id="merge_refresh")
    scheduler.start()
    log.info("Scheduler ativo (refresh a cada 10 min)")


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
    import os
    static_data = os.path.join(os.path.dirname(__file__), "static", "data")
    return send_from_directory(static_data, "malha_der.geojson",
                               mimetype="application/geo+json")


@app.route("/api/road-stats")
def api_road_stats():
    """Estatisticas e listas de filtros da malha."""
    from flask import send_from_directory
    import os
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
# MAIN
# ============================================================================

if __name__ == "__main__":
    initialize()
    log.info("Servidor pronto em http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False, use_reloader=False)
