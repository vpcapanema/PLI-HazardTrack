"""
Orquestrador: para cada ponto de monitoramento,
busca chuva (MERGE) e calcula risco dinamico.

Mantem cache em memoria do estado atual + historico.

Politica de dados:
- Sem dado real do MERGE/INPE -> snapshot fica em estado NO_DATA.
- NUNCA usa mock no caminho operacional. Sem dado real = NO_DATA.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from collections import deque
import logging
import os
import time
from threading import Lock

from .regions import load_regions, find_region_for_point, Region
from .zones import ZONES_GEO, ZONES_HIDRO
from .merge_inpe import (
    progress_stage,
    progress_done,
    fetch_real_batch,
    _target_hour_for,
)
from .merge_ingest import ingest
from .forecast_wrf_prec_hourly import fetch_forecast_accum_batch
from .risk import evaluate_point, compose_pdf_windows
from .notifier import notifier

log = logging.getLogger("aggregator")

# Limite de horas faltando na janela de 24h para marcar "degraded"
DEGRADED_MISSING_24H_THRESHOLD = int(
    os.environ.get("SAMAEG_DEGRADED_24H", "6")
)
# Quantos ciclos manter no historico de runtime (para a pagina de ops)
RUNTIME_HISTORY = 96
# TTL do cache da animacao temporal (Linha do Tempo), em segundos
TIMELINE_TTL_S = 600
# Quantos quadros horarios a Linha do Tempo reconstroi (Anexo C 3.4.2: 96h)
TIMELINE_FRAMES = 96
HISTORY_MAX_DAYS = int(os.environ.get("SAMAEG_HISTORY_MAX_DAYS", "1460"))
MIN_OK_HOURS_FOR_HISTORY = int(os.environ.get("SAMAEG_MIN_OK_HOURS", "24"))


def _seed_point(p: Dict[str, Any], region: Optional[Region],
                hazard: str) -> Dict[str, Any]:
    """Ponto inicial antes do primeiro ciclo MERGE."""
    return {
        "id": p["id"], "nome": p["nome"],
        "rodovia": p["rodovia"], "km": p["km"],
        "lat": p["lat"], "lon": p["lon"],
        "hazard": hazard,
        "region_id": region.id if region else None,
        "region_name": region.nome if region else None,
        "ac96h_mm": 0.0, "ac24h_mm": 0.0, "intensity_mmh": 0.0,
        "cpc": None, "icc_geo": 0, "icc_hid": 0,
        "ra": p.get("ra"),
        "ra_geo": p.get("ra_geo"), "ra_hid": p.get("ra_hid"),
        "rd_geo": 0, "rd_hid": 0, "rd": 0, "nivel": "Aguardando",
        "geometry": p.get("geometry"),
        "geometry_type": p.get("geometry_type", "polyline"),
        "source": "NO_DATA",
    }


def _no_data_point(p: Dict[str, Any], region: Optional[Region],
                   hazard: str) -> Dict[str, Any]:
    return {
        "id": p["id"], "nome": p["nome"],
        "rodovia": p["rodovia"], "km": p["km"],
        "lat": p["lat"], "lon": p["lon"],
        "hazard": hazard,
        "region_id": region.id if region else None,
        "region_name": region.nome if region else None,
        "ac96h_mm": 0.0, "ac24h_mm": 0.0,
        "intensity_mmh": 0.0,
        "cpc": None,
        "icc_geo": 0, "icc_hid": 0,
        "ra": p.get("ra"),
        "ra_geo": p.get("ra_geo"), "ra_hid": p.get("ra_hid"),
        "rd_geo": 0, "rd_hid": 0,
        "rd": 0, "nivel": "Sem dado",
        "geometry": p.get("geometry"),
        "geometry_type": p.get("geometry_type", "polyline"),
        "source": "NO_DATA",
    }


def _process_zone(
    p: Dict[str, Any],
    rain,
    fc,
    region: Optional[Region],
    hazard: str,
    now: datetime,
    history: Dict[str, deque],
) -> Dict[str, Any]:
    """Calcula RD mono-canal (geo ou hidro) para uma UA."""
    ac96h_use, ac24h_use, fonte_prev = compose_pdf_windows(
        ac72h_obs=rain.ac72h_mm, ac18h_obs=rain.ac18h_mm,
        ac96h_obs=rain.ac96h_mm, ac24h_obs=rain.ac24h_mm,
        prev24h_mm=fc.ac24h_mm if fc else None,
        prev6h_mm=fc.ac6h_mm if fc else None,
    )
    if hazard == "geo":
        result = evaluate_point(
            lat=p["lat"], lon=p["lon"], region=region,
            ac96h=ac96h_use, intensity=rain.intensity_mmh,
            ac24h=ac24h_use,
            ra_geo=p.get("ra"), ra_hid=None,
        )
        rd = result.rd_geo
    else:
        result = evaluate_point(
            lat=p["lat"], lon=p["lon"], region=region,
            ac96h=ac96h_use, intensity=rain.intensity_mmh,
            ac24h=ac24h_use,
            ra_geo=None, ra_hid=p.get("ra"),
        )
        rd = result.rd_hid

    hist_key = f"{p['id']}:{hazard}"
    hist = history.setdefault(hist_key, deque(maxlen=24))
    hist.append({
        "ts": now.isoformat(),
        "rd": rd,
        "rd_geo": result.rd_geo,
        "rd_hid": result.rd_hid,
        "ac96h": result.ac96h_mm,
        "ac24h": result.ac24h_mm,
        "cpc": result.cpc,
    })

    return {
        "id": p["id"], "nome": p["nome"],
        "rodovia": p["rodovia"], "km": p["km"],
        "lat": p["lat"], "lon": p["lon"],
        "hazard": hazard,
        "region_id": result.region_id,
        "region_name": result.region_name,
        "ac96h_mm": result.ac96h_mm, "ac24h_mm": result.ac24h_mm,
        "intensity_mmh": result.intensity_mmh,
        "ac72h_obs_mm": rain.ac72h_mm,
        "ac18h_obs_mm": rain.ac18h_mm,
        "prev24h_mm": fc.ac24h_mm if fc else None,
        "prev6h_mm": fc.ac6h_mm if fc else None,
        "fonte_chuva": fonte_prev,
        "cpc": result.cpc,
        "icc_geo": result.icc_geo, "icc_hid": result.icc_hid,
        "ra": p.get("ra"),
        "ra_geo": p.get("ra_geo"), "ra_hid": p.get("ra_hid"),
        "ra_source": p.get("ra_source"),
        "rd_geo": result.rd_geo, "rd_hid": result.rd_hid,
        "rd": rd, "nivel": result.nivel,
        "rd_geo_dist": result.rd_geo_dist,
        "rd_hid_dist": result.rd_hid_dist,
        "rd_unidades": result.rd_unidades,
        "geometry": p.get("geometry"),
        "geometry_type": p.get("geometry_type", "polyline"),
        "source": rain.source,
        "history": list(hist),
        "_rd": rd,
    }


def _rollup_levels(points: List[Dict[str, Any]]) -> Dict[int, int]:
    by_level = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for pt in points:
        by_level[pt.get("rd", 0)] = by_level.get(pt.get("rd", 0), 0) + 1
    return by_level


def _max_point(points: List[Dict[str, Any]]):
    best = None
    best_rd = -1
    for pt in points:
        rd = pt.get("rd", 0)
        if rd > best_rd:
            best_rd = rd
            best = pt
        elif (
            rd == best_rd and best is not None
            and pt.get("ac96h_mm", 0) > best.get("ac96h_mm", 0)
        ):
            best = pt
    return best_rd, best


def _resolve_now() -> datetime:
    """Hora de referencia do ciclo.

    Em producao retorna agora (UTC). Para backtest/demonstracao, defina
    SAMAEG_BACKTEST_UTC (ex.: "2023-02-19T12:00") para fixar a janela em um
    evento historico. So tem efeito quando a variavel esta presente.
    """
    override = os.environ.get("SAMAEG_BACKTEST_UTC")
    if override:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                    "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(override, fmt)
                log.warning("MODO BACKTEST ativo: now fixado em %s UTC",
                            override)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        log.warning(
            "SAMAEG_BACKTEST_UTC invalido (%s); usando hora real", override
        )
    return datetime.now(timezone.utc)


class State:
    """Estado global do sistema (thread-safe)."""
    def __init__(self):
        self._lock = Lock()
        self.regions: List[Region] = load_regions()
        # Duas malhas mono-canal (809 UAs cada). Chuva amostrada uma vez
        # por centróide (points_geo); hidro reutiliza o mesmo índice.
        self.points_geo = ZONES_GEO
        self.points_hidro = ZONES_HIDRO

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
        # Cache da serie horaria do ultimo ciclo (reaproveitada pela
        # Linha do Tempo, evitando novo download dos GRIBs)
        self._series_cache: Optional[Dict[str, Any]] = None

        # Seed inicial: pontos visiveis no mapa em "loading" (estilo sem dado).
        # Importante para Render free, onde o primeiro ciclo MERGE pode levar
        # 30-60 s e nao queremos tela vazia ate la.
        seed_geo = []
        seed_hidro = []
        for p in self.points_geo:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            seed_geo.append(_seed_point(p, region, "geo"))
        for p in self.points_hidro:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            seed_hidro.append(_seed_point(p, region, "hidro"))

        self.snapshot: Dict[str, Any] = {
            "timestamp_utc": None,
            "points_geo": seed_geo,
            "points_hidro": seed_hidro,
            "points": seed_geo + seed_hidro,
            "summary": {
                "total": len(self.points_geo) + len(self.points_hidro),
                "total_geo": len(self.points_geo),
                "total_hidro": len(self.points_hidro),
                "by_level": {0: len(self.points_geo) + len(self.points_hidro),
                             1: 0, 2: 0, 3: 0, 4: 0},
                "by_level_geo": {0: len(self.points_geo), 1: 0, 2: 0, 3: 0, 4: 0},
                "by_level_hidro": {0: len(self.points_hidro), 1: 0, 2: 0, 3: 0, 4: 0},
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
        now = _resolve_now()
        t0 = time.monotonic()
        self.cycle_count += 1
        self.last_cycle_started_at = now
        log.info("Atualizando snapshot @ %s", now.isoformat())

        published = False
        try:
            published = self._do_update(now)
            if published:
                self.cycle_success += 1
                outcome = "ok"
            else:
                outcome = "skipped"
            err_msg = None
        except Exception as e:  # noqa: BLE001
            self.cycle_fail += 1
            self.last_error = str(e)
            self.last_error_at = datetime.now(timezone.utc)
            outcome = "error"
            err_msg = str(e)
            published = True
            log.exception("erro no ciclo de update: %s", e)
            # Tambem publica um snapshot 'no_data' para a UI saber
            try:
                self._publish_no_data(now)
            except Exception:
                pass
        finally:
            if published:
                progress_done()
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

    def _do_update(self, now) -> bool:
        """
        Logica do ciclo, separada para captura de
        erro/timing em update().

        Retorna True se publicou snapshot (ok/degraded/no_data); False se
        o ingest ainda esta populando o cache (mantem loading na UI).
        """
        # Caminho de producao: SOMENTE MERGE/INPE real. with_series=True
        # guarda a serie horaria para a Linha do Tempo reaproveitar.
        coords = [(p["lat"], p["lon"]) for p in self.points_geo]
        ingest.configure(coords)
        rain_batch = ingest.get_rain_batch(
            coords, now, with_series=True,
        )

        if rain_batch is None:
            if ingest.should_wait():
                log.info(
                    "MERGE ingest em andamento; mantendo snapshot loading"
                )
                return False
            log.error(
                "MERGE/INPE indisponivel: snapshot marcado como NO_DATA "
                "(sem dado, sem RD calculado)"
            )
            self._publish_no_data(now)
            return True
        else:
            files_ok = rain_batch[0].files_ok
            missing_24h = rain_batch[0].missing_24h
            missing_96h = rain_batch[0].missing_96h
            # Guarda a serie horaria do ciclo para a Linha do Tempo
            with self._lock:
                self._series_cache = {
                    "built_at": now,
                    "target": now,
                    "series": [r.series for r in rain_batch],
                }
            data_source = "MERGE/INPE"
            data_status = (
                "ok"
                if missing_24h < DEGRADED_MISSING_24H_THRESHOLD
                else "degraded"
            )
            degraded = data_status == "degraded"

        progress_stage("aggregate")
        progress_stage("forecast")
        # Previsao WRF horaria (para a composicao do PDF: 72h obs + 24h prev
        # geologico; 18h obs + 6h prev hidrologico). Se indisponivel, o ciclo
        # degrada de forma transparente para observado-apenas (flag abaixo).
        try:
            forecast_batch = fetch_forecast_accum_batch(coords, now)
        except Exception as e:  # noqa: BLE001
            log.warning("previsao WRF indisponivel (%s); usando observado", e)
            forecast_batch = None
        forecast_ok = forecast_batch is not None
        forecast_source = (
            forecast_batch[0].source
            if forecast_ok and forecast_batch[0] else None
        )
        forecast_count = 0

        progress_stage("risk")
        new_geo = []
        new_hidro = []
        forecast_count = 0

        for idx, p in enumerate(self.points_geo):
            try:
                region = find_region_for_point(
                    p["lat"], p["lon"], self.regions
                )
                rain = rain_batch[idx]
                fc = forecast_batch[idx] if forecast_batch else None
                if fc is not None:
                    forecast_count += 1
                new_geo.append(_process_zone(
                    p, rain, fc, region, "geo", now, self.point_rd_history
                ))
            except Exception as e:
                log.error("erro UA geo %s: %s", p["id"], e)

        for idx, p in enumerate(self.points_hidro):
            try:
                region = find_region_for_point(
                    p["lat"], p["lon"], self.regions
                )
                rain = rain_batch[idx]
                fc = forecast_batch[idx] if forecast_batch else None
                new_hidro.append(_process_zone(
                    p, rain, fc, region, "hidro", now, self.point_rd_history
                ))
            except Exception as e:
                log.error("erro UA hidro %s: %s", p["id"], e)

        for pt in new_geo + new_hidro:
            pt.pop("_rd", None)

        by_level_geo = _rollup_levels(new_geo)
        by_level_hidro = _rollup_levels(new_hidro)
        max_geo_rd, max_geo_pt = _max_point(new_geo)
        max_hid_rd, max_hid_pt = _max_point(new_hidro)
        if max_geo_rd >= max_hid_rd:
            max_rd = max(0, max_geo_rd)
            max_rd_point = max_geo_pt
            max_rd_hazard = "geo"
        else:
            max_rd = max(0, max_hid_rd)
            max_rd_point = max_hid_pt
            max_rd_hazard = "hidro"
        by_level = {
            i: by_level_geo.get(i, 0) + by_level_hidro.get(i, 0)
            for i in range(5)
        }

        progress_stage("publish")
        with self._lock:
            self.snapshot["timestamp_utc"] = now.isoformat()
            self.snapshot["points_geo"] = new_geo
            self.snapshot["points_hidro"] = new_hidro
            self.snapshot["points"] = new_geo + new_hidro
            self.snapshot["summary"] = {
                "total": len(new_geo) + len(new_hidro),
                "total_geo": len(new_geo),
                "total_hidro": len(new_hidro),
                "by_level": by_level,
                "by_level_geo": by_level_geo,
                "by_level_hidro": by_level_hidro,
                "max_rd": max_rd,
                "max_rd_point": max_rd_point["id"] if max_rd_point else None,
                "max_rd_name": max_rd_point["nome"] if max_rd_point else None,
                "max_rd_hazard": max_rd_hazard,
                "data_source": data_source,
                "data_status": data_status,
                "degraded": degraded,
                "files_ok": files_ok,
                "missing_24h": missing_24h,
                "missing_96h": missing_96h,
                # Composicao observado+previsto (Produto 6, secao 4.5.3)
                "forecast_ok": forecast_ok,
                "forecast_source": forecast_source,
                "forecast_count": forecast_count,
                "rd_basis": (
                    "obs+prev (72h+24h / 18h+6h)" if forecast_ok
                    else "OBSERVADO (previsao WRF indisponivel)"
                ),
            }

        log.info(
            (
                "  ok: %d geo + %d hidro, max RD=%d, geo=%s hidro=%s, "
                "status=%s (24h faltando=%d) | previsao=%s (%d/%d zonas)"
            ),
            len(new_geo), len(new_hidro), max_rd, by_level_geo,
            by_level_hidro, data_status, missing_24h,
            forecast_ok, forecast_count, len(self.points_geo)
        )

        # Notificacao de alertas por canal (falha NUNCA interrompe ciclo)
        try:
            summary = self.snapshot.get("summary", {})
            notifier.evaluate(new_geo, summary, now, channel="geo")
            notifier.evaluate(new_hidro, summary, now, channel="hidro")
        except Exception as e:  # noqa: BLE001
            log.error("notificacao falhou (ignorado): %s", e)
        return True

    def _publish_no_data(self, now):
        """
        Marca snapshot como NO_DATA quando o MERGE falha por completo.
        Mesmo sem dado real de chuva, publicamos os pontos de monitoramento
        com chuva zerada e nivel "Monitoramento" para que a interface
        continue mostrando a malha vigiada (importante para Render free,
        onde o eccodes pode estar indisponivel ou o INPE com latencia).
        Pontos aparecem com source="NO_DATA" para o frontend distinguir.
        """
        new_geo = []
        new_hidro = []
        for p in self.points_geo:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            new_geo.append(_no_data_point(p, region, "geo"))
        for p in self.points_hidro:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            new_hidro.append(_no_data_point(p, region, "hidro"))
        n0 = len(new_geo) + len(new_hidro)

        with self._lock:
            self.snapshot["timestamp_utc"] = now.isoformat()
            self.snapshot["points_geo"] = new_geo
            self.snapshot["points_hidro"] = new_hidro
            self.snapshot["points"] = new_geo + new_hidro
            self.snapshot["summary"] = {
                "total": n0,
                "total_geo": len(new_geo),
                "total_hidro": len(new_hidro),
                "by_level": {0: n0, 1: 0, 2: 0, 3: 0, 4: 0},
                "by_level_geo": {0: len(new_geo), 1: 0, 2: 0, 3: 0, 4: 0},
                "by_level_hidro": {0: len(new_hidro), 1: 0, 2: 0, 3: 0, 4: 0},
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
                    "Nao foi possivel obter dados do MERGE/CPTEC neste "
                    "momento. Nova tentativa automatica em ate 10 min."
                ),
            }

    def compute_snapshot_at(self, as_of_utc: datetime) -> Dict[str, Any]:
        """Consulta pontual no passado (baixa MERGE da epoca, sem WRF).

        Nao altera o snapshot ao vivo nem dispara notificacoes.
        """
        if as_of_utc.tzinfo is None:
            as_of_utc = as_of_utc.replace(tzinfo=timezone.utc)
        now_real = datetime.now(timezone.utc)
        if as_of_utc > now_real:
            return self._historical_error(
                as_of_utc, "Data no futuro — escolha um instante passado."
            )
        age_days = (now_real - as_of_utc).total_seconds() / 86400
        if age_days > HISTORY_MAX_DAYS:
            return self._historical_error(
                as_of_utc,
                f"Consulta limitada aos ultimos {HISTORY_MAX_DAYS} dias.",
            )

        coords = [(p["lat"], p["lon"]) for p in self.points_geo]
        log.info(
            "Consulta historica MERGE @ %s (target ~%s)",
            as_of_utc.isoformat(),
            _target_hour_for(as_of_utc).isoformat(),
        )
        rain_batch = fetch_real_batch(
            coords, as_of_utc, with_series=False, force_sync=True,
        )
        if rain_batch is None:
            return self._historical_error(
                as_of_utc,
                "MERGE/INPE indisponivel para esta data "
                "(arquivos ausentes ou rede).",
            )

        files_ok = rain_batch[0].files_ok
        missing_24h = rain_batch[0].missing_24h
        missing_96h = rain_batch[0].missing_96h
        if files_ok < MIN_OK_HOURS_FOR_HISTORY:
            return self._historical_error(
                as_of_utc,
                f"Dados insuficientes ({files_ok}h validas; "
                f"minimo {MIN_OK_HOURS_FOR_HISTORY}h).",
            )

        data_status = (
            "ok"
            if missing_24h < DEGRADED_MISSING_24H_THRESHOLD
            else "degraded"
        )
        hist_scratch: Dict[str, deque] = {}
        new_geo = []
        new_hidro = []
        for idx, p in enumerate(self.points_geo):
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            new_geo.append(_process_zone(
                p, rain_batch[idx], None, region, "geo",
                as_of_utc, hist_scratch,
            ))
        for idx, p in enumerate(self.points_hidro):
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            new_hidro.append(_process_zone(
                p, rain_batch[idx], None, region, "hidro",
                as_of_utc, hist_scratch,
            ))
        for pt in new_geo + new_hidro:
            pt.pop("_rd", None)

        by_level_geo = _rollup_levels(new_geo)
        by_level_hidro = _rollup_levels(new_hidro)
        max_geo_rd, max_geo_pt = _max_point(new_geo)
        max_hid_rd, max_hid_pt = _max_point(new_hidro)
        if max_geo_rd >= max_hid_rd:
            max_rd = max(0, max_geo_rd)
            max_rd_point = max_geo_pt
            max_rd_hazard = "geo"
        else:
            max_rd = max(0, max_hid_rd)
            max_rd_point = max_hid_pt
            max_rd_hazard = "hidro"
        by_level = {
            i: by_level_geo.get(i, 0) + by_level_hidro.get(i, 0)
            for i in range(5)
        }

        return {
            "timestamp_utc": as_of_utc.isoformat(),
            "points_geo": new_geo,
            "points_hidro": new_hidro,
            "points": new_geo + new_hidro,
            "summary": {
                "total": len(new_geo) + len(new_hidro),
                "total_geo": len(new_geo),
                "total_hidro": len(new_hidro),
                "by_level": by_level,
                "by_level_geo": by_level_geo,
                "by_level_hidro": by_level_hidro,
                "max_rd": max_rd,
                "max_rd_point": max_rd_point["id"] if max_rd_point else None,
                "max_rd_name": max_rd_point["nome"] if max_rd_point else None,
                "max_rd_hazard": max_rd_hazard,
                "data_source": "MERGE/INPE (consulta historica)",
                "data_status": data_status,
                "degraded": data_status == "degraded",
                "files_ok": files_ok,
                "missing_24h": missing_24h,
                "missing_96h": missing_96h,
                "forecast_ok": False,
                "forecast_source": None,
                "forecast_count": 0,
                "historical": True,
                "consulted_at": as_of_utc.isoformat(),
                "merge_target_hour": rain_batch[0].timestamp_utc,
                "rd_basis": (
                    "OBSERVADO (consulta historica — sem previsao WRF)"
                ),
            },
            "regions": self.snapshot.get("regions", []),
        }

    def _historical_error(
        self, as_of_utc: datetime, message: str,
    ) -> Dict[str, Any]:
        new_geo = []
        new_hidro = []
        for p in self.points_geo:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            new_geo.append(_no_data_point(p, region, "geo"))
        for p in self.points_hidro:
            region = find_region_for_point(p["lat"], p["lon"], self.regions)
            new_hidro.append(_no_data_point(p, region, "hidro"))
        n0 = len(new_geo) + len(new_hidro)
        return {
            "timestamp_utc": as_of_utc.isoformat(),
            "points_geo": new_geo,
            "points_hidro": new_hidro,
            "points": new_geo + new_hidro,
            "summary": {
                "total": n0,
                "by_level": {0: n0, 1: 0, 2: 0, 3: 0, 4: 0},
                "by_level_geo": {0: len(new_geo), 1: 0, 2: 0, 3: 0, 4: 0},
                "by_level_hidro": {0: len(new_hidro), 1: 0, 2: 0, 3: 0, 4: 0},
                "max_rd": 0,
                "data_status": "no_data",
                "historical": True,
                "consulted_at": as_of_utc.isoformat(),
                "message": message,
            },
            "regions": self.snapshot.get("regions", []),
        }

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.snapshot)

    def build_timeline(
        self, frames: int = TIMELINE_FRAMES
    ) -> Dict[str, Any]:
        """Anima a evolucao do Risco Dinamico hora-a-hora (Anexo C, 3.4.2).

        Reaproveita a serie horaria de 96h ja baixada pelo ciclo (sem novo
        download); na primeira chamada antes do primeiro ciclo, baixa 96h
        uma vez. Para cada quadro H (horas atras) o RD de cada zona usa a
        janela movel OBSERVADA terminando naquela hora, limitada a janela
        de ingestao de 96h: o quadro "agora" e exato (= snapshot ao vivo) e
        os quadros mais antigos refletem o acumulado disponivel ate ali.
        Sem previsao (a timeline e so chuva observada).

        Retorna dict pronto para JSON; ``available=False`` quando nao ha
        serie horaria disponivel (MERGE/INPE indisponivel).
        """
        frames = max(2, min(TIMELINE_FRAMES, int(frames)))
        window = 96
        now = _resolve_now()

        with self._lock:
            cache = self._series_cache
        series = None
        target_hour = None
        if cache and (now - cache["built_at"]).total_seconds() \
                < TIMELINE_TTL_S:
            series = cache["series"]
            target_hour = cache["target"]
        if series is None:
            coords = [(p["lat"], p["lon"]) for p in self.points_geo]
            ingest.configure(coords)
            res = ingest.get_hourly_series(coords, now, hours_back=window)
            if res is None:
                return {
                    "available": False,
                    "reason": "MERGE/INPE indisponivel",
                }
            target_hour, series = res

        avail = len(series[0]) if series and series[0] else 0
        frames = min(frames, avail)
        if frames < 2:
            return {
                "available": False,
                "reason": "serie horaria insuficiente",
            }

        regions_geo = [
            find_region_for_point(p["lat"], p["lon"], self.regions)
            for p in self.points_geo
        ]
        regions_hidro = [
            find_region_for_point(p["lat"], p["lon"], self.regions)
            for p in self.points_hidro
        ]

        out_frames = []
        # Do mais antigo (H = frames-1) ao mais recente (H = 0)
        for h in range(frames - 1, -1, -1):
            ts = (target_hour - timedelta(hours=h)).isoformat()
            rd_geo: Dict[str, int] = {}
            rd_hidro: Dict[str, int] = {}
            for i, p in enumerate(self.points_geo):
                s = series[i]
                result = evaluate_point(
                    lat=p["lat"], lon=p["lon"], region=regions_geo[i],
                    ac96h=sum(s[h:h + window]),
                    intensity=s[h],
                    ac24h=sum(s[h:h + 24]),
                    ra_geo=p.get("ra"), ra_hid=None,
                )
                rd_geo[p["id"]] = result.rd_geo
            for i, p in enumerate(self.points_hidro):
                s = series[i]
                result = evaluate_point(
                    lat=p["lat"], lon=p["lon"], region=regions_hidro[i],
                    ac96h=sum(s[h:h + window]),
                    intensity=s[h],
                    ac24h=sum(s[h:h + 24]),
                    ra_geo=None, ra_hid=p.get("ra"),
                )
                rd_hidro[p["id"]] = result.rd_hid
            out_frames.append({
                "ts": ts,
                "rd_geo": rd_geo,
                "rd_hidro": rd_hidro,
                "rd": rd_geo,
            })

        return {
            "available": True,
            "target_utc": target_hour.isoformat(),
            "frames": out_frames,
            "frame_count": len(out_frames),
            "window_h": window,
            "source": "MERGE/INPE (observado)",
        }

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
