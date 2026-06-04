"""
Segmentos de rodovia com RA oficial, gerados a partir da malha DER/SP.

Fonte: scripts/build_ua_segments.py
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
    Path(__file__).resolve().parent.parent
    / "data" / "ua_segments" / "ua_segments_ra.geojson"
)


def _load_segments():
    """Carrega segmentos do GeoJSON (lazy import geopandas)."""
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError:
        log.warning(
            "geopandas/shapely nao instalado. "
            "UA segments nao carregado."
        )
        return None, None

    if not _GEOJSON.exists():
        log.warning("ua_segments_ra.geojson nao encontrado. "
                    "Rode scripts/build_ua_segments.py para gerar.")
        return None, None

    try:
        gdf = gpd.read_file(_GEOJSON)
    except Exception as e:
        log.error("falha ao ler %s: %s", _GEOJSON, e)
        return None, None

    log.info("Segmentos carregados: %d", len(gdf))
    return gdf, Point


def get_ra_by_location(
    lat: float, lon: float, rodovia: Optional[str] = None,
    max_distance_m: float = 500.0
) -> Tuple[Optional[int], Optional[int], str]:
    """
    Retorna (ra_geo, ra_hid, source) para um ponto (lat, lon).

    Busca o segmento da malha DER/SP mais proximo do ponto.
    Se estiver dentro de max_distance_m, retorna o RA do segmento.
    Caso contrario, retorna (None, None, "SEM_DADO").

    Args:
        lat, lon: coordenadas WGS84
        rodovia: opcional, filtra por rodovia (ex: "SP 055")
        max_distance_m: distancia maxima em metros para match

    Returns:
        (ra_geo, ra_hid, source)
    """
    gdf, Point = _load_segments()
    if gdf is None or Point is None:
        return (None, None, "SEM_DADO")

    pt = Point(lon, lat)
    gdf_proj = gdf.to_crs(epsg=3857)  # Web Mercator para distancia em metros
    pt_proj = gpd.GeoSeries([pt], crs="EPSG:4326").to_crs(epsg=3857)[0]

    # Calcula distancia a cada segmento
    gdf_proj["dist"] = gdf_proj.distance(pt_proj)

    # Filtra por rodovia se informada
    if rodovia:
        rod_norm = rodovia.strip().upper()
        gdf_proj = gdf_proj[gdf_proj["rodovia"] == rod_norm]

    if gdf_proj.empty:
        return (None, None, "SEM_DADO")

    # Encontra o mais proximo
    nearest = gdf_proj.loc[gdf_proj["dist"].idxmin()]
    dist_m = nearest["dist"]

    if dist_m > max_distance_m:
        return (None, None, "SEM_DADO")

    ra_geo = nearest.get("ra_geo")
    ra_hid = nearest.get("ra_hid")
    src = nearest.get("source", "SEM_DADO")
    desc = nearest.get("desc", "")
    uba = nearest.get("uba", "")

    if src == "regea2021":
        detail = f"{uba}:{desc}" if uba else desc
        src = f"ua_segments:{detail}"

    import math
    return (
        int(ra_geo) if (ra_geo is not None and not math.isnan(ra_geo))
        else None,
        int(ra_hid) if (ra_hid is not None and not math.isnan(ra_hid))
        else None,
        src
    )
