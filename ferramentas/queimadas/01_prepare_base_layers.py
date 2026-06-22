"""
Prepara os dados estaticos do modulo de queimadas.

Saidas:
- data/queimadas/base/trechos_der_sp.gpkg
- data/queimadas/base/limite_sp.gpkg
- data/queimadas/base/limite_sp_ibge.geojson
- data/queimadas/metadata/base_layers.json

Este script nao baixa rasters grandes (MapBiomas/DEM). Eles sao tratados por
scripts especificos para evitar downloads pesados sem controle.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import geopandas as gpd
import requests
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.text_encoding import fix_text  # noqa: E402

BASE_DIR = ROOT / "data" / "queimadas" / "base"
META_DIR = ROOT / "data" / "queimadas" / "metadata"
DER_SHP = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
RESIDENCIAS_ZIP = ROOT / "data" / "RESIDENCIAS_CONSERVA_POLIGONOS.zip"

TRECHOS_GPKG = BASE_DIR / "trechos_der_sp.gpkg"
LIMITE_GPKG = BASE_DIR / "limite_sp.gpkg"
LIMITE_GEOJSON = BASE_DIR / "limite_sp_ibge.geojson"
BASE_META = META_DIR / "base_layers.json"

IBGE_SP_URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados/35"
    "?formato=application/vnd.geo+json&qualidade=maxima"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _drop_z(geom):
    if geom is None:
        return None
    if hasattr(geom, "has_z") and geom.has_z:
        return shp_transform(lambda x, y, z=None: (x, y), geom)
    return geom


def _norm_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        return fix_text(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return value
    return value


def _trecho_id(row) -> str:
    parts = [
        row.get("rodovia"),
        row.get("km_ini"),
        row.get("km_fim"),
        row.get("orientacao"),
        row.get("municipio"),
    ]
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _residencias_zip_path() -> str:
    path = str(RESIDENCIAS_ZIP.resolve()).replace("\\", "/")
    return (
        f"zip://{path}"
        "!RESIDENCIAS_CONSERVA_POLIGONOS/"
        "residencia_conserva_poligonos.shp"
    )


def _read_residencias_conserva() -> gpd.GeoDataFrame:
    if not RESIDENCIAS_ZIP.exists():
        raise FileNotFoundError(f"ZIP ausente: {RESIDENCIAS_ZIP}")
    gdf = gpd.read_file(_residencias_zip_path(), encoding="latin1")
    keep = ["Regional", "UBA", "RC", "geometry"]
    gdf = gdf[[c for c in keep if c in gdf.columns]].rename(columns={
        "Regional": "residencia_dr",
        "UBA": "uba_nome",
        "RC": "uba_codigo",
    })
    for col in ("residencia_dr", "uba_nome", "uba_codigo"):
        if col in gdf.columns:
            gdf[col] = gdf[col].map(_norm_value)
    return gdf.to_crs("EPSG:4326")


def _enrich_with_residencias(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Atribui residencia/UBA pelo poligono DER com maior intersecao."""
    for col in ("residencia_dr", "uba_codigo", "uba_nome"):
        if col not in gdf.columns:
            gdf[col] = None
    try:
        resid = _read_residencias_conserva()
    except FileNotFoundError as exc:
        print(f"AVISO: {exc}; atributos UBA/RC ficam vazios.")
        return gdf

    metric_crs = "EPSG:31983"
    roads_m = gdf.to_crs(metric_crs).reset_index(names="_road_idx")
    resid_m = resid.to_crs(metric_crs).reset_index(names="_res_idx")
    joined = gpd.sjoin(
        roads_m[["_road_idx", "geometry"]],
        resid_m[["residencia_dr", "uba_codigo", "uba_nome", "geometry"]],
        how="left",
        predicate="intersects",
    )
    if joined.empty:
        return gdf

    def _intersection_length(row) -> float:
        idx = row.get("index_right")
        if idx is None or idx != idx:
            return -1.0
        poly = resid_m.loc[int(idx), "geometry"]
        return float(row.geometry.intersection(poly).length)

    joined["_join_len"] = joined.apply(_intersection_length, axis=1)
    best = (
        joined.sort_values(["_road_idx", "_join_len"], ascending=[True, False])
        .drop_duplicates("_road_idx")
        .set_index("_road_idx")
    )
    for col in ("residencia_dr", "uba_codigo", "uba_nome"):
        gdf[col] = best[col].reindex(gdf.index).values

    matched = int(gdf["uba_codigo"].notna().sum())
    print(f"Atributos residencia/UBA: {matched}/{len(gdf)} trechos preenchidos")
    return gdf


