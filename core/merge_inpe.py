"""
Ingestao MERGE/CPTEC/INPE em STREAMING - sem cache em disco.

Estrategia:
- HTTP GET do GRIB2 horario direto do servidor INPE (paralelo, 8 workers)
- Decodificacao via eccodes 2.x com codes_new_from_message (aceita bytes)
- Decode SERIALIZADO com lock global (eccodes MEMFS nao e thread-safe)
- Amostragem batch via codes_grib_find_nearest_multiple (1 chamada para N pontos)
- Agregacao em memoria

Sem write em disco. Cada refresh busca dados frescos.

Estrutura no servidor INPE:
    https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/HOURLY/AAAA/MM/DD/MERGE_CPTEC_AAAAMMDDHH.grib2

Resolucao: 0.1 graus (~10 km). Cobertura: America do Sul. Sem auth.

nenhum GRIB chegar, fetch_real_batch retorna None e o aggregator marca o
snapshot como degraded; a UI mostra "Dado indisponivel" em vez de fingir
chuva sintetica.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import List, Optional, Tuple
import logging
import requests

log = logging.getLogger("merge_inpe")

INPE_BASE = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM"
PUBLISH_LAG_HOURS = 3
HTTP_TIMEOUT = (10, 60)         # (connect, read)
# Em producao (Render free: 0.5 CPU / 512MB RAM) reduzimos os workers para
# nao estourar memoria nem saturar CPU. Pode ser sobreposto via env.
import os as _os
DEFAULT_WORKERS = int(_os.environ.get("SAMAEG_WORKERS", "4"))

# eccodes MEMFS nao e thread-safe: serializa o decode entre threads.
_ECCODES_LOCK = Lock()


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
    # Metadados de qualidade do batch (opcionais, populados apenas no caminho real)
    files_ok: int = 0
    missing_24h: int = 0
    missing_96h: int = 0


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
    """
    Decodifica um GRIB em memoria e amostra todos os pontos de uma vez.
    Usa codes_new_from_message (eccodes 2.x) que aceita bytes diretamente.

    eccodes MEMFS nao e thread-safe; o chamador deve manter _ECCODES_LOCK.
    """
    import eccodes

    n = len(lats)
    samples = [0.0] * n
    gid = eccodes.codes_new_from_message(grib_bytes)
    if gid is None:
        return samples
    try:
        try:
            nearest = eccodes.codes_grib_find_nearest_multiple(gid, False, lats, lons_360)
            for i, near in enumerate(nearest):
                v = float(near.value)
                samples[i] = 0.0 if (v > 1e30 or v < 0) else v
            return samples
        except Exception as e:
            log.debug("nearest_multiple falhou (%s); fallback ponto-a-ponto", e)

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
    """Download paralelo (rede) + decode serializado (eccodes nao e thread-safe)."""
    data = _fetch_grib_bytes(dt)
    if data is None:
        return dt, None
    try:
        with _ECCODES_LOCK:
            return dt, _sample_grib_in_memory(data, lats, lons_360)
    except Exception as e:
        log.debug("erro decode %s: %s", dt, e)
        return dt, None
    finally:
        data = None  # noqa: F841 - solta a referencia para o GC


def fetch_real_batch(points: list,
                     now_utc: Optional[datetime] = None,
                     hours_back: int = 96,
                     workers: int = DEFAULT_WORKERS) -> Optional[list]:
    """
    Stream paralelo de 96 GRIB2 horarios direto do INPE.
    Retorna lista de RainSample na mesma ordem de `points` (ou None se eccodes indisponivel).

    Cada RainSample carrega tres metricas extras de qualidade do batch (iguais para
    todos os pontos, replicadas por conveniencia da API):
      - files_ok          numero total de horas lidas com sucesso (0..96)
      - missing_24h       horas faltando na janela 0..23h
      - missing_96h       horas faltando na janela 0..95h
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
    hour_ok = [False] * hours_back
    files_ok = 0

    hours = [(h, target_hour - timedelta(hours=h)) for h in range(hours_back)]

    log.info(
        "MERGE batch: target=%s, %d horas, %d pontos, %d workers",
        target_hour.isoformat(), hours_back, n, max(1, workers)
    )

    progress_every = max(1, hours_back // 6)  # ~6 marcos no log

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(_process_hour, dt, lats, lons_360): h for h, dt in hours}
        done = 0
        for fut in as_completed(futures):
            h = futures[fut]
            try:
                _, samples = fut.result()
            except Exception as e:
                log.debug("worker falhou em h=%d: %s", h, e)
                samples = None
            done += 1
            if samples is None:
                if done % progress_every == 0:
                    log.info("MERGE progress %d/%d (ok=%d)", done, hours_back, files_ok)
                continue
            for i in range(n):
                v = samples[i]
                if v > 0:
                    series[i][h] = v
            hour_ok[h] = True
            files_ok += 1
            if done % progress_every == 0:
                log.info("MERGE progress %d/%d (ok=%d)", done, hours_back, files_ok)

    if files_ok == 0:
        log.warning("nenhum GRIB MERGE foi lido com sucesso")
        return None

    missing_24h = sum(1 for ok in hour_ok[:24] if not ok)
    missing_96h = sum(1 for ok in hour_ok[:96] if not ok)
    log.info(
        "MERGE streaming: %d/%d arquivos lidos para %d pontos (faltando 24h=%d, 96h=%d)",
        files_ok, hours_back, n, missing_24h, missing_96h
    )

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
            source="MERGE/INPE (streaming)",
            files_ok=files_ok,
            missing_24h=missing_24h,
            missing_96h=missing_96h,
        ))
    return out


def fetch_real(lat: float, lon: float,
               now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    res = fetch_real_batch([(lat, lon)], now_utc)
    return res[0] if res else None



def fetch(lat: float, lon: float,
          now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    """API legada: retorna apenas dado real do MERGE; None se indisponivel."""
    return fetch_real(lat, lon, now_utc)
