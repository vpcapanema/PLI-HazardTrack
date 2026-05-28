"""
Pontos de monitoramento ao longo das rodovias SP-055 e SP-098.

PROVISORIO. Os pontos sao amostrados sobre a geometria real da malha DER-SP
(centro de cada trecho dentro das 4 regioes cobertas pelo metodo
REGEA-NIPPON 2021). A fonte canonica e o JSON gerado pelo script:

    scripts/build_monitoring_points.py  ->  core/monitoring_points_data.json

A unidade real do metodo e a Unidade de Analise (UA, polygon), nao um ponto.
Esta amostragem e aproximacao temporaria ate substituicao por:
  (a) shapefile oficial das 809 UAs (REGEA-NIPPON), ou
  (b) RA derivado de fontes publicas: CPRM (susceptibilidade)
      + iRAP-DER (vulnerabilidade) + IDESP (risco).

Politica de RA:
- Por padrao, ra=1 em todos os pontos (RA neutro). Sem dado de campo nao da
  para inferir RA confiavel; aplicar RA chutado infla alertas.
- Quando vier RA por trecho/UA, basta atualizar o JSON com o valor real.
"""

from pathlib import Path
import json
import logging

log = logging.getLogger("monitoring_points")

_DATA_FILE = Path(__file__).resolve().parent / "monitoring_points_data.json"


def _load_points():
    if not _DATA_FILE.exists():
        log.warning(
            "monitoring_points_data.json nao encontrado. "
            "Rode scripts/build_monitoring_points.py para gerar."
        )
        return []
    try:
        data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("falha ao ler %s: %s", _DATA_FILE, e)
        return []

    # Normaliza: garante campos minimos esperados pelo aggregator
    out = []
    for p in data:
        out.append({
            "id": p["id"],
            "rodovia": p["rodovia"],
            "km": p.get("km"),
            "lat": float(p["lat"]),
            "lon": float(p["lon"]),
            "ra": int(p.get("ra", 1)),     # politica: neutro ate vir RA real
            "nome": p.get("nome", p["id"]),
        })
    return out


MONITORING_POINTS = _load_points()
log.info("MONITORING_POINTS carregado: %d pontos", len(MONITORING_POINTS))
