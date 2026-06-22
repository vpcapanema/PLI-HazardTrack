"""
Enriquece UAs com CGR, UBA e Residencia de Conserva (RC).

Fontes (mesmas camadas do mapa):
  static/data/rc_poligonos.geojson
  static/data/uba_poligonos.geojson
  static/data/cgr_poligonos.geojson
  data/ua_segments/ua_segments_ra.geojson (codigo UBA REGEA-NIPPON)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.text_encoding import fix_text

log = logging.getLogger("ua_der_enrich")

_ROOT = Path(__file__).resolve().parent.parent
_RC = _ROOT / "static" / "data" / "rc_poligonos.geojson"
_UBA = _ROOT / "static" / "data" / "uba_poligonos.geojson"
_CGR = _ROOT / "static" / "data" / "cgr_poligonos.geojson"
_CRS_WORK = "EPSG:5880"

DER_ATTR_COLS = [
    "cgr",
    "regional_cgr",
    "regional",
    "rc",
    "residencia_conserva",
    "uba",
    "uba_codigo",
    "uba_nome",
]


def _require_gpd():
    import geopandas as gpd
    return gpd


@lru_cache(maxsize=1)
def _load_layer(path: Path):
    gpd = _require_gpd()
    if not path.exists():
        log.warning("camada nao encontrada: %s", path)
        return None
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs(_CRS_WORK)


def _best_hit(
    ua_geom,
    layer,
    value_cols: List[str],
):
    """Feicao da camada com maior area de intersecao com a UA."""
    if layer is None or ua_geom is None or ua_geom.is_empty:
        return {}
    hits = layer[layer.intersects(ua_geom)]
    if hits.empty:
        return {}
    best_row = None
    best_area = -1.0
    for _, row in hits.iterrows():
        inter = row.geometry.intersection(ua_geom)
        if inter.is_empty:
            continue
        area = float(inter.area)
        if area > best_area:
            best_area = area
            best_row = row
    if best_row is None:
        return {}
    out = {}
    for col in value_cols:
        val = best_row.get(col)
        if val is None or str(val) == "nan":
            out[col] = None
        else:
            out[col] = fix_text(str(val).strip()) or None
    return out


def _lookup_uba_codigo(
    rodovia: Optional[str], km: Optional[float]
) -> Optional[str]:
    from core.der_units import _lookup_uba_codigo
    if not rodovia or km is None:
        return None
    try:
        return _lookup_uba_codigo(0.0, 0.0, rodovia, km, max_m=1.0)
    except Exception:
        return None


def enrich_row_props(props: Dict[str, Any], ua_geom) -> Dict[str, Any]:
    """Calcula atributos DER para uma UA (geometria shapely em WGS84)."""
    gpd = _require_gpd()
    from shapely.geometry import shape

    if ua_geom is None:
        if props.get("geometry"):
            ua_geom = shape(props["geometry"])
        else:
            return props

    if ua_geom.is_empty:
        return props

    geom_p = gpd.GeoSeries([ua_geom], crs="EPSG:4326").to_crs(_CRS_WORK)[0]

    rc = _load_layer(_RC)
    uba = _load_layer(_UBA)
    cgr = _load_layer(_CGR)

    rc_hit = _best_hit(geom_p, rc, ["rc", "uba", "regional", "regional_cgr"])
    uba_hit = _best_hit(geom_p, uba, ["uba", "regional", "regional_cgr"])
    cgr_hit = _best_hit(geom_p, cgr, ["regional_cgr"])

    cgr_val = (
        rc_hit.get("regional_cgr")
        or uba_hit.get("regional_cgr")
        or cgr_hit.get("regional_cgr")
    )
    rc_val = rc_hit.get("rc")
    uba_nome = rc_hit.get("uba") or uba_hit.get("uba")

    rodovia = props.get("rodovia")
    km = props.get("km")
    uba_codigo = _lookup_uba_codigo(rodovia, km)

    props = dict(props)
    props["cgr"] = cgr_val
    props["regional_cgr"] = cgr_val
    props["regional"] = rc_hit.get("regional") or uba_hit.get("regional")
    props["rc"] = rc_val
    props["residencia_conserva"] = rc_val
    props["uba_nome"] = uba_nome
    props["uba_codigo"] = uba_codigo
    props["uba"] = uba_codigo or uba_nome
    return props


def enrich_geodataframe(gdf):
    """Adiciona colunas DER a GeoDataFrame de UAs (809 feicoes)."""
    gpd = _require_gpd()
    if gdf is None or gdf.empty:
        return gdf

    out = gdf.copy()
    for col in DER_ATTR_COLS:
        if col not in out.columns:
            out[col] = None

    filled = 0
    for idx, row in out.iterrows():
        props = enrich_row_props(row.to_dict(), row.geometry)
        for col in DER_ATTR_COLS:
            out.at[idx, col] = props.get(col)
        if props.get("rc") or props.get("uba"):
            filled += 1

    log.info("UAs enriquecidas com DER: %d/%d", filled, len(out))
    return out
