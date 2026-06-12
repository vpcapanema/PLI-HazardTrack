"""
Unidades de Analise (UAs) = unidade operacional do sistema.

Duas malhas separadas (Produto 7 — processos independentes):
  data/ua_zones/ua_geo.geojson    — encosta (RAGEO por UA)
  data/ua_zones/ua_hidro.geojson — inundação (RAHID por UA)

Geradas por ferramentas/geracao-uas/assign_ra_to_uas.py.
O centróide amostra chuva MERGE/INPE; o polígono é a tradução visual
do alerta no mapa.
"""

from pathlib import Path
import json
import logging

from shapely.geometry import shape

log = logging.getLogger("zones")

_DATA = Path(__file__).resolve().parent.parent / "data" / "ua_zones"
_GEOJSON_GEO = _DATA / "ua_geo.geojson"
_GEOJSON_HIDRO = _DATA / "ua_hidro.geojson"


def _to_int(v):
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _centroid_and_ring(geom):
    """Retorna (lat, lon, ring_latlon, geometry_type) a partir da geometria."""
    g = shape(geom)
    c = g.centroid
    lat, lon = float(c.y), float(c.x)
    gtype = geom.get("type")
    if gtype == "Polygon":
        ring = [[float(la), float(lo)]
                for lo, la in geom["coordinates"][0]]
        return lat, lon, ring, "polygon"
    if gtype == "LineString":
        coords = geom.get("coordinates", [])
        if coords:
            lon, lat = coords[len(coords) // 2]
            ring = [[float(la), float(lo)] for lo, la in coords]
            return float(lat), float(lon), ring, "polyline"
    if gtype == "MultiPolygon" and geom["coordinates"]:
        ring = [[float(la), float(lo)]
                for lo, la in geom["coordinates"][0][0]]
        return lat, lon, ring, "polygon"
    return lat, lon, None, "point"


def _load_hazard_zones(path: Path, hazard: str):
    """Carrega UAs de um GeoJSON mono-canal (geo ou hidro)."""
    if not path.exists():
        log.warning(
            "%s nao encontrado. Rode ferramentas/geracao-uas/"
            "build_ua_polygons.py e assign_ra_to_uas.py.", path
        )
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("falha ao ler %s: %s", path, e)
        return []

    label = "GEO" if hazard == "geo" else "HIDRO"
    out = []
    for i, feat in enumerate(data.get("features", [])):
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        if gtype not in ("Polygon", "LineString", "MultiPolygon"):
            continue
        lat, lon, ring, geometry_type = _centroid_and_ring(geom)
        if ring is None or len(ring) < 2:
            continue
        regiao = _to_int(props.get("regiao"))
        rodovia = props.get("rodovia")
        km = props.get("km")
        ra = _to_int(props.get("ra"))
        zid = props.get("id") or f"R{regiao}-{i:03d}"
        km_txt = f" km {km:.1f}" if isinstance(km, (int, float)) else ""
        suffix = " encosta" if hazard == "geo" else " hidro"
        ra_key = "ra_geo" if hazard == "geo" else "ra_hid"
        zone = {
            "id": zid,
            "nome": f"{rodovia}{km_txt} (R{regiao}){suffix}",
            "rodovia": rodovia,
            "km": km,
            "regiao": regiao,
            "lat": lat,
            "lon": lon,
            "hazard": hazard,
            "ra": ra,
            ra_key: ra,
            "ra_source": (
                props.get("fonte") or props.get("ra_fonte") or "figura"
            ),
            "geometry": ring,
            "geometry_type": geometry_type,
        }
        if hazard == "geo":
            zone["ra_geo"] = ra
            zone["ra_hid"] = None
        else:
            zone["ra_hid"] = ra
            zone["ra_geo"] = None
        out.append(zone)
    log.info("ZONES_%s carregado: %d UAs", label, len(out))
    return out


ZONES_GEO = _load_hazard_zones(_GEOJSON_GEO, "geo")
ZONES_HIDRO = _load_hazard_zones(_GEOJSON_HIDRO, "hidro")

# Compatibilidade legada (testes / imports antigos)
ZONES = ZONES_GEO + ZONES_HIDRO
