"""
Chuva observada por pluviometros (SIBH / SP Aguas) como fonte PRIMARIA.

Motivacao
---------
O MERGE/INPE publica cada hora com ~4 h 25 min de atraso: a hora mais
recente pedida pelo ciclo quase nunca esta disponivel e a intensidade
horaria (base do CPC geologico) fica zerada. A rede telemetrica do Estado
(CEMADEN, SP Aguas, SABESP, IAC, ANA, INMET...) agregada pelo SIBH tem
latencia de minutos.

Fonte (API do portal SIBH; sem documentacao oficial publicada)
--------------------------------------------------------------
- Estacoes com dado recente (coordenadas):
    GET .../sibh/api/v2/measurements/now
        ?station_type_id=2&hours=72&public=true
- Serie horaria por estacao (valor = soma das leituras da hora, UTC):
    GET .../sibh/api/v2/measurements
        ?station_prefix_ids[]=ID&start_date=AAAA-MM-DDTHH:MM
        &end_date=AAAA-MM-DDTHH:MM&group_type=hour&serializer=very_short

Metodologia
-----------
1. Hora-alvo = ultima hora UTC completa (hora cheia corrente - 1 h).
2. Para cada UA, estacoes num raio ``RADIUS_KM`` recebem peso IDW p=2.
3. Em cada hora h (0..95) a chuva da UA e o IDW apenas das estacoes que
   REPORTARAM naquela hora (estacao sem leitura nao conta como zero).
4. A UA usa pluviometros se a hora-alvo tiver cobertura e se pelo menos
   ``MIN_COVERAGE`` das horas de 24 h e de 96 h tiverem cobertura. Horas
   sem nenhuma estacao somam 0 mm (subestimativa limitada pelo criterio).
5. UA sem cobertura mantem o MERGE/INPE. Falha da API -> ciclo inteiro
   segue com MERGE. Nunca inventa dado.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from .gauge_correction import _haversine_km

log = logging.getLogger("gauge_primary")

ENABLED = os.environ.get("SAMAEG_GAUGE_PRIMARY", "1").strip() not in (
    "0", "false", "False", "no",
)
STATIONS_URL = os.environ.get(
    "SAMAEG_SIBH_URL",
    "https://apps.spaguas.sp.gov.br/sibh/api/v2/measurements/now",
)
MEASUREMENTS_URL = os.environ.get(
    "SAMAEG_SIBH_MEASUREMENTS_URL",
    "https://apps.spaguas.sp.gov.br/sibh/api/v2/measurements",
)
HTTP_TIMEOUT = float(os.environ.get("SAMAEG_GAUGE_PRIMARY_TIMEOUT", "60"))
# Raio de influencia de uma estacao na interpolacao (km).
RADIUS_KM = float(os.environ.get("SAMAEG_GAUGE_PRIMARY_RADIUS_KM", "15"))
# Fracao minima de horas com ao menos uma estacao reportando.
MIN_COVERAGE = float(os.environ.get(
    "SAMAEG_GAUGE_PRIMARY_MIN_COVERAGE", "0.9",
))
# Intervalo minimo entre consultas a API (s).
MIN_INTERVAL_S = int(os.environ.get(
    "SAMAEG_GAUGE_PRIMARY_MIN_INTERVAL_S", "300",
))
WINDOW_H = 96
# Consulta incremental: re-busca as ultimas horas (dado atrasado).
RECENT_H = 6
# Recarga completa (lista de estacoes + 96 h) a cada 6 h.
FULL_REFRESH_S = 6 * 3600
# Limite da API: "station_prefix_ids" aceita no maximo 10 itens.
BATCH_SIZE = 10
MIN_DISTANCE_KM = 0.5
SOURCE_LABEL = "SIBH/SP Aguas (pluviometros)"

_HEADERS = {
    "User-Agent": "PLI-HazardTrack/1.0 (gauge-primary)",
    "Accept": "application/json",
}


@dataclass
class GaugePrimaryMeta:
    """Estatisticas do ciclo (uso administrativo)."""
    enabled: bool = True
    applied: bool = False
    source: str = SOURCE_LABEL
    radius_km: float = RADIUS_KM
    min_coverage: float = MIN_COVERAGE
    target_hour: Optional[str] = None
    stations_near: int = 0
    stations_last_hour: int = 0
    points_total: int = 0
    points_gauge: int = 0
    points_fallback: int = 0
    error: Optional[str] = None
    fetched_at: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class PointSeries:
    series: List[float]      # mm por hora; indice 0 = hora-alvo
    covered_24: int
    covered_96: int
    covered_target: bool
    stations: int


def _now_mono() -> float:
    return time.monotonic()


def target_hour_for(now: datetime) -> datetime:
    """Ultima hora UTC completa (a hora cheia corrente ainda esta aberta)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hour = now.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0,
    )
    return hour - timedelta(hours=1)


