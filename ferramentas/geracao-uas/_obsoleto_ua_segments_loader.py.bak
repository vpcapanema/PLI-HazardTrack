"""
Segmentos de rodovia com RA oficial, gerados a partir da malha DER/SP.

Fonte: ferramentas/geracao-uas/build_ua_segments.py
Dados: malha DER/SP oficial + RA dos relatorios REGEA-NIPPON 2021

Como os shapefiles das 809 UAs nao estao disponiveis (Anexo B do
Produto 7, Google Drive inacessivel), esta solucao alternativa usa:

1. Malha DER/SP oficial (LineString por trecho)
2. RA por trecho dos relatorios (Tabelas 3.3.3.1-3 e 3.3.3.1-4)
3. Intersecao espacial: dado um ponto (lat,lon), encontra o segmento
   da malha mais proximo e retorna seu RA

Politica:
- Ponto em segmento com RA oficial: retorna RA real
- Ponto fora de segmentos ou em segmento SEM_DADO: retorna None
- Nunca inventar RA
"""

from pathlib import Path
from typing import Optional, Tuple
import logging

try:
    import geopandas as gpd
    from shapely.geometry import Point
    _HAS_GEO = True
except ImportError:
    _HAS_GEO = False
    gpd = None  # type: ignore
    Point = None  # type: ignore

log = logging.getLogger("ua_segments")

_GEOJSON = (
    Path(__file__).resolve().parents[2]
    / "data" / "ua_segments" / "ua_segments_ra.geojson"
)


def _load_segments():
    """Carrega segmentos do GeoJSON. Usa geopandas/shapely do topo."""
    if not _HAS_GEO or gpd is None or Point is None:
        log.warning(
            "geopandas/shapely nao instalado. UA segments nao carregado."
        )
        return None, None

    if not _GEOJSON.exists():
        log.warning("ua_segments_ra.geojson nao encontrado. "
                    "Rode ferramentas/geracao-uas/build_ua_segments.py "
                    "para gerar.")
        return None, None

    try:
        gdf = gpd.read_file(_GEOJSON)
    except Exception as e:
        log.error("falha ao ler %s: %s", _GEOJSON, e)
        return None, None

    log.info("Segmentos carregados: %d", len(gdf))
    return gdf, Point


def _nearest_segment(lat, lon, rodovia, max_distance_m):
    """Retorna a linha do segmento mais proximo dentro de max_distance_m."""
    gdf, point_cls = _load_segments()
    if gdf is None or point_cls is None:
        return None

    pt = point_cls(lon, lat)
    gdf_proj = gdf.to_crs(epsg=3857)  # Web Mercator para distancia em metros
    pt_proj = gpd.GeoSeries([pt], crs="EPSG:4326").to_crs(epsg=3857)[0]
    gdf_proj["dist"] = gdf_proj.distance(pt_proj)

    if rodovia:
        rod_norm = rodovia.strip().upper()
        gdf_proj = gdf_proj[gdf_proj["rodovia"] == rod_norm]

    if gdf_proj.empty:
        return None

    nearest = gdf_proj.loc[gdf_proj["dist"].idxmin()]
    if nearest["dist"] > max_distance_m:
        return None
    return nearest


def _to_int(v):
    import math
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_dist(v):
    """Le coluna dist_geo/dist_hid (JSON string) -> {int: int} ou None."""
    if v is None or (isinstance(v, float)):  # NaN vem como float
        return None
    try:
        import json
        d = json.loads(v) if isinstance(v, str) else v
        out = {int(k): int(n) for k, n in d.items() if n and int(n) > 0}
        return out or None
    except (ValueError, TypeError, AttributeError):
        return None


def get_ra_by_location(
    lat: float, lon: float, rodovia: Optional[str] = None,
    max_distance_m: float = 500.0
) -> Tuple[Optional[int], Optional[int], str]:
    """
    Retorna (ra_geo, ra_hid, source) para um ponto (lat, lon), usando a maior
    classe presente no segmento mais proximo (pior caso). Compatibilidade.
    """
    nearest = _nearest_segment(lat, lon, rodovia, max_distance_m)
    if nearest is None:
        return (None, None, "SEM_DADO")

    ra_geo = _to_int(nearest.get("ra_geo_max"))
    ra_hid = _to_int(nearest.get("ra_hid_max"))
    src = nearest.get("source", "SEM_DADO")
    if src == "regea2021":
        uba = nearest.get("uba", "") or ""
        desc = nearest.get("desc", "") or ""
        src = f"ua_segments:{uba}:{desc}" if uba else f"ua_segments:{desc}"
    return (ra_geo, ra_hid, src)


def get_ra_dist_by_location(
    lat: float, lon: float, rodovia: Optional[str] = None,
    max_distance_m: float = 500.0
):
    """
    Retorna a distribuicao completa de RA do segmento mais proximo:
        (dist_geo, dist_hid, ra_geo_max, ra_hid_max, source)
    Usado como fallback espacial quando o lookup por km nao cobre o ponto.
    """
    nearest = _nearest_segment(lat, lon, rodovia, max_distance_m)
    if nearest is None:
        return (None, None, None, None, "SEM_DADO")

    dist_geo = _parse_dist(nearest.get("dist_geo"))
    dist_hid = _parse_dist(nearest.get("dist_hid"))
    ra_geo = _to_int(nearest.get("ra_geo_max"))
    ra_hid = _to_int(nearest.get("ra_hid_max"))
    src = nearest.get("source", "SEM_DADO")
    if src == "regea2021":
        uba = nearest.get("uba", "") or ""
        src = f"ua_segments:{uba}" if uba else "ua_segments"
    return (dist_geo, dist_hid, ra_geo, ra_hid, src)
