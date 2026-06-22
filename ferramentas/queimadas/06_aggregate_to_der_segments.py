"""Agrega RF oficial INPE para trechos rodoviarios DER-SP."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from shapely.geometry import LineString, MultiLineString

from common import INTERIM_DIR, MONITORED_ROAD_LAYER, RISK_GPKG
from common import ensure_dirs, load_trechos
from common import now_iso, parse_date_arg, pipeline_status_path, read_json
from common import rf_class, sem_dado_fields, write_json


def _line_parts(geom) -> List[LineString]:
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return []


def _sample_points(geom, n: int = 7) -> List[Tuple[float, float]]:
    parts = _line_parts(geom)
    if not parts:
        c = geom.representative_point()
        return [(float(c.x), float(c.y))]
    line = max(parts, key=lambda g: g.length)
    if line.length == 0:
        c = line.centroid
        return [(float(c.x), float(c.y))]
    pts = []
    for i in range(n):
        frac = i / max(1, n - 1)
        p = line.interpolate(frac, normalized=True)
        pts.append((float(p.x), float(p.y)))
    return pts


def _valid_rf(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    # INPE usa valores 0..1. Alguns rasters podem trazer nodata negativos
    # ou codigos acima de 1; descarta apenas valores claramente invalidos.
    if v < 0 or v > 5:
        return None
    return min(v, 1.0)


def _open_raster(path: Path):
    import rasterio

    src = rasterio.open(path)
    if src.subdatasets:
        first = src.subdatasets[0]
        src.close()
        return rasterio.open(first)
    return src


def _sample_from_src(src, coords: Iterable[Tuple[float, float]]):
    from rasterio.warp import transform

    coords_list = list(coords)
    if src.crs and src.crs.to_string() not in ("EPSG:4326", "OGC:CRS84"):
        xs, ys = zip(*coords_list)
        tx, ty = transform("EPSG:4326", src.crs, xs, ys)
        coords_list = list(zip(tx, ty))
    vals = []
    for arr in src.sample(coords_list):
        if len(arr):
            v = _valid_rf(arr[0])
            if v is not None:
                vals.append(v)
    if not vals:
        return None, None, None
    vals.sort()
    p90_idx = min(len(vals) - 1, int(round((len(vals) - 1) * 0.9)))
    return max(vals), vals[p90_idx], sum(vals) / len(vals)


def main() -> None:
    ensure_dirs()
    ref_date = parse_date_arg("Agrega RF para trechos DER-SP.")
    trechos = load_trechos()
    grid_status = INTERIM_DIR / "rf_inpe" / f"{ref_date:%Y%m%d}" / "rf_index.json"
    grid = read_json(grid_status, {})

    products = [
        p for p in grid.get("grid_products", [])
        if p.get("horizonte") in {"observado", "D+1", "D+2", "D+3"}
    ]
    rows = []
    if not products:
        fields = sem_dado_fields(ref_date)
        for key, value in fields.items():
            trechos[key] = value
        rows = [trechos]
    else:
        points_by_idx = {
            idx: _sample_points(geom)
            for idx, geom in trechos.geometry.items()
        }
        for product in products:
            path = Path(product["path"])
            horizonte = product["horizonte"]
            gdf = trechos.copy()
            values = []
            p90s = []
            means = []
            classes = []
            with _open_raster(path) as src:
                for idx, coords in points_by_idx.items():
                    rf_max, rf_p90, rf_mean = _sample_from_src(src, coords)
                    values.append(rf_max)
                    p90s.append(rf_p90)
                    means.append(rf_mean)
                    classes.append(rf_class(rf_max))
            gdf["data_referencia"] = ref_date.isoformat()
            gdf["horizonte"] = horizonte
            gdf["data_alvo"] = ref_date.isoformat()
            gdf["rf_valor"] = values
            gdf["rf_classe"] = classes
            gdf["rf_p90"] = p90s
            gdf["rf_media"] = means
            gdf["metodologia"] = "INPE-RF-v11"
            gdf["fonte_precipitacao"] = "INPE_RF_OFICIAL"
            gdf["fonte_meteo"] = "INPE_RF_OFICIAL"
            gdf["focos_correcao"] = None
            gdf["data_status"] = [
                "ok" if v is not None else "no_data" for v in values
            ]
            gdf["gerado_em"] = now_iso()
            rows.append(gdf)

    import pandas as pd

    import geopandas as gpd

    out = gpd.GeoDataFrame(pd.concat(rows, ignore_index=True), crs=trechos.crs)

    RISK_GPKG.unlink(missing_ok=True)
    out.to_file(RISK_GPKG, layer="risco_diario", driver="GPKG")
    if "observado" in set(out["horizonte"].astype(str)):
        monitored = out[out["horizonte"].astype(str) == "observado"].copy()
    else:
        first_horizon = str(out["horizonte"].iloc[0])
        monitored = out[out["horizonte"].astype(str) == first_horizon].copy()
    monitored.to_file(RISK_GPKG, layer=MONITORED_ROAD_LAYER, driver="GPKG")

    status = {
        "modulo": "queimadas",
        "step": "06_aggregate_to_der_segments",
        "data_referencia": ref_date.isoformat(),
        "status": "ok" if products else "no_data",
        "source_grid": str(grid_status),
        "output": str(RISK_GPKG),
        "output_layer": "risco_diario",
        "monitored_layer": MONITORED_ROAD_LAYER,
        "features": int(len(out)),
        "monitored_features": int(len(monitored)),
        "horizontes": [p.get("horizonte") for p in products] or ["observado"],
        "message": "Produto por trecho gerado com RF oficial INPE.",
    }
    write_json(pipeline_status_path("aggregate", ref_date), status)
    print(status["message"])


if __name__ == "__main__":
    main()