def parse_hour(raw: Any) -> Optional[datetime]:
    """'2026/09/15 19' (UTC, formato do group_type=hour) -> datetime."""
    try:
        return datetime.strptime(str(raw), "%Y/%m/%d %H").replace(
            tzinfo=timezone.utc,
        )
    except (TypeError, ValueError):
        return None


def _rows(payload: Any, what: str) -> List[Dict[str, Any]]:
    rows = payload.get("measurements") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"resposta SIBH sem lista de {what}")
    return rows


def _get_json(url: str, params: Dict[str, Any]) -> Any:
    """GET com a mensagem de erro da API (sem a URL) em falha HTTP."""
    r = requests.get(
        url, params=params, headers=_HEADERS, timeout=HTTP_TIMEOUT,
    )
    if r.status_code != 200:
        raise ValueError(f"SIBH HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def _fetch_station_list() -> Dict[str, Tuple[float, float]]:
    """Estacoes pluviometricas publicas com dado nas ultimas 72 h."""
    params: Dict[str, Any] = {
        "station_type_id": 2,
        "hours": 72,
        "show_all": "false",
        "serializer": "complete",
        "public": "true",
    }
    out: Dict[str, Tuple[float, float]] = {}
    for row in _rows(_get_json(STATIONS_URL, params), "estacoes"):
        sid = row.get("station_prefix_id")
        lat_raw = row.get("latitude")
        lon_raw = row.get("longitude")
        if lat_raw is None or lon_raw is None:
            continue
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (TypeError, ValueError):
            continue
        if sid is None or not (-35 < lat < 5 and -75 < lon < -30):
            continue
        out[str(sid)] = (lat, lon)
    return out


def _fetch_hourly(
    station_ids: Sequence[str], start: datetime, end: datetime,
) -> Dict[str, Dict[datetime, float]]:
    """Serie horaria (mm) por estacao entre start e end (UTC)."""
    out: Dict[str, Dict[datetime, float]] = {}
    ids = list(station_ids)
    for i in range(0, len(ids), BATCH_SIZE):
        params: Dict[str, Any] = {
            "station_prefix_ids[]": ids[i:i + BATCH_SIZE],
            "start_date": start.strftime("%Y-%m-%dT%H:%M"),
            "end_date": end.strftime("%Y-%m-%dT%H:%M"),
            "group_type": "hour",
            "serializer": "very_short",
        }
        for row in _rows(_get_json(MEASUREMENTS_URL, params), "medicoes"):
            sid = row.get("station_prefix_id")
            hour = parse_hour(row.get("date"))
            raw_value = row.get("value")
            if raw_value is None:
                continue
            try:
                value = float(raw_value)
                qtd = int(row.get("qtd") or 0)
            except (TypeError, ValueError):
                continue
            if (
                sid is None or hour is None or qtd <= 0
                or not math.isfinite(value) or value < 0
            ):
                continue
            out.setdefault(str(sid), {})[hour] = value
    return out


def _stations_near(
    stations: Dict[str, Tuple[float, float]],
    coords: Sequence[Tuple[float, float]],
) -> Dict[str, Tuple[float, float]]:
    """Filtra estacoes a <= RADIUS_KM de ao menos uma UA."""
    if not coords:
        return {}
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    pad_lat = RADIUS_KM / 111.0
    mean_lat = math.radians(sum(lats) / len(lats))
    pad_lon = RADIUS_KM / (111.0 * max(0.1, math.cos(mean_lat)))
    lat_min, lat_max = min(lats) - pad_lat, max(lats) + pad_lat
    lon_min, lon_max = min(lons) - pad_lon, max(lons) + pad_lon
    out: Dict[str, Tuple[float, float]] = {}
    for sid, (slat, slon) in stations.items():
        if not (lat_min <= slat <= lat_max and lon_min <= slon <= lon_max):
            continue
        if any(
            _haversine_km(lat, lon, slat, slon) <= RADIUS_KM
            for lat, lon in coords
        ):
            out[sid] = (slat, slon)
    return out


class GaugeSeriesStore:
    """Cache em RAM da serie horaria das estacoes proximas as UAs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._stations: Dict[str, Tuple[float, float]] = {}
        self._values: Dict[str, Dict[datetime, float]] = {}
        self._coords_key: Optional[Tuple[Tuple[float, float], ...]] = None
        self._last_target: Optional[datetime] = None
        self._last_fetch: Optional[float] = None
        self._last_full: Optional[float] = None
        self._fetched_at: Optional[str] = None

    def refresh(
        self, coords: Sequence[Tuple[float, float]], now: datetime,
    ) -> None:
        """Atualiza o cache (levanta excecao em falha de rede/resposta)."""
        target = target_hour_for(now)
        key = tuple((float(c[0]), float(c[1])) for c in coords)
        mono = _now_mono()
        with self._lock:
            same_coords = key == self._coords_key
            last_target = self._last_target
            if (
                same_coords and last_target == target
                and self._last_fetch is not None
                and mono - self._last_fetch < MIN_INTERVAL_S
            ):
                return
            full = (
                not same_coords
                or last_target is None
                or self._last_full is None
                or mono - self._last_full >= FULL_REFRESH_S
                or target < last_target
                or target - last_target > timedelta(hours=RECENT_H)
                or not self._stations
            )
            stations = dict(self._stations)

        if full:
            stations = _stations_near(_fetch_station_list(), coords)
        span = WINDOW_H if full else RECENT_H
        start = target - timedelta(hours=span - 1)
        end = target + timedelta(minutes=59)
        fetched = (
            _fetch_hourly(sorted(stations), start, end) if stations else {}
        )
        oldest = target - timedelta(hours=WINDOW_H - 1)

        with self._lock:
            values: Dict[str, Dict[datetime, float]] = {}
            for sid in stations:
                old = {} if full else self._values.get(sid, {})
                hours = {
                    h: v for h, v in old.items() if oldest <= h < start
                }
                hours.update(fetched.get(sid, {}))
                values[sid] = hours
            self._stations = stations
            self._values = values
            self._coords_key = key
            self._last_target = target
            self._last_fetch = mono
            if full:
                self._last_full = mono
            self._fetched_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
            )
        log.info(
            "SIBH pluviometros: %d estacoes proximas, consulta %s "
            "(%d h, alvo %s)",
            len(stations), "completa" if full else "incremental",
            span, target.isoformat(),
        )

    def data(self) -> Tuple[
        Dict[str, Tuple[float, float]],
        Dict[str, Dict[datetime, float]],
        Optional[datetime],
        Optional[str],
    ]:
        with self._lock:
            return (
                dict(self._stations),
                {sid: dict(v) for sid, v in self._values.items()},
                self._last_target,
                self._fetched_at,
            )


def build_point_series(
    coords: Sequence[Tuple[float, float]],
    stations: Dict[str, Tuple[float, float]],
    values: Dict[str, Dict[datetime, float]],
    target: datetime,
) -> List[Optional[PointSeries]]:
    """IDW hora a hora por UA; None quando nao ha estacao no raio."""
    hours = [target - timedelta(hours=h) for h in range(WINDOW_H)]
    out: List[Optional[PointSeries]] = []
    for lat, lon in coords:
        neigh = []
        for sid, (slat, slon) in stations.items():
            d = _haversine_km(lat, lon, slat, slon)
            if d <= RADIUS_KM:
                w = 1.0 / max(d, MIN_DISTANCE_KM) ** 2
                neigh.append((values.get(sid, {}), w))
        if not neigh:
            out.append(None)
            continue
        series = [0.0] * WINDOW_H
        covered = [False] * WINDOW_H
        for h, hour in enumerate(hours):
            num = 0.0
            den = 0.0
            for vals, w in neigh:
                v = vals.get(hour)
                if v is None:
                    continue
                num += w * v
                den += w
            if den > 0:
                series[h] = num / den
                covered[h] = True
        out.append(PointSeries(
            series=series,
            covered_24=sum(covered[:24]),
            covered_96=sum(covered),
            covered_target=covered[0],
            stations=len(neigh),
        ))
    return out


def _qualifies(ps: PointSeries) -> bool:
    return (
        ps.covered_target
        and ps.covered_24 >= math.ceil(MIN_COVERAGE * 24)
        and ps.covered_96 >= math.ceil(MIN_COVERAGE * WINDOW_H)
    )


def _apply_series(rain: Any, series: List[float]) -> None:
    setattr(rain, "intensity_mmh", round(series[0], 2))
    setattr(rain, "ac18h_mm", round(sum(series[:18]), 2))
    setattr(rain, "ac24h_mm", round(sum(series[:24]), 2))
    setattr(rain, "ac72h_mm", round(sum(series[:72]), 2))
    setattr(rain, "ac96h_mm", round(sum(series[:96]), 2))
    setattr(rain, "source", SOURCE_LABEL)


def apply_gauge_primary(
    coords: Sequence[Tuple[float, float]],
    rain_batch: list,
    now: datetime,
) -> Tuple[GaugePrimaryMeta, List[int]]:
    """
    Substitui in-place a chuva das UAs com cobertura de pluviometros.

    Retorna (metadados, indices substituidos). Nao levanta excecao: falha
    da API -> nenhum ponto substituido (ciclo segue com MERGE/INPE).
    """
    meta = GaugePrimaryMeta(enabled=ENABLED, points_total=len(coords))
    meta.points_fallback = len(coords)
    if not ENABLED:
        return meta, []
    try:
        store.refresh(coords, now)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "pluviometros SIBH indisponiveis (%s); ciclo segue com MERGE", e,
        )
        meta.error = str(e)
        return meta, []

    stations, values, target, fetched_at = store.data()
    meta.fetched_at = fetched_at
    if target is None:
        meta.error = "sem dados de pluviometros carregados"
        return meta, []
    meta.target_hour = target.isoformat()
    meta.stations_near = len(stations)
    meta.stations_last_hour = sum(1 for v in values.values() if target in v)

    used: List[int] = []
    series = build_point_series(coords, stations, values, target)
    for i, ps in enumerate(series):
        if i >= len(rain_batch) or rain_batch[i] is None:
            continue
        if ps is None or not _qualifies(ps):
            continue
        _apply_series(rain_batch[i], ps.series)
        used.append(i)

    meta.applied = bool(used)
    meta.points_gauge = len(used)
    meta.points_fallback = len(coords) - len(used)
    log.info(
        "chuva por pluviometros: %d/%d UAs (alvo %s, %d estacoes, "
        "%d com a ultima hora)",
        len(used), len(coords), meta.target_hour,
        meta.stations_near, meta.stations_last_hour,
    )
    return meta, used


# Singleton operacional
store = GaugeSeriesStore()
