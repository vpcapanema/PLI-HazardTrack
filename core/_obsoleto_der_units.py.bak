"""
Residencia de Conserva (RC) e UBA DER por coordenada da UA.

Fontes:
  - static/data/rc_poligonos.geojson (poligonos RC/UBA DER)
  - data/ua_segments/ua_segments_ra.geojson (codigo UBA REGEA-NIPPON)
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from core.text_encoding import fix_text

log = logging.getLogger("der_units")

_ROOT = Path(__file__).resolve().parent.parent
_RC_GEOJSON = _ROOT / "static" / "data" / "rc_poligonos.geojson"
_SEG_GEOJSON = _ROOT / "data" / "ua_segments" / "ua_segments_ra.geojson"


def _empty_units() -> Dict[str, Optional[str]]:
    return {
        "rc": None,
        "residencia_conserva": None,
        "uba": None,
        "uba_codigo": None,
        "uba_nome": None,
        "regional": None,
        "regional_cgr": None,
    }


@lru_cache(maxsize=1)
def _load_rc_index():
    try:
        import geopandas as gpd
    except ImportError:
        log.warning("geopandas indisponivel — RC/UBA nao carregados")
        return None
    if not _RC_GEOJSON.exists():
        log.warning("rc_poligonos.geojson nao encontrado")
        return None
    try:
        return gpd.read_file(_RC_GEOJSON)
    except Exception as exc:
        log.error("falha ao ler RC: %s", exc)
        return None


@lru_cache(maxsize=1)
def _load_segments_index():
    try:
        import geopandas as gpd
    except ImportError:
        return None
    if not _SEG_GEOJSON.exists():
        return None
    try:
        gdf = gpd.read_file(_SEG_GEOJSON)
        return gdf.to_crs(epsg=3857)
    except Exception as exc:
        log.error("falha ao ler ua_segments: %s", exc)
        return None


def _lookup_rc(lat: float, lon: float) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    gdf = _load_rc_index()
    if gdf is None:
        return out
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        hits = gdf[gdf.contains(pt)]
        if hits.empty:
            return out
        row = hits.iloc[0]
        rc = fix_text(str(row.get("rc") or "")) or None
        out["rc"] = rc
        out["residencia_conserva"] = rc
        out["uba_nome"] = fix_text(str(row.get("uba") or "")) or None
        out["regional"] = fix_text(str(row.get("regional") or "")) or None
        cgr = row.get("regional_cgr")
        out["regional_cgr"] = fix_text(str(cgr)) if cgr else None
    except Exception as exc:
        log.debug("lookup RC falhou: %s", exc)
    return out


def _lookup_uba_codigo(
    lat: float,
    lon: float,
    rodovia: Optional[str],
    km: Optional[float] = None,
    max_m: float = 800.0,
) -> Optional[str]:
    gdf = _load_segments_index()
    if gdf is None:
        return None
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        if rodovia and km is not None:
            try:
                km_f = float(km)
                rod_norm = rodovia.strip().upper()
                on_rod = gdf[gdf["rodovia"] == rod_norm]
                if not on_rod.empty and "km_ini" in on_rod.columns:
                    tol = 0.05
                    hit = on_rod[
                        (on_rod["km_ini"] <= km_f + tol)
                        & (on_rod["km_fim"] >= km_f - tol)
                    ]
                    if not hit.empty:
                        uba = hit.iloc[0].get("uba")
                        if uba is not None and str(uba) != "nan":
                            uba_s = fix_text(str(uba).strip())
                            if uba_s:
                                return uba_s
            except (TypeError, ValueError):
                pass

        pt385 = gpd.GeoSeries(
            [Point(lon, lat)], crs="EPSG:4326"
        ).to_crs(epsg=3857)[0]
        work = gdf
        if rodovia:
            rod_norm = rodovia.strip().upper()
            work = work[work["rodovia"] == rod_norm]
        if work.empty:
            return None
        work = work.copy()
        work["dist"] = work.distance(pt385)
        nearest = work.loc[work["dist"].idxmin()]
        if float(nearest["dist"]) > max_m:
            return None
        uba = nearest.get("uba")
        if uba is None or (isinstance(uba, float) and str(uba) == "nan"):
            return None
        uba_s = fix_text(str(uba).strip())
        return uba_s or None
    except Exception as exc:
        log.debug("lookup UBA codigo falhou: %s", exc)
        return None


def lookup_der_units(
    lat: float,
    lon: float,
    rodovia: Optional[str] = None,
    km: Optional[float] = None,
) -> Dict[str, Optional[str]]:
    """Retorna CGR, RC, UBA e regional DER para o trecho da UA."""
    out = _empty_units()
    out.update(_lookup_rc(lat, lon))
    uba_code = _lookup_uba_codigo(lat, lon, rodovia, km)
    if uba_code:
        out["uba_codigo"] = uba_code
        out["uba"] = uba_code
    elif out.get("uba_nome"):
        out["uba"] = out["uba_nome"]
    return out


def format_uba_display(units: Dict[str, Any]) -> str:
    """Texto amigavel para popup: codigo + nome quando disponiveis."""
    code = units.get("uba_codigo") or units.get("uba")
    nome = units.get("uba_nome")
    if code and nome and code != nome:
        return f"{code} — {nome}"
    return code or nome or "—"
