"""
Ingestao MERGE/CPTEC/INPE em STREAMING - sem cache em disco.

Estrategia:
- HTTP GET do GRIB2 horario direto do servidor INPE
- Parser eccodes em memoria (BytesIO) - nada toca o filesystem
- Amostragem batch via codes_grib_find_nearest_multiple (1 chamada para N pontos)
- ThreadPool: 96 horas em paralelo (8 workers)
- Agregacao em memoria (apenas floats das series temporais)

Sem write em disco. Cada refresh busca dados frescos.

Estrutura no servidor INPE:
    https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/HOURLY/AAAA/MM/DD/MERGE_CPTEC_AAAAMMDDHH.grib2

Resolucao: 0.1 graus (~10 km). Cobertura: America do Sul. Sem auth.
Quando eccodes nao estiver disponivel, opera em MOCK (chuva sintetica).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import List, Optional, Tuple
import logging
import requests

log = logging.getLogger("merge_inpe")

INPE_BASE = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM"
PUBLISH_LAG_HOURS = 3
HTTP_TIMEOUT = (10, 60)         # (connect, read)
DEFAULT_WORKERS = 8


def _hourly_url(dt: datetime) -> str:
    return (
        f"{INPE_BASE}/HOURLY/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/"
        f"MERGE_CPTEC_{dt.year:04d}{dt.month:02d}{dt.day:02d}{dt.hour:02d}.grib2"
    )


@dataclass
class RainSample:
    lat: float
    lon: float
    intensity_mmh: float
    ac24h_mm: float
    ac96h_mm: float
    timestamp_utc: str
    source: str = "MERGE/INPE"


# ---------------------------------------------------------------------------
# Backend eccodes - decode em memoria
# ---------------------------------------------------------------------------

def _eccodes_available() -> bool:
    try:
        import eccodes  # noqa: F401
        return True
    except Exception:
        return False


_HTTP_SESSION: Optional[requests.Session] = None


def _http() -> requests.Session:
    """Sessao HTTP com keep-alive para reaproveitar conexoes."""
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "PLI-HazardTrack/0.1 (eccodes streaming)"})
        _HTTP_SESSION = s
    return _HTTP_SESSION


def _fetch_grib_bytes(dt: datetime) -> Optional[bytes]:
    """Baixa o GRIB horario para memoria. Retorna None em falha."""
    url = _hourly_url(dt)
    try:
        r = _http().get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200 or len(r.content) < 1000:
            log.debug("MERGE %s: HTTP %s (%d bytes)", dt, r.status_code, len(r.content))
            return None
        return r.content
    except Exception as e:
        log.debug("MERGE %s falhou: %s", dt, e)
        return None


def _sample_grib_in_memory(grib_bytes: bytes,
                           lats: List[float],
                           lons_360: List[float]) -> List[float]:
    """Decodifica um GRIB em memoria e amostra todos os pontos de uma vez."""
    import eccodes

    n = len(lats)
    samples = [0.0] * n
    buf = BytesIO(grib_bytes)
    gid = eccodes.codes_grib_new_from_file(buf)
    if gid is None:
        return samples
    try:
        # Batch: 1 chamada nativa para N pontos
        try:
            nearest = eccodes.codes_grib_find_nearest_multiple(gid, False, lats, lons_360)
            for i, near in enumerate(nearest):
                v = float(near.value)
                samples[i] = 0.0 if (v > 1e30 or v < 0) else v
            return samples
        except Exception as e:
            log.debug("nearest_multiple falhou (%s); fallback ponto-a-ponto", e)

        # Fallback ponto-a-ponto
        for i in range(n):
            try:
                near = eccodes.codes_grib_find_nearest(gid, lats[i], lons_360[i])
                v = float(near[0].value)
                samples[i] = 0.0 if (v > 1e30 or v < 0) else v
            except Exception:
                pass
        return samples
    finally:
        eccodes.codes_release(gid)


def _process_hour(dt: datetime,
                  lats: List[float],
                  lons_360: List[float]) -> Tuple[datetime, Optional[List[float]]]:
    data = _fetch_grib_bytes(dt)
    if data is None:
        return dt, None
    try:
        return dt, _sample_grib_in_memory(data, lats, lons_360)
    except Exception as e:
        log.debug("erro decode %s: %s", dt, e)
        return dt, None
    finally:
        # Solta a referencia explicitamente para o GC liberar a memoria
        data = None  # noqa: F841


def fetch_real_batch(points: list,
                     now_utc: Optional[datetime] = None,
                     hours_back: int = 96,
                     workers: int = DEFAULT_WORKERS) -> Optional[list]:
    """
    Stream paralelo de 96 GRIB2 horarios direto do INPE.
    Retorna lista de RainSample na mesma ordem de `points` (ou None se eccodes indisponivel).
    """
    if not _eccodes_available():
        log.warning("eccodes nao disponivel; chamador deve usar MOCK")
        return None

    now = now_utc or datetime.now(timezone.utc)
    target_hour = (now - timedelta(hours=PUBLISH_LAG_HOURS)).replace(minute=0, second=0, microsecond=0)

    n = len(points)
    lats = [float(p[0]) for p in points]
    lons_360 = [float(p[1]) if p[1] >= 0 else float(p[1]) + 360 for p in points]

    series = [[0.0] * hours_back for _ in range(n)]
    files_ok = 0

    hours = [(h, target_hour - timedelta(hours=h)) for h in range(hours_back)]

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(_process_hour, dt, lats, lons_360): h for h, dt in hours}
        for fut in as_completed(futures):
            h = futures[fut]
            try:
                _, samples = fut.result()
            except Exception as e:
                log.debug("worker falhou em h=%d: %s", h, e)
                continue
            if samples is None:
                continue
            for i in range(n):
                v = samples[i]
                if v > 0:
                    series[i][h] = v
            files_ok += 1

    if files_ok == 0:
        log.warning("nenhum GRIB MERGE foi lido com sucesso")
        return None

    log.info("MERGE streaming: %d/%d arquivos lidos para %d pontos", files_ok, hours_back, n)

    out = []
    ts = target_hour.isoformat()
    for i, (lat, lon) in enumerate(points):
        s = series[i]
        out.append(RainSample(
            lat=lat, lon=lon,
            intensity_mmh=round(s[0], 2),
            ac24h_mm=round(sum(s[:24]), 2),
            ac96h_mm=round(sum(s[:96]), 2),
            timestamp_utc=ts,
            source="MERGE/INPE (streaming)"
        ))
    return out


def fetch_real(lat: float, lon: float,
               now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    res = fetch_real_batch([(lat, lon)], now_utc)
    return res[0] if res else None


# ---------------------------------------------------------------------------
# MOCK: chuva sintetica para desenvolvimento sem eccodes
# ---------------------------------------------------------------------------

def fetch_mock(lat: float, lon: float,
               now_utc: Optional[datetime] = None) -> RainSample:
    now = now_utc or datetime.now(timezone.utc)
    seed = (abs(hash((round(lat, 1), round(lon, 1), now.day))) % 1000) / 1000.0
    base_24h = 8 + 90 * seed
    base_96h = base_24h * (2.0 + seed * 1.2)
    intensity = base_24h * (0.05 + 0.2 * seed)
    return RainSample(
        lat=lat, lon=lon,
        intensity_mmh=round(intensity, 1),
        ac24h_mm=round(base_24h, 1),
        ac96h_mm=round(base_96h, 1),
        timestamp_utc=now.replace(minute=0, second=0, microsecond=0).isoformat(),
        source="MOCK (eccodes indisponivel)"
    )


def fetch(lat: float, lon: float,
          now_utc: Optional[datetime] = None) -> RainSample:
    """API legada: tenta MERGE real, fallback para mock."""
    real = fetch_real(lat, lon, now_utc)
    if real is not None:
        return real
    return fetch_mock(lat, lon, now_utc)
