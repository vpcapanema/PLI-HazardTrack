"""
Ingestao de dados MERGE/CPTEC/INPE em tempo real.

MERGE = produto operacional do INPE que combina IMERG/GPM com pluviometros
in situ da rede brasileira (Rozante et al., 2010).

Estrutura no servidor INPE:
    https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/HOURLY/AAAA/MM/DD/MERGE_CPTEC_AAAAMMDDHH.grib2
    https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/AAAA/MM/MERGE_CPTEC_AAAAMMDD.grib2

Resolução: 0.1° (~10 km) | Cobertura: América do Sul | Sem auth.

Esta camada:
- baixa o arquivo GRIB2 mais recente
- abre com cfgrib/xarray
- expoe metodos de amostragem por (lat, lon) e por agregacoes 24h/96h
- mantem cache local para evitar re-download

Quando cfgrib nao estiver instalado, opera em MODO MOCK (chuva sintetica).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple
import os
import logging
import requests
import math

log = logging.getLogger("merge_inpe")

INPE_BASE = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM"
CACHE_DIR = Path(os.environ.get("MERGE_CACHE_DIR", Path(__file__).parent.parent / "cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Hora UTC de cada arquivo: o INPE publica os arquivos horarios com algumas horas de defasagem
PUBLISH_LAG_HOURS = 3


def _hourly_url(dt: datetime) -> str:
    return (
        f"{INPE_BASE}/HOURLY/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/"
        f"MERGE_CPTEC_{dt.year:04d}{dt.month:02d}{dt.day:02d}{dt.hour:02d}.grib2"
    )


def _hourly_path(dt: datetime) -> Path:
    return CACHE_DIR / f"MERGE_CPTEC_{dt.year:04d}{dt.month:02d}{dt.day:02d}{dt.hour:02d}.grib2"


def download_hourly(dt: datetime, force: bool = False) -> Optional[Path]:
    """Baixa o arquivo MERGE horario para (year, month, day, hour) UTC. Cacheado."""
    path = _hourly_path(dt)
    if path.exists() and path.stat().st_size > 1000 and not force:
        return path
    url = _hourly_url(dt)
    try:
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            log.warning(f"MERGE indisponivel para {dt}: HTTP {r.status_code}")
            return None
        with path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        if path.stat().st_size < 1000:
            path.unlink()
            return None
        return path
    except Exception as e:
        log.error(f"Falha download MERGE {dt}: {e}")
        return None


@dataclass
class RainSample:
    lat: float
    lon: float
    intensity_mmh: float    # ultima hora (mm)
    ac24h_mm: float         # ultimas 24 h
    ac96h_mm: float         # ultimas 96 h
    timestamp_utc: str
    source: str = "MERGE/INPE"


# ============================================================================
# IMPLEMENTACAO REAL (cfgrib) - otimizada para multiplos pontos
# ============================================================================

def _open_grib(path: Path):
    import xarray as xr
    return xr.open_dataset(str(path), engine="cfgrib",
                           backend_kwargs={"indexpath": ""})


def _sample_at(ds, lat: float, lon: float) -> float:
    """
    Amostra precipitacao em (lat, lon).
    No produto MERGE/CPTEC a variavel se chama 'rdp' (Precipitation from radar)
    em unidades kg m**-2 (= mm para agua liquida).
    """
    # MERGE usa lon em [0, 360]; pontos no Brasil ficam ~313..325
    lon_360 = lon if lon >= 0 else lon + 360

    # Prioridade: rdp (oficial), depois prec, depois primeira variavel
    candidates = ["rdp", "prec", "tp", "precipitation"]
    var = None
    for c in candidates:
        if c in ds.data_vars:
            var = c
            break
    if var is None:
        var = list(ds.data_vars)[0]

    val = ds[var].sel(latitude=lat, longitude=lon_360, method="nearest").values
    try:
        v = float(val.item() if hasattr(val, "item") else val)
        # missing value sentinel do GRIB
        if v > 1e30 or v < 0:
            return 0.0
        return v
    except Exception:
        return 0.0


def fetch_real(lat: float, lon: float, now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    """
    Busca chuva real do MERGE para UM ponto.
    Para multiplos pontos use fetch_real_batch (muito mais eficiente).
    """
    samples = fetch_real_batch([(lat, lon)], now_utc)
    return samples[0] if samples else None


def _is_cfgrib_available() -> bool:
    try:
        import xarray as xr  # noqa
        import cfgrib  # noqa
        return True
    except ImportError:
        return False


def fetch_real_batch(points: list, now_utc: Optional[datetime] = None,
                     hours_back: int = 96) -> Optional[list]:
    """
    Versao otimizada: baixa cada GRIB UMA vez e amostra TODOS os pontos.
    points: lista de tuplas (lat, lon)
    Retorna lista de RainSample na mesma ordem (ou None se cfgrib indisponivel).
    """
    if not _is_cfgrib_available():
        log.warning("xarray/cfgrib nao disponivel")
        return None

    now = now_utc or datetime.now(timezone.utc)
    target_hour = (now - timedelta(hours=PUBLISH_LAG_HOURS)).replace(minute=0, second=0, microsecond=0)

    # series[i] = lista de N intensidades horarias (mais recente primeiro)
    n = len(points)
    series = [[0.0] * hours_back for _ in range(n)]
    files_ok = 0

    for h in range(hours_back):
        dt = target_hour - timedelta(hours=h)
        path = download_hourly(dt)
        if path is None:
            continue
        try:
            ds = _open_grib(path)
            for i, (lat, lon) in enumerate(points):
                series[i][h] = max(0.0, _sample_at(ds, lat, lon))
            ds.close()
            files_ok += 1
        except Exception as e:
            log.debug(f"erro ler {path.name}: {e}")

    if files_ok == 0:
        log.warning("nenhum arquivo MERGE leu com sucesso")
        return None

    log.info(f"MERGE: {files_ok}/{hours_back} arquivos lidos para {n} pontos")
    out = []
    for i, (lat, lon) in enumerate(points):
        s = series[i]
        out.append(RainSample(
            lat=lat, lon=lon,
            intensity_mmh=round(s[0], 2),
            ac24h_mm=round(sum(s[:24]), 2),
            ac96h_mm=round(sum(s[:96]), 2),
            timestamp_utc=target_hour.isoformat(),
            source="MERGE/INPE"
        ))
    return out


# ============================================================================
# MOCK: chuva sintetica para desenvolvimento sem cfgrib
# ============================================================================

def fetch_mock(lat: float, lon: float, now_utc: Optional[datetime] = None) -> RainSample:
    """
    Gera chuva sintetica determinista a partir de (lat, lon, hora).
    Util para desenvolvimento e demos sem dependencia GRIB.
    """
    now = now_utc or datetime.now(timezone.utc)
    # padrao deterministico (sem aleatoriedade pura) baseado na hora UTC
    seed = (abs(hash((round(lat, 1), round(lon, 1), now.day))) % 1000) / 1000.0

    # litoral norte SP tem chuva tipica de verao 30-150 mm em 24h em chuvas fortes
    base_24h = 8 + 90 * seed                 # 8 a 98 mm em 24h
    base_96h = base_24h * (2.0 + seed * 1.2) # 2x a 3.2x da 24h
    intensity = base_24h * (0.05 + 0.2 * seed)  # frac da 24h na hora de pico

    return RainSample(
        lat=lat, lon=lon,
        intensity_mmh=round(intensity, 1),
        ac24h_mm=round(base_24h, 1),
        ac96h_mm=round(base_96h, 1),
        timestamp_utc=now.replace(minute=0, second=0, microsecond=0).isoformat(),
        source="MOCK (cfgrib indisponivel)"
    )


def fetch(lat: float, lon: float, now_utc: Optional[datetime] = None) -> RainSample:
    """Tenta MERGE real, faz fallback para mock."""
    real = fetch_real(lat, lon, now_utc)
    if real is not None:
        return real
    return fetch_mock(lat, lon, now_utc)
