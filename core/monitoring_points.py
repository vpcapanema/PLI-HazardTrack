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

Politica de RA (atualizada com dados dos relatorios REGEA-NIPPON 2021):
- Trechos mapeados nos relatorios usam RA real (moda da distribuicao).
- Trechos NAO mapeados retornam ra=None (SEM_DADO). Nunca inventar RA.
- Fonte: core/ra_official.py (Tabelas 3.3.3.1-3 e 3.3.3.1-4).
"""

from pathlib import Path
import json
import logging

from .ra_official import get_ra_for_point

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
    except (OSError, json.JSONDecodeError) as e:
        log.error("falha ao ler %s: %s", _DATA_FILE, e)
        return []

    # Normaliza: garante campos minimos esperados pelo aggregator
    out = []
    for p in data:
        # RA real dos relatorios REGEA-NIPPON 2021 (se disponivel)
        region_id = p.get("region_id_hint")
        ra_geo, ra_hid, ra_source = get_ra_for_point(
            rodovia=p.get("rodovia"),
            km=p.get("km"),
            lat=float(p["lat"]),
            lon=float(p["lon"]),
            region_id=region_id,
        )
        out.append({
            "id": p["id"],
            "rodovia": p["rodovia"],
            "km": p.get("km"),
            "lat": float(p["lat"]),
            "lon": float(p["lon"]),
            # ra = max(ra_geo, ra_hid)
            # Sem dado oficial: ra=None (SEM_DADO)
            "ra": (
                max(filter(None, [ra_geo, ra_hid]))
                if any([ra_geo, ra_hid])
                else None
            ),
            "ra_geo": ra_geo,
            "ra_hid": ra_hid,
            "ra_source": ra_source,
            "nome": p.get("nome", p["id"]),
        })
    return out


MONITORING_POINTS = _load_points()
log.info("MONITORING_POINTS carregado: %d pontos", len(MONITORING_POINTS))
