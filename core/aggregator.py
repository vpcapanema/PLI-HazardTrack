"""
Orquestrador: para cada ponto de monitoramento,
busca chuva (MERGE) e calcula risco dinamico.

Mantem cache em memoria do estado atual + historico.

Politica de dados:
- Sem dado real do MERGE/INPE -> snapshot fica em estado NO_DATA.
- NUNCA usa mock no caminho operacional. Sem dado real = NO_DATA.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any
from collections import deque
import logging
import os
import time
from threading import Lock

from .regions import load_regions, find_region_for_point, Region
from .monitoring_points import MONITORING_POINTS
from .merge_inpe import fetch_real_batch
from .risk import evaluate_point

log = logging.getLogger("aggregator")

# Limite de horas faltando na janela de 24h para marcar "degraded"
DEGRADED_MISSING_24H_THRESHOLD = int(
    os.environ.get("SAMAEG_DEGRADED_24H", "6")
)
# Quantos ciclos manter no historico de runtime (para a pagina de ops)
RUNTIME_HISTORY = 96


class State:
    """Estado global do sistema (thread-safe)."""
    def __init__(self):
        self._lock = Lock()
        self.regions: List[Region] = load_regions()
        self.points = MONITORING_POINTS

        # Telemetria operacional
        self.started_at = datetime.now(timezone.utc)
        self.cycle_count = 0
        self.cycle_success = 0
        self.cycle_fail = 0
        self.last_cycle_started_at = None
        self.last_cycle_finished_at = None
        self.last_cycle_duration_s = None
        self.last_error = None
        self.last_error_at = None
        # Historico curto dos ultimos ciclos (para a pagina /ops)
        self.cycle_history = deque(maxlen=RUNTIME_HISTORY)
        # Historico de RD por ponto (ultimos 24 ciclos = 4h)
        self.point_rd_history: Dict[str, deque] = {}

        # Seed inicial: pontos visiveis no mapa em "loading" (estilo sem dado).
        # Importante para Render free, onde o primeiro ciclo MERGE pode levar
        # 30-60 s e nao queremos tela vazia ate la.
        seed_points = []
        for p in self.points:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            seed_points.append({
                "id": p["id"], "nome": p["nome"],
                "rodovia": p["rodovia"], "km": p["km"],
                "lat": p["lat"], "lon": p["lon"],
                "region_id": region.id if region else None,
                "region_name": region.nome if region else None,
                "ac96h_mm": 0.0, "ac24h_mm": 0.0, "intensity_mmh": 0.0,
                "cpc": None, "icc_geo": 0, "icc_hid": 0,
                "ra": p.get("ra", 1),
                "rd_geo": 0, "rd_hid": 0, "rd": 0, "nivel": "Aguardando",
                "source": "NO_DATA",
            })

        self.snapshot: Dict[str, Any] = {
            "timestamp_utc": None,
            "points": seed_points,
            "summary": {
                "total": len(self.points),
                "by_level": {0: len(self.points), 1: 0, 2: 0, 3: 0, 4: 0},
                "max_rd": 0,
                "max_rd_point": None,
                # Estado inicial antes do primeiro update terminar.
                # A UI usa isto para mostrar tela "Carregando" em vez
                # de aparente snapshot vazio.
                "data_status": "loading",
                "data_source": "MERGE/INPE",
                "degraded": False,
                "files_ok": 0,
                "missing_24h": 0,
                "missing_96h": 0,
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
        t0 = time.monotonic()
        self.cycle_count += 1
        self.last_cycle_started_at = now
        log.info(f"Atualizando snapshot @ {now.isoformat()}")

        try:
            self._do_update(now)
            self.cycle_success += 1
            outcome = "ok"
            err_msg = None
        except Exception as e:  # noqa: BLE001
            self.cycle_fail += 1
            self.last_error = str(e)
            self.last_error_at = datetime.now(timezone.utc)
            outcome = "error"
            err_msg = str(e)
            log.exception("erro no ciclo de update: %s", e)
            # Tambem publica um snapshot 'no_data' para a UI saber
            try:
                self._publish_no_data(now)
            except Exception:
                pass
        finally:
            duration = time.monotonic() - t0
            self.last_cycle_finished_at = datetime.now(timezone.utc)
            self.last_cycle_duration_s = round(duration, 2)
            summary = (
                self.snapshot.get("summary", {})
                if hasattr(self, "snapshot") else {}
            )
            self.cycle_history.append({
                "started_at": now.isoformat(),
                "finished_at": self.last_cycle_finished_at.isoformat(),
                "duration_s": round(duration, 2),
                "outcome": outcome,
                "data_status": summary.get("data_status"),
                "files_ok": summary.get("files_ok"),
                "missing_24h": summary.get("missing_24h"),
                "max_rd": summary.get("max_rd", 0),
                "error": err_msg,
            })

    def _do_update(self, now):
        """
        Logica do ciclo, separada para captura de
        erro/timing em update().
        """
        # Caminho de producao: SOMENTE MERGE/INPE real.
        coords = [(p["lat"], p["lon"]) for p in self.points]
        rain_batch = fetch_real_batch(coords, now)

        if rain_batch is None:
            # Falha total: sem dado real do MERGE/INPE
            log.error(
                "MERGE/INPE indisponivel: snapshot marcado como NO_DATA "
                "(sem dado, sem RD calculado)"
            )
            self._publish_no_data(now)
            return
        else:
            files_ok = rain_batch[0].files_ok
            missing_24h = rain_batch[0].missing_24h
            missing_96h = rain_batch[0].missing_96h
            data_source = "MERGE/INPE"
            data_status = (
                "ok"
                if missing_24h < DEGRADED_MISSING_24H_THRESHOLD
                else "degraded"
            )
            degraded = data_status == "degraded"

        new_points = []
        by_level = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        max_rd = -1
        max_rd_point = None

        for idx, p in enumerate(self.points):
            try:
                region = find_region_for_point(
                    p["lat"], p["lon"], self.regions
                )
                rain = rain_batch[idx]
                result = evaluate_point(
                    lat=p["lat"], lon=p["lon"],
                    region=region,
                    ac96h=rain.ac96h_mm,
                    intensity=rain.intensity_mmh,
                    ac24h=rain.ac24h_mm,
                    ra=p["ra"],
                    ra_geo=p.get("ra_geo"),
                    ra_hid=p.get("ra_hid")
                )
                pt = {
                    "id": p["id"], "nome": p["nome"],
                "rodovia": p["rodovia"], "km": p["km"],
                    "lat": p["lat"], "lon": p["lon"],
                    "region_id": result.region_id,
                    "region_name": result.region_name,
                    "ac96h_mm": result.ac96h_mm, "ac24h_mm": result.ac24h_mm,
                    "intensity_mmh": result.intensity_mmh,
                    "cpc": result.cpc,
                    "icc_geo": result.icc_geo, "icc_hid": result.icc_hid,
                    "ra": result.ra,
                    "rd_geo": result.rd_geo, "rd_hid": result.rd_hid,
                    "rd": result.rd, "nivel": result.nivel,
                    "source": rain.source
                }
                # Historico de RD por ponto
                hist = self.point_rd_history.setdefault(
                    p["id"], deque(maxlen=24)
                )
                hist.append({
                    "ts": now.isoformat(),
                    "rd": result.rd,
                    "rd_geo": result.rd_geo,
                    "rd_hid": result.rd_hid,
                    "ac96h": result.ac96h_mm,
                    "ac24h": result.ac24h_mm,
                    "cpc": result.cpc,
                })
                pt["history"] = list(hist)

                new_points.append(pt)
                by_level[result.rd] = by_level.get(result.rd, 0) + 1
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
                "data_source": data_source,
                "data_status": data_status,
                "degraded": degraded,
                "files_ok": files_ok,
                "missing_24h": missing_24h,
                "missing_96h": missing_96h,
            }

        log.info(
            (
                "  ok: %d pontos, max RD=%d, "
                "niveis=%s, status=%s (24h faltando=%d)"
            ),
            len(new_points), max(0, max_rd), by_level, data_status, missing_24h
        )

    def _publish_no_data(self, now):
        """
        Marca snapshot como NO_DATA quando o MERGE falha por completo.
        Mesmo sem dado real de chuva, publicamos os pontos de monitoramento
        com chuva zerada e nivel "Monitoramento" para que a interface
        continue mostrando a malha vigiada (importante para Render free,
        onde o eccodes pode estar indisponivel ou o INPE com latencia).
        Pontos aparecem com source="NO_DATA" para o frontend distinguir.
        """
        new_points = []
        by_level = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        for p in self.points:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            new_points.append({
                "id": p["id"], "nome": p["nome"],
                "rodovia": p["rodovia"], "km": p["km"],
                "lat": p["lat"], "lon": p["lon"],
                "region_id": region.id if region else None,
                "region_name": region.nome if region else None,
                "ac96h_mm": 0.0, "ac24h_mm": 0.0,
                "intensity_mmh": 0.0,
                "cpc": None,
                "icc_geo": 0, "icc_hid": 0,
                "ra": p.get("ra", 1),
                "rd_geo": 0, "rd_hid": 0,
                "rd": 0, "nivel": "Sem dado",
                "source": "NO_DATA",
            })
            by_level[0] += 1

        with self._lock:
            self.snapshot["timestamp_utc"] = now.isoformat()
            self.snapshot["points"] = new_points
            self.snapshot["summary"] = {
                "total": len(new_points),
                "by_level": by_level,
                "max_rd": 0,
                "max_rd_point": None,
                "max_rd_name": None,
                "data_source": "MERGE/INPE",
                "data_status": "no_data",
                "degraded": True,
                "files_ok": 0,
                "missing_24h": 24,
                "missing_96h": 96,
                "message": (
                    "Sem dado real do MERGE/INPE."
                ),
            }

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.snapshot)

    def get_runtime(self) -> Dict[str, Any]:
        """Telemetria de execucao para a pagina de operacoes."""
        with self._lock:
            return {
                "started_at": self.started_at.isoformat(),
                "uptime_s": (
                    datetime.now(timezone.utc) - self.started_at
                ).total_seconds(),
                "cycle_count": self.cycle_count,
                "cycle_success": self.cycle_success,
                "cycle_fail": self.cycle_fail,
                "last_cycle_started_at": self.last_cycle_started_at.isoformat()
                    if self.last_cycle_started_at else None,
                "last_cycle_finished_at": (
                    self.last_cycle_finished_at.isoformat()
                )
                    if self.last_cycle_finished_at else None,
                "last_cycle_duration_s": self.last_cycle_duration_s,
                "last_error": self.last_error,
                "last_error_at": self.last_error_at.isoformat()
                    if self.last_error_at else None,
                "history": list(self.cycle_history),

                "degraded_threshold": DEGRADED_MISSING_24H_THRESHOLD,
            }


# Singleton
state = State()
