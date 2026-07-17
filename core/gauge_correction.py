"""
Correcao do satelite MERGE/INPE por medicoes de solo (DAEE/CEMADEN).

Motivacao
---------
O produto MERGE/INPE (GPM-IMERG-late) e a fonte primaria de chuva do sistema.
Em celulas SEM correcao por pluviometro (campo ``NEST`` do GRIB indefinido), o
IMERG-late e puramente satelital e pode SUPERESTIMAR conveccao persistente
(o algoritmo de "morphing" propaga a mesma celula de chuva por varias horas
entre passagens de satelite). Isso gera acumulados irreais e alertas
falso-positivos.

Este modulo ancora o satelite na realidade medida no chao, usando a rede
pluviometrica automatica do Estado de Sao Paulo (DAEE + CEMADEN) publicada
pelo SIBH:

    GET https://apps.spaguas.sp.gov.br/sibh/api/v2/measurements/now
        ?station_type_id=2&hours=N&public=true

Metodologia (documentada nas paginas administrativas)
-----------------------------------------------------
Para cada Unidade de Analise (ponto p) e uma janela de acumulacao:

1. Selecionam-se as estacoes de solo com dado recente dentro de um raio
   ``GAUGE_RADIUS_KM`` (padrao 30 km) de p.
2. Interpola-se a chuva de solo em p por Inverso da Distancia ao Quadrado
   (IDW, p=2) -> ``g`` (mm).
3. Define-se o peso do solo ``w`` pela proximidade da estacao mais proxima:
       w = w_max * (1 - d_min / R)      (0 se nenhuma estacao no raio)
   de modo que perto de um pluviometro confia-se no solo e longe mantem-se
   o satelite.
4. Ancoragem multiplicativa (preserva a estrutura TEMPORAL do satelite):
       blend24 = w*g24 + (1-w)*s24
       fator   = clamp(blend24 / s24, FMIN, FMAX)
   O ``fator`` derivado da janela de 24 h e aplicado a TODAS as janelas
   (18/24/72/96 h) e a intensidade horaria, mantendo a monotonicidade.
5. Quando o satelite esta ~seco mas o solo mediu chuva, aplica-se correcao
   ADITIVA (nao ha estrutura satelital para escalar).
6. Guarda de falso positivo: se pelo menos 3 estacoes proximas, recentes e
   com cobertura suficiente concordarem que esta seco, enquanto o satelite
   indicar chuva extrema, o IDW de solo substitui a ancora de 24 h sem o
   piso multiplicativo. Isso impede que o residuo de um erro extremo do
   satelite gere alerta operacional.

Politica: fonte COMPLEMENTAR ao MERGE, nunca substituta. Sem estacao no raio,
o valor satelital permanece intacto. Falha da API -> ciclo segue com satelite
puro (degradacao transparente). NUNCA inventa dado.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional, Tuple

import requests

log = logging.getLogger("gauge_correction")

# --- Configuracao (env override) -------------------------------------------
SIBH_URL = os.environ.get(
    "SAMAEG_SIBH_URL",
    "https://apps.spaguas.sp.gov.br/sibh/api/v2/measurements/now",
)
ENABLED = os.environ.get("SAMAEG_GAUGE_CORRECTION", "1").strip() not in (
    "0", "false", "False", "no",
)
HTTP_TIMEOUT = float(os.environ.get("SAMAEG_SIBH_TIMEOUT", "20"))
CACHE_TTL_S = int(os.environ.get("SAMAEG_SIBH_CACHE_TTL", "300"))
# Raio de influencia de uma estacao de solo (km).
GAUGE_RADIUS_KM = float(os.environ.get("SAMAEG_GAUGE_RADIUS_KM", "30"))
# Peso maximo do solo (mesmo colado numa estacao, mantem 15% de satelite).
GAUGE_MAX_WEIGHT = float(os.environ.get("SAMAEG_GAUGE_MAX_WEIGHT", "0.85"))
# Limites do fator multiplicativo (evita correcoes explosivas).
FACTOR_MIN = float(os.environ.get("SAMAEG_GAUGE_FMIN", "0.1"))
FACTOR_MAX = float(os.environ.get("SAMAEG_GAUGE_FMAX", "3.0"))
# Idade maxima da medicao de uma estacao (horas) para ser considerada.
STATION_MAX_AGE_H = float(os.environ.get("SAMAEG_GAUGE_MAX_AGE_H", "3"))
# Abaixo disto (mm) consideramos "seco" para evitar divisao instavel.
DRY_MM = 0.5
# Janela de ancoragem (h). 24 h e a mais robusta na cadencia das estacoes.
ANCHOR_HOURS = 24
# Guarda conservadora contra falso positivo por persistencia do IMERG.
DRY_GUARD_ENABLED = os.environ.get(
    "SAMAEG_GAUGE_DRY_GUARD", "1",
).strip() not in ("0", "false", "False", "no")
DRY_GUARD_MIN_STATIONS = int(os.environ.get(
    "SAMAEG_GAUGE_DRY_MIN_STATIONS", "3",
))
DRY_GUARD_MAX_NEAREST_KM = float(os.environ.get(
    "SAMAEG_GAUGE_DRY_MAX_NEAREST_KM", "15",
))
DRY_GUARD_MAX_GAUGE_MM = float(os.environ.get(
    "SAMAEG_GAUGE_DRY_MAX_MM", "2",
))
DRY_GUARD_MIN_SAT_MM = float(os.environ.get(
    "SAMAEG_GAUGE_DRY_MIN_SAT_MM", "50",
))
DRY_GUARD_MIN_FRACTION = float(os.environ.get(
    "SAMAEG_GAUGE_DRY_MIN_FRACTION", "0.8",
))
DRY_GUARD_MIN_COVERAGE_H = float(os.environ.get(
    "SAMAEG_GAUGE_DRY_MIN_COVERAGE_H", "18",
))


@dataclass
class GaugeStation:
    lat: float
    lon: float
    value_mm: float          # acumulado na janela consultada
    name: str
    owner: str
    city: str
    observed_at: Optional[datetime] = None
    coverage_hours: Optional[float] = None


@dataclass
class GaugeCorrectionMeta:
    """Estatisticas do ciclo (renderizadas apenas em paginas admin)."""
    enabled: bool = True
    applied: bool = False
    source: str = "DAEE/CEMADEN (SIBH)"
    anchor_hours: int = ANCHOR_HOURS
    radius_km: float = GAUGE_RADIUS_KM
    stations_total: int = 0
    stations_recent: int = 0
    points_corrected: int = 0
    points_ground_override: int = 0
    points_total: int = 0
    mean_factor: Optional[float] = None
    max_downscale: Optional[float] = None   # menor fator aplicado (<1)
    max_upscale: Optional[float] = None     # maior fator aplicado (>1)
    error: Optional[str] = None
    fetched_at: Optional[str] = None

    def as_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "applied": self.applied,
            "source": self.source,
            "anchor_hours": self.anchor_hours,
            "radius_km": self.radius_km,
            "stations_total": self.stations_total,
            "stations_recent": self.stations_recent,
            "points_corrected": self.points_corrected,
            "points_ground_override": self.points_ground_override,
            "points_total": self.points_total,
            "mean_factor": self.mean_factor,
            "max_downscale": self.max_downscale,
            "max_upscale": self.max_upscale,
            "error": self.error,
            "fetched_at": self.fetched_at,
        }


# --- Cache de estacoes (por janela de horas) -------------------------------
_CACHE_LOCK = Lock()
_CACHE: Dict[int, Tuple[float, List[GaugeStation]]] = {}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_station(raw: Dict) -> Optional[GaugeStation]:
    lat_raw = raw.get("latitude")
    lon_raw = raw.get("longitude")
    if lat_raw is None or lon_raw is None:
        return None
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except (TypeError, ValueError):
        return None
    if not (-35 < lat < 5 and -75 < lon < -30):
        return None
    val = raw.get("value")
    try:
        value = float(val) if val is not None else None
    except (TypeError, ValueError):
        value = None
    if value is None or value < 0:
        return None
    observed_at = None
    max_date = raw.get("max_date")
    if max_date:
        try:
            observed_at = datetime.fromisoformat(
                str(max_date).replace("Z", "+00:00")
            )
        except ValueError:
            pass
    coverage_hours = None
    count_raw = raw.get("qtd")
    gap_raw = raw.get("measurement_gap")
    try:
        if count_raw is not None and gap_raw is not None:
            count = float(count_raw)
            gap_minutes = float(gap_raw)
            coverage_hours = count * gap_minutes / 60.0
    except (TypeError, ValueError):
        pass
    return GaugeStation(
        lat=lat, lon=lon, value_mm=value,
        name=str(raw.get("station_name") or ""),
        owner=str(raw.get("station_owner") or ""),
        city=str(raw.get("city") or ""),
        observed_at=observed_at,
        coverage_hours=coverage_hours,
    )


def _fetch_stations(hours: int) -> List[GaugeStation]:
    """Busca estacoes do SIBH para a janela `hours` (com cache TTL)."""
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(hours)
        if cached and (now - cached[0]) < CACHE_TTL_S:
            return cached[1]
    params = {
        "station_type_id": 2,
        "hours": hours,
        "show_all": "false",
        "serializer": "complete",
        "public": "true",
    }
    headers = {
        "User-Agent": "PLI-HazardTrack/1.0 (gauge-correction)",
        "Accept": "application/json",
    }
    r = requests.get(
        SIBH_URL, params=params, headers=headers, timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    rows = None
    if isinstance(payload, dict):
        rows = payload.get("measurements") or payload.get("data")
    elif isinstance(payload, list):
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("resposta SIBH sem lista de medicoes")
    cutoff = datetime.now(timezone.utc).timestamp() - STATION_MAX_AGE_H * 3600
    stations = [
        station
        for station in (_parse_station(x) for x in rows)
        if station is not None and (
            station.observed_at is None
            or station.observed_at.timestamp() >= cutoff
        )
    ]
    with _CACHE_LOCK:
        _CACHE[hours] = (now, stations)
    log.info("SIBH: %d estacoes (janela %dh)", len(stations), hours)
    return stations


def _idw(
    stations: List[GaugeStation], lat: float, lon: float,
) -> Tuple[Optional[float], Optional[float]]:
    """IDW p=2 no ponto. Retorna (valor_mm, dist_estacao_mais_proxima_km)."""
    num = 0.0
    den = 0.0
    d_min = None
    for s in stations:
        d = _haversine_km(lat, lon, s.lat, s.lon)
        if d_min is None or d < d_min:
            d_min = d
        if d > GAUGE_RADIUS_KM:
            continue
        if d < 0.5:
            return s.value_mm, d
        w = 1.0 / (d * d)
        num += s.value_mm * w
        den += w
    if den <= 0:
        return None, d_min
    return num / den, d_min


def _dry_ground_consensus(
    stations: List[GaugeStation], lat: float, lon: float, g24: float,
) -> bool:
    """Confirma solo seco com redundancia espacial e temporal."""
    if not DRY_GUARD_ENABLED or g24 > DRY_GUARD_MAX_GAUGE_MM:
        return False
    nearby = []
    for station in stations:
        distance = _haversine_km(lat, lon, station.lat, station.lon)
        coverage = station.coverage_hours
        if (
            distance <= GAUGE_RADIUS_KM
            and coverage is not None
            and coverage >= DRY_GUARD_MIN_COVERAGE_H
        ):
            nearby.append((distance, station))
    if len(nearby) < DRY_GUARD_MIN_STATIONS:
        return False
    if min(distance for distance, _ in nearby) > DRY_GUARD_MAX_NEAREST_KM:
        return False
    dry_count = sum(
        station.value_mm <= DRY_GUARD_MAX_GAUGE_MM
        for _, station in nearby
    )
    return dry_count / len(nearby) >= DRY_GUARD_MIN_FRACTION


def correct_rain_batch(
    coords: List[Tuple[float, float]],
    rain_batch: list,
) -> GaugeCorrectionMeta:
    """
    Ancora in-place os acumulados satelitais de `rain_batch` nas medicoes de
    solo. Cada item de `rain_batch` deve ter os atributos
    ``ac18h_mm``, ``ac24h_mm``, ``ac72h_mm``, ``ac96h_mm`` e
    ``intensity_mmh`` (RainSample). Retorna metadados do ciclo (uso admin).

    Nao levanta excecao: falha -> retorna meta com `applied=False` e o
    satelite permanece intacto.
    """
    meta = GaugeCorrectionMeta(
        enabled=ENABLED, points_total=len(coords),
    )
    if not ENABLED:
        return meta
    try:
        stations = _fetch_stations(ANCHOR_HOURS)
    except Exception as e:  # noqa: BLE001
        log.warning("correcao por solo indisponivel (%s); satelite puro", e)
        meta.error = str(e)
        return meta

    meta.fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta.stations_total = len(stations)
    meta.stations_recent = len(stations)
    if not stations:
        meta.error = "sem estacoes de solo com dado recente"
        return meta

    factors: List[float] = []
    down: List[float] = []
    up: List[float] = []
    corrected = 0
    ground_overrides = 0

    for i, (lat, lon) in enumerate(coords):
        if i >= len(rain_batch) or rain_batch[i] is None:
            continue
        g24, d_min = _idw(stations, lat, lon)
        if g24 is None or d_min is None or d_min > GAUGE_RADIUS_KM:
            continue  # nenhuma estacao no raio: mantem satelite
        rain = rain_batch[i]
        s24 = float(getattr(rain, "ac24h_mm", 0.0) or 0.0)

        w = GAUGE_MAX_WEIGHT * max(0.0, 1.0 - d_min / GAUGE_RADIUS_KM)
        if w <= 0:
            continue
        blend24 = w * g24 + (1.0 - w) * s24

        if s24 <= DRY_MM and g24 <= DRY_MM:
            continue  # ambos secos: nada a corrigir
        ground_override = (
            s24 >= DRY_GUARD_MIN_SAT_MM
            and _dry_ground_consensus(stations, lat, lon, g24)
        )
        if ground_override:
            # Consenso de solo substitui apenas uma divergencia extrema.
            # Sem piso: o residuo do satelite nao pode fabricar um alerta.
            factor = max(0.0, min(1.0, g24 / s24))
            _anchor_recent_24h_to_ground(rain, g24, factor)
            ground_overrides += 1
        elif s24 > DRY_MM:
            factor = blend24 / s24
            factor = max(FACTOR_MIN, min(FACTOR_MAX, factor))
            _scale_rain(rain, factor)
        else:
            # satelite ~seco, solo mediu chuva: correcao aditiva
            _add_rain(rain, blend24)
            factor = None

        corrected += 1
        if factor is not None:
            factors.append(factor)
            if factor < 1.0:
                down.append(factor)
            elif factor > 1.0:
                up.append(factor)

    meta.applied = corrected > 0
    meta.points_corrected = corrected
    meta.points_ground_override = ground_overrides
    if factors:
        meta.mean_factor = round(sum(factors) / len(factors), 3)
    if down:
        meta.max_downscale = round(min(down), 3)
    if up:
        meta.max_upscale = round(max(up), 3)
    log.info(
        "correcao por solo: %d/%d pontos ancorados, %d override(s) de "
        "satélite extremo (fator medio %s)",
        corrected, len(coords), ground_overrides, meta.mean_factor,
    )
    return meta


def _scale_rain(rain, factor: float) -> None:
    """Aplica fator multiplicativo a todas as janelas + intensidade."""
    for attr in ("ac18h_mm", "ac24h_mm", "ac72h_mm", "ac96h_mm",
                 "intensity_mmh"):
        v = getattr(rain, attr, None)
        if v is not None:
            setattr(rain, attr, round(float(v) * factor, 2))
    _enforce_monotonic(rain)


def _anchor_recent_24h_to_ground(
    rain, ground24: float, factor: float,
) -> None:
    """Substitui 24 h pelo solo sem apagar chuva anterior a essa janela."""
    satellite24 = float(getattr(rain, "ac24h_mm", 0.0) or 0.0)
    satellite72 = float(getattr(rain, "ac72h_mm", 0.0) or 0.0)
    satellite96 = float(getattr(rain, "ac96h_mm", 0.0) or 0.0)
    satellite18 = float(getattr(rain, "ac18h_mm", 0.0) or 0.0)
    intensity = float(getattr(rain, "intensity_mmh", 0.0) or 0.0)

    setattr(rain, "ac18h_mm", round(satellite18 * factor, 2))
    setattr(rain, "ac24h_mm", round(ground24, 2))
    setattr(
        rain, "ac72h_mm",
        round(max(0.0, satellite72 - satellite24) + ground24, 2),
    )
    setattr(
        rain, "ac96h_mm",
        round(max(0.0, satellite96 - satellite24) + ground24, 2),
    )
    setattr(rain, "intensity_mmh", round(intensity * factor, 2))
    _enforce_monotonic(rain)


def _add_rain(rain, delta24: float) -> None:
    """Correcao aditiva (satelite seco). Distribui pela proporcao natural."""
    ac24 = float(getattr(rain, "ac24h_mm", 0.0) or 0.0) + delta24
    setattr(rain, "ac24h_mm", round(ac24, 2))
    # 18h ~ chuva das ultimas horas: usa fracao 0.8 do acrescimo de 24h
    ac18 = float(getattr(rain, "ac18h_mm", 0.0) or 0.0) + delta24 * 0.8
    setattr(rain, "ac18h_mm", round(ac18, 2))
    # janelas longas recebem ao menos o acrescimo de 24h
    for attr in ("ac72h_mm", "ac96h_mm"):
        v = float(getattr(rain, attr, 0.0) or 0.0) + delta24
        setattr(rain, attr, round(v, 2))
    _enforce_monotonic(rain)


def _enforce_monotonic(rain) -> None:
    """Garante ac18h <= ac24h <= ac72h <= ac96h."""
    a18 = float(getattr(rain, "ac18h_mm", 0.0) or 0.0)
    a24 = float(getattr(rain, "ac24h_mm", 0.0) or 0.0)
    a72 = float(getattr(rain, "ac72h_mm", 0.0) or 0.0)
    a96 = float(getattr(rain, "ac96h_mm", 0.0) or 0.0)
    a24 = max(a24, a18)
    a72 = max(a72, a24)
    a96 = max(a96, a72)
    setattr(rain, "ac24h_mm", round(a24, 2))
    setattr(rain, "ac72h_mm", round(a72, 2))
    setattr(rain, "ac96h_mm", round(a96, 2))
