"""
Leitura/publicacao do modulo estadual de risco de queimadas.

Este modulo NAO baixa dados e NAO calcula RF no ciclo HTTP. Ele apenas le os
produtos prontos gerados por `ferramentas/queimadas/`:

- `static/data/queimadas/risco_trechos_der_latest.geojson`
- `static/data/queimadas/risco_trechos_der_latest.json`

Se os produtos ainda nao existem, publica uma camada `SEM_DADO` derivada da
malha base `data/queimadas/base/trechos_der_sp.gpkg`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static" / "data" / "queimadas"
DATA_DIR = ROOT / "data" / "queimadas"
LATEST_GEOJSON = STATIC_DIR / "risco_trechos_der_latest.geojson"
LATEST_JSON = STATIC_DIR / "risco_trechos_der_latest.json"
BASE_TRECHOS = DATA_DIR / "base" / "trechos_der_sp.gpkg"

SEM_DADO = "SEM_DADO"
METHODOLOGY = "INPE-RF-v11"

_cache: Dict[str, Any] = {
    "token": None,
    "geojson": None,
    "snapshot": None,
}


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _disk_token() -> Tuple[float, float, float]:
    return (_mtime(LATEST_GEOJSON), _mtime(LATEST_JSON), _mtime(BASE_TRECHOS))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sem_dado_props() -> Dict[str, Any]:
    return {
        "rf_valor": None,
        "rf_classe": SEM_DADO,
        "rf_p90": None,
        "rf_media": None,
        "horizonte": "observado",
        "data_referencia": None,
        "data_alvo": None,
        "metodologia": METHODOLOGY,
        "fonte_precipitacao": None,
        "fonte_meteo": None,
        "focos_correcao": False,
        "data_status": "no_data",
    }


def _load_latest_geojson() -> Dict[str, Any]:
    with LATEST_GEOJSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("metadata", {})
    data["metadata"].setdefault("source", str(LATEST_GEOJSON))
    return data


def _horizon_slug(value: str) -> str:
    return value.replace("+", "").replace(" ", "").lower()


def _geojson_path_for_horizon(horizonte: str) -> Path:
    if horizonte in ("", "observado", None):
        return LATEST_GEOJSON
    return STATIC_DIR / f"risco_trechos_der_{_horizon_slug(horizonte)}.geojson"


def _load_geojson_path(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("metadata", {})
    data["metadata"].setdefault("source", str(path))
    return data


def _load_latest_snapshot() -> Dict[str, Any]:
    if not LATEST_JSON.exists():
        return _build_snapshot_from_geojson(_load_latest_geojson())
    with LATEST_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


def _build_fallback_geojson() -> Dict[str, Any]:
    if not BASE_TRECHOS.exists():
        return {
            "type": "FeatureCollection",
            "metadata": {
                "modulo": "queimadas",
                "data_status": "no_data",
                "message": "Produto de queimadas e malha base ausentes.",
                "metodologia": METHODOLOGY,
                "gerado_em": _now_iso(),
            },
            "features": [],
        }

    import geopandas as gpd

    gdf = gpd.read_file(BASE_TRECHOS, layer="trechos").to_crs("EPSG:4326")
    data = json.loads(gdf.to_json())
    for feature in data.get("features", []):
        props = feature.setdefault("properties", {})
        props.update(_sem_dado_props())
    data["metadata"] = {
        "modulo": "queimadas",
        "data_status": "no_data",
        "message": "Risco de queimadas ainda nao calculado.",
        "metodologia": METHODOLOGY,
        "features": len(data.get("features", [])),
        "source": str(BASE_TRECHOS),
        "gerado_em": _now_iso(),
    }
    return data


def _build_snapshot_from_geojson(geojson: Dict[str, Any]) -> Dict[str, Any]:
    features = geojson.get("features") or []
    counts: Dict[str, int] = {}
    for feature in features:
        props = feature.get("properties") or {}
        cls = props.get("rf_classe") or SEM_DADO
        counts[cls] = counts.get(cls, 0) + 1
    metadata = geojson.get("metadata") or {}
    return {
        "modulo": "queimadas",
        "metodologia": metadata.get("metodologia") or METHODOLOGY,
        "data_status": metadata.get("data_status") or "ok",
        "data_referencia": metadata.get("data_referencia"),
        "gerado_em": metadata.get("gerado_em") or _now_iso(),
        "horizontes_disponiveis": metadata.get("horizontes_disponiveis")
        or ["observado"],
        "total_trechos": len(features),
        "classes": counts,
        "source": metadata.get("source"),
    }


def _load_locked() -> None:
    token = _disk_token()
    if _cache.get("token") == token:
        return
    if LATEST_GEOJSON.exists():
        geojson = _load_latest_geojson()
        snapshot = _load_latest_snapshot()
    else:
        geojson = _build_fallback_geojson()
        snapshot = _build_snapshot_from_geojson(geojson)
    _cache.update({
        "token": token,
        "geojson": geojson,
        "snapshot": snapshot,
    })


def get_fire_risk_geojson(
    horizonte: str = "observado",
    min_class: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna FeatureCollection para o mapa publico."""
    _load_locked()
    path = _geojson_path_for_horizon(horizonte)
    if path.exists():
        data = _load_geojson_path(path)
    else:
        data = json.loads(json.dumps(_cache["geojson"]))
    data.setdefault("metadata", {})
    data["metadata"]["requested_horizonte"] = horizonte
    if min_class:
        # Filtro simples reservado para uso futuro; SEM_DADO nao ordena.
        data["features"] = [
            f for f in data.get("features", [])
            if (f.get("properties") or {}).get("rf_classe") == min_class
        ]
    return data


def get_fire_risk_snapshot() -> Dict[str, Any]:
    """Resumo estadual do ultimo produto publicado."""
    _load_locked()
    return json.loads(json.dumps(_cache["snapshot"]))


def get_fire_risk_by_trecho(
    trecho_id: str,
    horizonte: str = "observado",
) -> Optional[Dict[str, Any]]:
    """Detalhe de um trecho DER-SP."""
    data = get_fire_risk_geojson(horizonte=horizonte)
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        if str(props.get("trecho_id")) == str(trecho_id):
            return {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": props,
                "metadata": data.get("metadata") or {},
            }
    return None
