"""
Cache persistente em disco para o pipeline MERGE/INPE.

Duas camadas independentes:

1. Cache de GRIB brutos (`data/_cache/merge/grib/AAAA-MM-DD/HH.grib2`):
   compartilhado entre runs e entre diferentes malhas de UAs (basta
   redecodificar). Sobrevive a reinicios.

2. Cache de samples decodificados por malha de coordenadas
   (`data/_cache/merge/samples/<coords_hash>/AAAA-MM-DD/HH.json`):
   contem apenas os valores ja amostrados nos centroides das UAs. Hit
   significa zero download e zero decode -- caminho mais rapido.

Politica de refetch por idade:
- idade < REFETCH_FRESH_HOURS (4h)  -> sempre refaz (INPE pode republicar)
- 4h <= idade < REFETCH_STALE_HOURS (24h) -> refaz 1x por dia (defensivo)
- idade >= 24h -> nunca refaz (dado final)

Sem dependencia de numpy / msgpack: JSON puro. Volume desprezivel
(~6 KB por arquivo de samples para 809 UAs).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("merge_cache")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_cache_root() -> Path:
    """Raiz do cache MERGE (GRIB + samples). Configuravel na VM/docker."""
    raw = os.environ.get("SAMAEG_MERGE_CACHE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_PROJECT_ROOT / "data" / "_cache" / "merge").resolve()


CACHE_ROOT = _resolve_cache_root()
GRIB_DIR = CACHE_ROOT / "grib"
SAMPLES_DIR = CACHE_ROOT / "samples"

# Janelas de re-fetch (configuravel via env). 4h: dado ainda pode ser
# republicado pelo CPTEC. 24h: corte conservador de seguranca.
REFETCH_FRESH_HOURS = int(os.environ.get("SAMAEG_REFETCH_FRESH_H", "4"))
REFETCH_STALE_HOURS = int(os.environ.get("SAMAEG_REFETCH_STALE_H", "24"))
# Limpeza opcional: descarta arquivos com mais de N dias. 0 = nunca limpa.
CACHE_TTL_DAYS = int(os.environ.get("SAMAEG_CACHE_TTL_D", "30"))


def coords_hash(lats: List[float], lons_360: List[float]) -> str:
    """Hash estavel da malha de coordenadas (binding samples<->UAs).

    Inclui n_pontos para detectar mudanca na geracao das UAs.
    Truncado em 12 chars (suficiente para evitar colisao na pratica).
    """
    h = hashlib.sha1()
    h.update(str(len(lats)).encode())
    for lat, lon in zip(lats, lons_360):
        h.update(f"|{lat:.6f},{lon:.6f}".encode())
    return h.hexdigest()[:12]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _grib_path(dt: datetime) -> Path:
    return GRIB_DIR / f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}" / (
        f"{dt.hour:02d}.grib2"
    )


def _samples_path(chash: str, dt: datetime) -> Path:
    return SAMPLES_DIR / chash / (
        f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
    ) / f"{dt.hour:02d}.json"


# ---------------------------------------------------------------------------
# GRIB brutos
# ---------------------------------------------------------------------------

def read_grib(dt: datetime) -> Optional[bytes]:
    """Le um GRIB previamente cacheado em disco. None se nao existir."""
    path = _grib_path(dt)
    if not path.exists():
        return None
    try:
        data = path.read_bytes()
    except OSError as e:
        log.debug("read_grib(%s) falhou: %s", dt, e)
        return None
    if len(data) < 1000:  # mesma sanidade do download
        return None
    return data


def write_grib(dt: datetime, data: bytes) -> None:
    """Persiste GRIB bruto no disco (atomico via .tmp + replace)."""
    if not data or len(data) < 1000:
        return
    path = _grib_path(dt)
    try:
        _ensure_dir(path.parent)
        tmp = path.with_suffix(".grib2.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as e:
        log.debug("write_grib(%s) falhou: %s", dt, e)


# ---------------------------------------------------------------------------
# Samples decodificados (por coords_hash)
# ---------------------------------------------------------------------------

def read_samples(chash: str, dt: datetime) -> Optional[List[float]]:
    """Le samples cacheados para esta malha + hora; None se faltar."""
    path = _samples_path(chash, dt)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.debug("read_samples(%s,%s) falhou: %s", chash, dt, e)
        return None
    if not isinstance(obj, dict):
        return None
    vals = obj.get("samples")
    if not isinstance(vals, list):
        return None
    try:
        return [float(v) for v in vals]
    except (TypeError, ValueError):
        return None


def write_samples(
    chash: str, dt: datetime, samples: List[float],
) -> None:
    """Persiste samples no disco (atomico)."""
    if not samples:
        return
    path = _samples_path(chash, dt)
    payload = {
        "coords_hash": chash,
        "hour_utc": dt.replace(tzinfo=timezone.utc).isoformat(),
        "n": len(samples),
        "samples": [round(float(v), 4) for v in samples],
    }
    try:
        _ensure_dir(path.parent)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as e:
        log.debug("write_samples(%s,%s) falhou: %s", chash, dt, e)


# ---------------------------------------------------------------------------
# Politica de refetch por idade
# ---------------------------------------------------------------------------

def should_refetch(
    dt: datetime,
    now: Optional[datetime] = None,
    last_check: Optional[datetime] = None,
) -> bool:
    """Decide se uma hora cacheada deve ser re-baixada.

    Regras:
      - idade < REFETCH_FRESH_HOURS  -> sempre True (INPE pode republicar)
      - idade >= REFETCH_STALE_HOURS -> sempre False (dado final)
      - faixa intermediaria          -> True somente se nunca verificado
        ou se ultima checagem foi ha mais de 24h
    """
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = (now - dt).total_seconds() / 3600.0
    if age_h < REFETCH_FRESH_HOURS:
        return True
    if age_h >= REFETCH_STALE_HOURS:
        return False
    if last_check is None:
        return True
    if last_check.tzinfo is None:
        last_check = last_check.replace(tzinfo=timezone.utc)
    return (now - last_check).total_seconds() > 24 * 3600


# ---------------------------------------------------------------------------
# Limpeza opcional
# ---------------------------------------------------------------------------

def prune_old(now: Optional[datetime] = None) -> Tuple[int, int]:
    """Remove arquivos mais antigos que CACHE_TTL_DAYS. Retorna (gribs, samples)."""
    if CACHE_TTL_DAYS <= 0:
        return (0, 0)
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=CACHE_TTL_DAYS)
    n_grib = _prune_tree(GRIB_DIR, cutoff)
    n_samples = _prune_tree(SAMPLES_DIR, cutoff)
    if n_grib or n_samples:
        log.info(
            "Cache MERGE: limpeza removeu %d GRIBs e %d arquivos de samples",
            n_grib, n_samples,
        )
    return (n_grib, n_samples)


def _prune_tree(root: Path, cutoff: datetime) -> int:
    if not root.exists():
        return 0
    removed = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    # Remove diretorios vazios
    for p in sorted(root.rglob("*"), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass
    return removed
