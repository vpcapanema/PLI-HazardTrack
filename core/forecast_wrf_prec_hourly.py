"""
Previsao de chuva WRF/CPTEC HORARIA (recorte `prec/`), para a composicao do
Risco Dinamico exatamente como o Produto 6 (secao 4.5.3) determina:

  - Geologico: Ac96h = 72h observadas (MERGE) + 24h previstas (WRF)
  - Hidrologico: Soma(24h) = 18h observadas (MERGE) + 6h previstas (WRF)

Fonte (HTTP sobre FTP do CPTEC):
  https://ftp.cptec.inpe.br/modelos/tempo/WRF/ams_07km/recortes/prec/
  AAAA/MM/DD/HH/WRF_cpt_07KM_{rodada}_{validade}.grib2

Semantica do GRIB (verificada via eccodes): stepType=accum, stepRange="0-N",
ou seja, PRECIPITACAO ACUMULADA DESDE O INICIO DA RODADA. Logo a chuva
prevista para uma janela futura [t0, t0+H] e:

    prev(H) = acum(t0 + H) - acum(t0)

onde acum(.) e o valor do arquivo cuja validade e aquela hora. Isso isola
exatamente a chuva FUTURA, sem dupla contagem com o periodo observado.

Contiguidade: t0 = fim da janela observada do MERGE = (agora - PUBLISH_LAG),
de modo que 72h observadas + 24h previstas formem 96h contiguas (idem 18h+6h).

Politica de dados: se a rodada/arquivos nao estiverem disponiveis, retorna
None (o aggregator degrada de forma transparente para observado-apenas e
sinaliza). NUNCA inventa previsao.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Dict, List, Optional, Tuple
import logging
import os

import requests

from .merge_inpe import PUBLISH_LAG_HOURS

log = logging.getLogger("forecast_wrf_hourly")

PREC_BASE = os.environ.get(
    "SAMAEG_WRF_PREC_BASE",
    "https://ftp.cptec.inpe.br/modelos/tempo/WRF/ams_07km/recortes/prec",
).rstrip("/")

HTTP_TIMEOUT = (10, 60)
_RUN_HOURS = [0, 6, 12, 18]
# Quantas rodadas (6 em 6 h) olhar para tras procurando dados publicados.
_LOOKBACK_RUNS = int(os.environ.get("SAMAEG_WRF_HOURLY_LOOKBACK", "12"))
_MAX_LEAD_H = int(os.environ.get("SAMAEG_WRF_HOURLY_MAXLEAD", "180"))
_CACHE_TTL_SECONDS = int(os.environ.get("SAMAEG_WRF_HOURLY_TTL", "600"))
_DISABLED = os.environ.get("SAMAEG_FORECAST_DISABLED", "0") == "1"

# eccodes MEMFS nao e thread-safe.
_ECCODES_LOCK = Lock()
_HTTP: Optional[requests.Session] = None
_CACHE: Dict[str, object] = {}


@dataclass
class ForecastAccum:
    lat: float
    lon: float
    ac6h_mm: float
    ac24h_mm: float
    run_utc: datetime
    source: str


def _http() -> requests.Session:
    global _HTTP
    if _HTTP is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "PLI-HazardTrack/0.1 (wrf hourly)"})
        _HTTP = s
    return _HTTP


def _eccodes_available() -> bool:
    try:
        import eccodes
        return eccodes is not None
    except Exception:
        return False


def _file_url(run: datetime, valid: datetime) -> str:
    return (
        f"{PREC_BASE}/{run.year:04d}/{run.month:02d}/{run.day:02d}/"
        f"{run.hour:02d}/WRF_cpt_07KM_"
        f"{run.year:04d}{run.month:02d}{run.day:02d}{run.hour:02d}_"
        f"{valid.year:04d}{valid.month:02d}{valid.day:02d}{valid.hour:02d}"
        f".grib2"
    )


def _fetch_bytes(url: str) -> Optional[bytes]:
    try:
        r = _http().get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200 or len(r.content) < 200:
            return None
        return r.content
    except requests.RequestException as e:
        log.debug("falha fetch %s: %s", url, e)
        return None


def _sample(grib_bytes: bytes, lats: List[float],
            lons360: List[float]) -> Optional[List[float]]:
    """Amostra todos os pontos de um GRIB em memoria (nearest)."""
    import eccodes
    n = len(lats)
    with _ECCODES_LOCK:
        gid = eccodes.codes_new_from_message(grib_bytes)
        if gid is None:
            return None
        try:
            vals = [0.0] * n
            try:
                near = eccodes.codes_grib_find_nearest_multiple(
                    gid, False, lats, lons360)
                for i, nr in enumerate(near):
                    v = float(nr.value)
                    vals[i] = 0.0 if (v > 1e30 or v < 0) else v
            except Exception:
                for i in range(n):
                    nr = eccodes.codes_grib_find_nearest(
                        gid, lats[i], lons360[i])[0]
                    v = float(nr.value)
                    vals[i] = 0.0 if (v > 1e30 or v < 0) else v
            return vals
        finally:
            eccodes.codes_release(gid)


def _choose_run(t0: datetime) -> Optional[Tuple[datetime, bytes, bytes, bytes]]:
    """Escolhe a rodada mais recente publicada cujos arquivos de validade
    t0, t0+6h e t0+24h existam. Retorna (run, bin_t0, bin_t6, bin_t24)."""
    # rodada mais recente <= t0
    base = t0.replace(minute=0, second=0, microsecond=0)
    while base.hour not in _RUN_HOURS:
        base -= timedelta(hours=1)

    for k in range(_LOOKBACK_RUNS + 1):
        run = base - timedelta(hours=6 * k)
        lead0 = int((t0 - run).total_seconds() // 3600)
        if lead0 < 0 or lead0 + 24 > _MAX_LEAD_H:
            continue
        b0 = _fetch_bytes(_file_url(run, t0))
        b6 = _fetch_bytes(_file_url(run, t0 + timedelta(hours=6)))
        b24 = _fetch_bytes(_file_url(run, t0 + timedelta(hours=24)))
        if b0 and b6 and b24:
            log.info("WRF horario: rodada %s (lead t0=%dh)",
                     run.isoformat(), lead0)
            return run, b0, b6, b24
    return None


def fetch_forecast_accum_batch(
    coords: List[Tuple[float, float]],
    now_utc: Optional[datetime] = None,
) -> Optional[List[Optional[ForecastAccum]]]:
    """Previsao acumulada 6h e 24h (mm) por ponto, a partir do fim da janela
    observada (t0 = agora - PUBLISH_LAG). None se previsao indisponivel."""
    if _DISABLED or not coords or not _eccodes_available():
        return None

    now = now_utc or datetime.now(timezone.utc)
    t0 = (now - timedelta(hours=PUBLISH_LAG_HOURS)).replace(
        minute=0, second=0, microsecond=0)

    cache_key = f"{t0.isoformat()}|{len(coords)}"
    cached = _CACHE.get("key")
    if (cached == cache_key
            and isinstance(_CACHE.get("valid_until"), datetime)
            and now < _CACHE["valid_until"]):  # type: ignore[operator]
        return _CACHE["result"]  # type: ignore[return-value]

    chosen = _choose_run(t0)
    if not chosen:
        return None
    run, b0, b6, b24 = chosen

    lats = [float(c[0]) for c in coords]
    lons360 = [float(c[1]) if c[1] >= 0 else float(c[1]) + 360
               for c in coords]

    c0 = _sample(b0, lats, lons360)
    c6 = _sample(b6, lats, lons360)
    c24 = _sample(b24, lats, lons360)
    if c0 is None or c6 is None or c24 is None:
        return None

    src = f"INPE/CPTEC WRF prec (rodada {run.isoformat()})"
    out: List[Optional[ForecastAccum]] = []
    for i, (lat, lon) in enumerate(coords):
        ac6 = max(0.0, c6[i] - c0[i])
        ac24 = max(0.0, c24[i] - c0[i])
        out.append(ForecastAccum(
            lat=lat, lon=lon,
            ac6h_mm=round(ac6, 2),
            ac24h_mm=round(ac24, 2),
            run_utc=run, source=src,
        ))

    _CACHE.clear()
    _CACHE.update({
        "key": cache_key, "result": out,
        "valid_until": now + timedelta(seconds=_CACHE_TTL_SECONDS),
    })
    return out
