"""
Unidades de Analise (UAs) = unidade operacional do sistema.

Duas malhas separadas (Produto 7 — processos independentes):
  data/ua_polygons/ua_polygons.geojson — fonte canonica (geometria + RA)
  data/ua_zones/ua_geo.geojson         — encosta (RAGEO por UA)
  data/ua_zones/ua_hidro.geojson       — inundação (RAHID por UA)

Geradas por ferramentas/geracao-uas/ (build_ua_polygons + assign_ra_to_uas).
O centróide amostra chuva MERGE/INPE; o polígono é a tradução visual
do alerta no mapa.

Recarrega do disco quando os arquivos GeoJSON são regenerados (mtime).
"""

from pathlib import Path
import json
import logging

from core.text_encoding import fix_text
from shapely.geometry import shape

log = logging.getLogger("zones")

DER_PROP_KEYS = (
    "cgr", "regional_cgr", "regional", "rc", "residencia_conserva",
    "uba", "uba_codigo", "uba_nome",
)


def _der_from_props(props: dict) -> dict:
    """Atributos DER gravados no GeoJSON da UA (intersecao com camadas)."""
    rc = fix_text(props.get("rc") or props.get("residencia_conserva"))
    cgr = fix_text(props.get("cgr") or props.get("regional_cgr"))
    return {
        "cgr": cgr,
        "regional_cgr": cgr,
        "regional": fix_text(props.get("regional")),
        "rc": rc,
        "residencia_conserva": rc,
        "uba": fix_text(props.get("uba")),
        "uba_codigo": fix_text(props.get("uba_codigo")),
        "uba_nome": fix_text(props.get("uba_nome")),
    }

_DATA = Path(__file__).resolve().parent.parent / "data" / "ua_zones"
_GEOJSON_GEO = _DATA / "ua_geo.geojson"
_GEOJSON_HIDRO = _DATA / "ua_hidro.geojson"

_cache = {
    "geo": [],
    "hidro": [],
    "token": (0.0, 0.0),
}


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def zones_disk_token() -> tuple:
    """Par (mtime geo, mtime hidro) para detectar alteracao no disco."""
    return (_file_mtime(_GEOJSON_GEO), _file_mtime(_GEOJSON_HIDRO))


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
            "nome": fix_text(f"{rodovia}{km_txt} (R{regiao}){suffix}"),
            "rodovia": fix_text(rodovia) if rodovia else rodovia,
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
            "municipio": fix_text(props.get("municipio")),
        }
        zone.update(_der_from_props(props))
        if hazard == "geo":
            zone["ra_geo"] = ra
            zone["ra_hid"] = None
        else:
            zone["ra_hid"] = ra
            zone["ra_geo"] = None
        out.append(zone)
    log.info("ZONES_%s carregado: %d UAs", label, len(out))
    return out


def reload_zones_if_changed(force: bool = False) -> bool:
    """Recarrega GeoJSON se os arquivos mudaram no disco."""
    token = zones_disk_token()
    if not force and token == _cache["token"]:
        return False
    _cache["geo"] = _load_hazard_zones(_GEOJSON_GEO, "geo")
    _cache["hidro"] = _load_hazard_zones(_GEOJSON_HIDRO, "hidro")
    _cache["token"] = token
    log.info(
        "Malha UA recarregada do disco (geo=%d hidro=%d)",
        len(_cache["geo"]), len(_cache["hidro"]),
    )
    return True


def get_zones_geo() -> list:
    reload_zones_if_changed()
    return _cache["geo"]


def get_zones_hidro() -> list:
    reload_zones_if_changed()
    return _cache["hidro"]


# Carga inicial + compatibilidade com imports existentes
reload_zones_if_changed(force=True)
ZONES_GEO = _cache["geo"]
ZONES_HIDRO = _cache["hidro"]
ZONES = ZONES_GEO + ZONES_HIDRO