def prepare_trechos() -> dict:
    print(f"Lendo malha DER-SP: {DER_SHP}")
    gdf = gpd.read_file(DER_SHP).to_crs("EPSG:4326")

    keep = [
        "Rodovia", "TipoRodovi", "Orientacao", "Municipio",
        "CodRegiona", "SedeRegion", "Residencia",
        "KmInicial", "KmFinal", "Extensao",
        "Jurisdicao", "Administra", "Conservado",
        "TipoPista", "Denominaca", "geometry",
    ]
    gdf = gdf[[c for c in keep if c in gdf.columns]]
    gdf = gdf.rename(columns={
        "Rodovia": "rodovia",
        "TipoRodovi": "tipo",
        "Orientacao": "orientacao",
        "Municipio": "municipio",
        "CodRegiona": "regional",
        "SedeRegion": "sede_regional",
        "Residencia": "residencia",
        "KmInicial": "km_ini",
        "KmFinal": "km_fim",
        "Extensao": "extensao",
        "Jurisdicao": "jurisdicao",
        "Administra": "administra",
        "Conservado": "conservado",
        "TipoPista": "tipo_pista",
        "Denominaca": "denominacao",
    })

    for col in gdf.columns:
        if col != "geometry":
            gdf[col] = gdf[col].map(_norm_value)
    gdf["geometry"] = gdf["geometry"].apply(_drop_z)
    gdf["trecho_id"] = gdf.apply(_trecho_id, axis=1)
    gdf["conservado_por"] = gdf.get("conservado")
    gdf = _enrich_with_residencias(gdf)

    if gdf["trecho_id"].duplicated().any():
        dupes = int(gdf["trecho_id"].duplicated().sum())
        raise RuntimeError(f"trecho_id duplicado em {dupes} feicoes")

    TRECHOS_GPKG.unlink(missing_ok=True)
    gdf.to_file(TRECHOS_GPKG, layer="trechos", driver="GPKG")
    print(f"Salvo: {TRECHOS_GPKG}")

    return {
        "path": str(TRECHOS_GPKG.relative_to(ROOT)),
        "layer": "trechos",
        "features": int(len(gdf)),
        "crs": "EPSG:4326",
        "bbox": [float(x) for x in gdf.total_bounds],
        "sha256": _sha256(TRECHOS_GPKG),
    }


def prepare_limite_sp() -> dict:
    print(f"Baixando limite SP (IBGE): {IBGE_SP_URL}")
    response = requests.get(IBGE_SP_URL, timeout=(10, 90))
    response.raise_for_status()
    LIMITE_GEOJSON.write_bytes(response.content)

    gdf = gpd.read_file(LIMITE_GEOJSON).to_crs("EPSG:4326")
    LIMITE_GPKG.unlink(missing_ok=True)
    gdf.to_file(LIMITE_GPKG, layer="limite_sp", driver="GPKG")
    print(f"Salvo: {LIMITE_GPKG}")

    return {
        "path": str(LIMITE_GPKG.relative_to(ROOT)),
        "source_raw": str(LIMITE_GEOJSON.relative_to(ROOT)),
        "layer": "limite_sp",
        "features": int(len(gdf)),
        "crs": "EPSG:4326",
        "bbox": [float(x) for x in gdf.total_bounds],
        "sha256": _sha256(LIMITE_GPKG),
        "source_url": IBGE_SP_URL,
    }


def main() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "modulo": "queimadas",
        "status": "base_estatica_parcial",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "layers": {
            "trechos_der_sp": prepare_trechos(),
            "limite_sp": prepare_limite_sp(),
        },
        "fontes_admin_der": {
            "residencias_conserva_poligonos": (
                str(RESIDENCIAS_ZIP.relative_to(ROOT))
                if RESIDENCIAS_ZIP.exists() else None
            ),
        },
        "pendentes": {
            "mapbiomas": "baixar/preparar vegetacao_inpe.tif",
            "dem": "baixar/preparar altitude_sp.tif",
        },
    }
    BASE_META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Metadata: {BASE_META}")


if __name__ == "__main__":
    main()
