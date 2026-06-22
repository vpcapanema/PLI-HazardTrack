"""
Unidades de Analise (UAs) = unidade operacional do sistema.

Duas malhas separadas (Produto 7 - canais independentes):
  data/ua_zones/ua_geo.geojson    - encosta   (RAGEO + ICC GEO)
  data/ua_zones/ua_hidro.geojson  - inundacao (RAHID + ICC HID)

Ambas geradas por:
  ferramentas/geracao-geopackage/04_export_ua_geojsons.py
a partir da camada `uas_area_estudo` do GeoPackage
`data/pli-hazardtrack.gpkg` (fonte unica de verdade).

CONTRATO DE ATRIBUTOS: este modulo NAO renomeia nem normaliza nada.
Cada UA propaga LITERALMENTE os campos da camada-mae para o restante
do sistema, mais alguns campos derivados puramente geometricos
(`lat`, `lon`, `geometry` no formato anel-latlon, `geometry_type`).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import shape

log = logging.getLogger("zones")

_DATA = Path(__file__).resolve().parent.parent / "data" / "ua_zones"
_GEOJSON_GEO = _DATA / "ua_geo.geojson"
_GEOJSON_HIDRO = _DATA / "ua_hidro.geojson"

_cache: Dict[str, Any] = {
    "geo": [],
    "hidro": [],
    "token": (0.0, 0.0),
}


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def zones_disk_token() -> Tuple[float, float]:
    """(mtime geo, mtime hidro) - detector de alteracao no disco."""
    return (_file_mtime(_GEOJSON_GEO), _file_mtime(_GEOJSON_HIDRO))


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_thresholds(raw: Any) -> Optional[List[float]]:
    """Converte 'a;b;c;d' em [a, b, c, d] (mantem ordem)."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [float(x) for x in raw]
    txt = str(raw).strip()
    if not txt:
        return None
    parts = [p for p in txt.replace(",", ";").split(";") if p.strip()]
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def _ring_from_coords(coords: List[List[float]]) -> List[List[float]]:
    """Converte [[lon, lat, ...], ...] -> [[lat, lon], ...] descartando Z."""
    return [[float(c[1]), float(c[0])] for c in coords]


def _centroid_and_ring(
    geom: Dict[str, Any],
    centroide_lat: Optional[float],
    centroide_lon: Optional[float],
) -> Tuple[float, float, Optional[List[List[float]]], str]:
    """Retorna (lat, lon, ring_latlon, geometry_type)."""
    g = shape(geom)
    c = g.centroid
    lat = float(centroide_lat) if centroide_lat is not None \
        else float(c.y)
    lon = float(centroide_lon) if centroide_lon is not None \
        else float(c.x)
    gtype = geom.get("type")
    if gtype == "Polygon":
        return lat, lon, _ring_from_coords(geom["coordinates"][0]), \
            "polygon"
    if gtype == "LineString":
        return lat, lon, _ring_from_coords(geom.get("coordinates", [])), \
            "polyline"
    if gtype == "MultiPolygon" and geom["coordinates"]:
        return lat, lon, _ring_from_coords(geom["coordinates"][0][0]), \
            "polygon"
    if gtype == "MultiLineString" and geom["coordinates"]:
        return lat, lon, _ring_from_coords(geom["coordinates"][0]), \
            "polyline"
    return lat, lon, None, "point"


def _load_hazard_zones(path: Path, hazard: str) -> List[Dict[str, Any]]:
    """Le um GeoJSON mono-canal e devolve lista de UAs (dicts)."""
    if not path.exists():
        log.warning(
            "%s nao encontrado. Rode "
            "ferramentas/geracao-geopackage/04_export_ua_geojsons.py.",
            path,
        )
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("falha ao ler %s: %s", path, e)
        return []

    ra_key = "RAGEO" if hazard == "geo" else "RAHID"
    icc_key = "icc_geo_thresholds" if hazard == "geo" \
        else "icc_hid_thresholds"
    flag_key = "trecho_critico_geo" if hazard == "geo" \
        else "trecho_critico_hid"

    out: List[Dict[str, Any]] = []
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        if gtype not in ("Polygon", "LineString", "MultiPolygon",
                         "MultiLineString"):
            continue
        lat, lon, ring, geometry_type = _centroid_and_ring(
            geom,
            _to_float(props.get("centroide_lat")),
            _to_float(props.get("centroide_lon")),
        )
        if ring is None or len(ring) < 2:
            continue

        zone: Dict[str, Any] = {
            # Identificacao
            "ua_id": props.get("ua_id"),
            "regiao_id": _to_int(props.get("regiao_id")),
            "regiao_nome": props.get("regiao_nome"),
            "sigla_rodovia": props.get("sigla_rodovia"),
            "escala": props.get("escala"),
            "tipo": props.get("tipo"),
            "extensao_km": _to_float(props.get("extensao_km")),
            "ordem_no_grupo": _to_int(props.get("ordem_no_grupo")),
            # Linear referencing (km cadastral)
            "km_inicial": _to_float(props.get("km_inicial")),
            "km_final": _to_float(props.get("km_final")),
            "subtrecho_der": props.get("subtrecho_der"),
            # Atributos administrativos DER
            "municipio": props.get("municipio"),
            "regional": props.get("regional"),
            "residencia_dr": props.get("residencia_dr"),
            "uba_nome": props.get("uba_nome"),
            "uba_codigo": props.get("uba_codigo"),
            "jurisdicao": props.get("jurisdicao"),
            "conservado_por": props.get("conservado_por"),
            # Geometria
            "centroide_lon": _to_float(props.get("centroide_lon")) or lon,
            "centroide_lat": _to_float(props.get("centroide_lat")) or lat,
            "lat": lat,
            "lon": lon,
            "geometry": ring,
            "geometry_type": geometry_type,
            "buffer_lateral_m": _to_int(props.get("buffer_lateral_m")),
            # ICC do canal corrente
            icc_key: _parse_thresholds(props.get(icc_key)),
            # Flag de trecho critico do canal
            flag_key: bool(props.get(flag_key)),
            # Hazard + RA do canal
            "hazard": hazard,
            ra_key: _to_int(props.get(ra_key)),
        }
        out.append(zone)
    label = "GEO" if hazard == "geo" else "HIDRO"
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


def get_zones_geo() -> List[Dict[str, Any]]:
    reload_zones_if_changed()
    return _cache["geo"]


def get_zones_hidro() -> List[Dict[str, Any]]:
    reload_zones_if_changed()
    return _cache["hidro"]


# Carga inicial + compatibilidade com imports existentes
reload_zones_if_changed(force=True)
ZONES_GEO = _cache["geo"]
ZONES_HIDRO = _cache["hidro"]
ZONES = ZONES_GEO + ZONES_HIDRO
