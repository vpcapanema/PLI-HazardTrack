"""
Orquestrador: para cada ponto de monitoramento,
busca chuva (MERGE) e calcula risco dinamico.

Mantem cache em memoria do estado atual + historico.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any
import logging
from threading import Lock

from .regions import load_regions, find_region_for_point, Region
from .monitoring_points import MONITORING_POINTS
from .merge_inpe import fetch as fetch_rain, fetch_real_batch, fetch_mock
from .risk import evaluate_point, RiskResult

log = logging.getLogger("aggregator")


class State:
    """Estado global do sistema (thread-safe)."""
    def __init__(self):
        self._lock = Lock()
        self.regions: List[Region] = load_regions()
        self.points = MONITORING_POINTS
        self.snapshot: Dict[str, Any] = {
            "timestamp_utc": None,
            "points": [],
            "summary": {
                "total": len(self.points),
                "by_level": {0: 0, 1: 0, 2: 0, 3: 0, 4: 0},
                "max_rd": 0,
                "max_rd_point": None
            },
            "regions": [
                {
                    "id": r.id, "nome": r.nome, "rodovia": r.rodovia,
                    "k_geo": r.k_geo,
                    "polygon": [[lat, lon] for lat, lon in r.polygon]
                } for r in self.regions
            ]
        }

    def update(self):
        """Roda um ciclo completo de atualizacao."""
        now = datetime.now(timezone.utc)
        log.info(f"Atualizando snapshot @ {now.isoformat()}")

        # Tentativa BATCH com MERGE real (1 download por hora, N pontos amostrados)
        coords = [(p["lat"], p["lon"]) for p in self.points]
        rain_batch = fetch_real_batch(coords, now)
        using_real = rain_batch is not None

        new_points = []
        by_level = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        max_rd = -1   # comeca em -1 para garantir que primeiro ponto sempre vence
        max_rd_point = None

        for idx, p in enumerate(self.points):
            try:
                region = find_region_for_point(p["lat"], p["lon"], self.regions)
                if using_real:
                    rain = rain_batch[idx]
                else:
                    rain = fetch_mock(p["lat"], p["lon"], now)
                result = evaluate_point(
                    lat=p["lat"], lon=p["lon"],
                    region=region,
                    ac96h=rain.ac96h_mm,
                    intensity=rain.intensity_mmh,
                    ac24h=rain.ac24h_mm,
                    ra=p["ra"]
                )
                pt = {
                    "id": p["id"],
                    "nome": p["nome"],
                    "rodovia": p["rodovia"],
                    "km": p["km"],
                    "lat": p["lat"],
                    "lon": p["lon"],
                    "region_id": result.region_id,
                    "region_name": result.region_name,
                    "ac96h_mm": result.ac96h_mm,
                    "ac24h_mm": result.ac24h_mm,
                    "intensity_mmh": result.intensity_mmh,
                    "cpc": result.cpc,
                    "icc_geo": result.icc_geo,
                    "icc_hid": result.icc_hid,
                    "ra": result.ra,
                    "rd_geo": result.rd_geo,
                    "rd_hid": result.rd_hid,
                    "rd": result.rd,
                    "nivel": result.nivel,
                    "source": rain.source
                }
                new_points.append(pt)
                by_level[result.rd] = by_level.get(result.rd, 0) + 1
                # Pior trecho: maior RD; em empate, maior chuva acumulada 96h
                if result.rd > max_rd or (
                    result.rd == max_rd
                    and max_rd_point is not None
                    and pt["ac96h_mm"] > max_rd_point["ac96h_mm"]
                ):
                    max_rd = result.rd
                    max_rd_point = pt
            except Exception as e:
                log.error(f"erro ponto {p['id']}: {e}")

        with self._lock:
            self.snapshot["timestamp_utc"] = now.isoformat()
            self.snapshot["points"] = new_points
            self.snapshot["summary"] = {
                "total": len(new_points),
                "by_level": by_level,
                "max_rd": max(0, max_rd),
                "max_rd_point": max_rd_point["id"] if max_rd_point else None,
                "max_rd_name": max_rd_point["nome"] if max_rd_point else None,
            }

        log.info(f"  ok: {len(new_points)} pontos, max RD={max(0, max_rd)}, niveis={by_level}")

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.snapshot)


# Singleton
state = State()
