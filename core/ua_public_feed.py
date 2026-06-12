"""
Feed publico GeoJSON das UAs com monitoramento em tempo real.

Consumo externo: GET /api/public/ua-layers
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

API_VERSION = "1"

HAZARD_LABELS = {
    "geo": "Risco geologico",
    "hidro": "Risco hidrologico",
}

PUBLIC_PROP_KEYS = (
    "id", "hazard", "hazard_label", "regiao", "region_name", "rodovia", "km",
    "municipio", "ra", "ra_geo", "ra_hid", "rd", "rd_geo", "rd_hid", "nivel",
    "ac96h_mm", "ac24h_mm", "intensity_mmh", "cpc", "icc_geo", "icc_hid",
    "fonte_chuva", "cgr", "regional_cgr", "uba_codigo", "uba_nome",
    "residencia_conserva", "lat", "lon",
)


def _ring_to_geojson(
    ring_latlon: List[List[float]],
    geometry_type: str,
) -> Optional[Dict[str, Any]]:
    """Converte anel [[lat, lon], ...] interno para geometria GeoJSON."""
    if not ring_latlon or len(ring_latlon) < 2:
        return None
    coords = [[float(lon), float(lat)] for lat, lon in ring_latlon]
    if geometry_type == "polygon" and len(coords) >= 3:
        if coords[0] != coords[-1]:
            coords.append(coords[0][:])
        return {"type": "Polygon", "coordinates": [coords]}
    return {"type": "LineString", "coordinates": coords}


def _public_props(p: Dict[str, Any]) -> Dict[str, Any]:
    hazard = p.get("hazard") or "geo"
    props: Dict[str, Any] = {
        "hazard": hazard,
        "hazard_label": HAZARD_LABELS.get(hazard, hazard),
    }
    for key in PUBLIC_PROP_KEYS:
        if key in ("hazard", "hazard_label"):
            continue
        if key in p:
            props[key] = p[key]
    if p.get("source") == "NO_DATA":
        props["monitoramento"] = "indisponivel"
    elif p.get("source"):
        props["monitoramento"] = "ativo"
    else:
        props["monitoramento"] = "ativo"
    return props


def point_to_feature(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """UA monitorada -> Feature GeoJSON (EPSG:4326)."""
    geom = _ring_to_geojson(
        p.get("geometry") or [],
        p.get("geometry_type") or "polyline",
    )
    if geom is None:
        return None
    fid = p.get("id")
    return {
        "type": "Feature",
        "id": fid,
        "geometry": geom,
        "properties": _public_props(p),
    }


def _select_points(
    snap: Dict[str, Any],
    hazard: str,
) -> Tuple[List[Dict[str, Any]], str]:
    hazard = (hazard or "all").strip().lower()
    if hazard == "geo":
        return list(snap.get("points_geo") or []), "geo"
    if hazard in ("hidro", "hidrologico", "inundacao"):
        return list(snap.get("points_hidro") or []), "hidro"
    geo = snap.get("points_geo") or []
    hidro = snap.get("points_hidro") or []
    if geo or hidro:
        return list(geo) + list(hidro), "all"
    return list(snap.get("points") or []), "all"


def build_ua_layers_geojson(
    snap: Dict[str, Any],
    *,
    hazard: str = "all",
    min_rd: Optional[int] = None,
) -> Dict[str, Any]:
    """Monta FeatureCollection GeoJSON para integracao externa."""
    points, hazard_key = _select_points(snap, hazard)
    if min_rd is not None:
        points = [p for p in points if int(p.get("rd") or 0) >= min_rd]

    features: List[Dict[str, Any]] = []
    for p in points:
        feat = point_to_feature(p)
        if feat is not None:
            features.append(feat)

    summary = snap.get("summary") or {}
    return {
        "type": "FeatureCollection",
        "name": "pli-hazardtrack-ua-monitoring",
        "metadata": {
            "api_version": API_VERSION,
            "timestamp_utc": snap.get("timestamp_utc"),
            "data_status": summary.get("data_status"),
            "data_source": summary.get("data_source"),
            "historical": bool(summary.get("historical")),
            "hazard": hazard_key,
            "feature_count": len(features),
            "total_geo": summary.get("total_geo"),
            "total_hidro": summary.get("total_hidro"),
            "max_rd": summary.get("max_rd"),
            "by_level_geo": summary.get("by_level_geo"),
            "by_level_hidro": summary.get("by_level_hidro"),
            "refresh_hint_s": 30,
            "endpoints": {
                "live": "/api/public/ua-layers",
                "geo": "/api/public/ua-layers?hazard=geo",
                "hidro": "/api/public/ua-layers?hazard=hidro",
                "alerts": "/api/public/ua-layers?min_rd=3",
            },
        },
        "features": features,
    }
