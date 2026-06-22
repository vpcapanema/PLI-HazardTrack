"""Exporta produtos publicos do modulo de queimadas para static/data."""

from __future__ import annotations

import json

from common import (
    LATEST_GEOJSON,
    LATEST_JSON,
    LATEST_STATS,
    RISK_GPKG,
    ensure_dirs,
    parse_date_arg,
    pipeline_status_path,
    read_json,
    write_json,
)


def _horizon_slug(value: str) -> str:
    return value.replace("+", "").replace(" ", "_").lower()


def _geojson_for(gdf):
    geojson = json.loads(gdf.to_json())
    return geojson


def main() -> None:
    ensure_dirs()
    ref_date = parse_date_arg("Exporta camada publica de queimadas.")
    if not RISK_GPKG.exists():
        raise FileNotFoundError(
            f"Produto processado ausente: {RISK_GPKG}. Rode 06 antes."
        )

    import geopandas as gpd

    gdf = gpd.read_file(RISK_GPKG, layer="risco_diario").to_crs("EPSG:4326")
    horizontes = sorted(gdf["horizonte"].dropna().astype(str).unique())
    if "observado" in set(horizontes):
        gdf_web = gdf[gdf["horizonte"] == "observado"].copy()
    else:
        gdf_web = gdf.copy()
    gdf_web["geometry"] = gdf_web["geometry"].simplify(
        0.0005, preserve_topology=True,
    )

    geojson = _geojson_for(gdf_web)
    counts = (
        gdf_web["rf_classe"].fillna("SEM_DADO").value_counts().to_dict()
        if "rf_classe" in gdf_web else {}
    )
    metadata = {
        "modulo": "queimadas",
        "metodologia": "INPE-RF-v11",
        "data_referencia": ref_date.isoformat(),
        "data_status": (
            "no_data" if counts.get("SEM_DADO", 0) == len(gdf_web) else "ok"
        ),
        "horizontes_disponiveis": horizontes or ["observado"],
        "horizonte_publicado": "observado",
        "total_trechos": int(len(gdf_web)),
        "classes": {str(k): int(v) for k, v in counts.items()},
        "source": str(RISK_GPKG),
    }
    geojson["metadata"] = metadata

    LATEST_GEOJSON.write_text(
        json.dumps(geojson, ensure_ascii=False),
        encoding="utf-8",
    )

    horizon_files = {}
    for horizonte in horizontes:
        sub = gdf[gdf["horizonte"].astype(str) == horizonte].copy()
        sub["geometry"] = sub["geometry"].simplify(
            0.0005, preserve_topology=True,
        )
        sub_geojson = _geojson_for(sub)
        sub_meta = {
            **metadata,
            "horizonte_publicado": horizonte,
            "total_trechos": int(len(sub)),
            "classes": {
                str(k): int(v)
                for k, v in sub["rf_classe"].fillna("SEM_DADO")
                .value_counts().to_dict().items()
            },
        }
        sub_geojson["metadata"] = sub_meta
        path = LATEST_GEOJSON.parent / (
            f"risco_trechos_der_{_horizon_slug(horizonte)}.geojson"
        )
        path.write_text(
            json.dumps(sub_geojson, ensure_ascii=False),
            encoding="utf-8",
        )
        horizon_files[horizonte] = str(path)

    snapshot = {
        **metadata,
        "trechos": [
            {
                key: row.get(key)
                for key in (
                    "trecho_id", "rodovia", "km_ini", "km_fim",
                    "municipio", "regional", "sede_regional",
                    "residencia", "residencia_dr", "uba_codigo",
                    "uba_nome", "jurisdicao", "conservado",
                    "conservado_por", "rf_valor", "rf_classe",
                    "horizonte", "data_status",
                )
            }
            for row in gdf_web.drop(columns="geometry").to_dict("records")
        ],
        "horizon_files": horizon_files,
    }
    write_json(LATEST_JSON, snapshot)
    write_json(LATEST_STATS, metadata)

    status = {
        "modulo": "queimadas",
        "step": "07_export_public_layers",
        "data_referencia": ref_date.isoformat(),
        "status": metadata["data_status"],
        "outputs": [str(LATEST_GEOJSON), str(LATEST_JSON), str(LATEST_STATS)],
    }
    # Preserva informacao de passos anteriores caso exista.
    prior = read_json(pipeline_status_path("aggregate", ref_date), {})
    if prior:
        status["aggregate"] = prior
    write_json(pipeline_status_path("export_public", ref_date), status)
    print(f"Exportado: {LATEST_GEOJSON}")


if __name__ == "__main__":
    main()
