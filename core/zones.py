"""
Zonas de Analise (UAs aproximadas) = unidade operacional do sistema.

Uma ZONA e um trecho contiguo da rodovia com o mesmo RA, digitalizado das
figuras da secao 3.3.3 do Produto 7 e projetado na malha DER/SP real
(scripts/digitize_ua_figures.py). O RA e calibrado pelas Tabelas oficiais
3.3.3.1-3/-4 onde ha trecho critico mapeado (fonte='tabela'); fora dele,
vem da figura (fonte='figura').

As zonas SUBSTITUEM os antigos pontos de monitoramento: sao a regiao real
onde o evento (escorregamento/inundacao) pode ocorrer. Cada zona expoe um
ponto representativo (lat/lon = meio do trecho) usado para amostrar a chuva
MERGE/INPE, e a geometria da linha para desenho no mapa.

Schema compativel com o aggregator (mesmos campos de monitoring_points) +
'geometry'. RA e escalar por zona (zona homogenea), portanto sem distribuicao.
"""

from pathlib import Path
import json
import logging

log = logging.getLogger("zones")

_GEOJSON = Path(__file__).resolve().parent.parent / "data" / "ua_zones" \
    / "ua_zones.geojson"


def _to_int(v):
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _midpoint(coords):
    """Ponto representativo: vertice medio da linha (lon,lat)->(lat,lon)."""
    if not coords:
        return None, None
    lon, lat = coords[len(coords) // 2]
    return float(lat), float(lon)


def _load_zones():
    if not _GEOJSON.exists():
        log.warning(
            "ua_zones.geojson nao encontrado em %s. "
            "Rode scripts/digitize_ua_figures.py para gerar.", _GEOJSON
        )
        return []
    try:
        data = json.loads(_GEOJSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("falha ao ler %s: %s", _GEOJSON, e)
        return []

    out = []
    for i, feat in enumerate(data.get("features", [])):
        props = feat.get("properties", {})
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        lat, lon = _midpoint(coords)
        if lat is None:
            continue
        regiao = _to_int(props.get("regiao"))
        rodovia = props.get("rodovia")
        km = props.get("km")
        ra_geo = _to_int(props.get("ra_geo"))
        ra_hid = _to_int(props.get("ra_hid"))
        ra = _to_int(props.get("ra"))
        fonte = props.get("fonte", "figura")
        zid = f"R{regiao}-{i:03d}"
        km_txt = f" km {km:.1f}" if isinstance(km, (int, float)) else ""
        out.append({
            "id": zid,
            "nome": f"{rodovia}{km_txt} (R{regiao})",
            "rodovia": rodovia,
            "km": km,
            "regiao": regiao,
            # ponto representativo para amostrar a chuva
            "lat": lat,
            "lon": lon,
            # RA escalar (zona homogenea) - sem distribuicao
            "ra": ra,
            "ra_geo": ra_geo,
            "ra_hid": ra_hid,
            "ra_geo_dist": None,
            "ra_hid_dist": None,
            "ra_source": f"ua_zone:{fonte}",
            # geometria da linha (lat,lon) para desenho no mapa
            "geometry": [[float(la), float(lo)] for lo, la in coords],
        })
    return out


ZONES = _load_zones()
log.info("ZONES carregado: %d zonas", len(ZONES))
