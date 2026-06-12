"""Exporta ua_zones unificado em ua_geo.geojson e ua_hidro.geojson."""
import sys
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
IN_UNIFIED = ROOT / "data" / "ua_zones" / "ua_zones.geojson"
IN_POLYGONS = ROOT / "data" / "ua_polygons" / "ua_polygons.geojson"
OUT_DIR = ROOT / "data" / "ua_zones"
OUT_GEO = OUT_DIR / "ua_geo.geojson"
OUT_HIDRO = OUT_DIR / "ua_hidro.geojson"

BASE_COLS = [
    "id", "regiao", "rodovia", "municipio", "km", "km_ini", "km_fim",
    "escala", "extensao_m", "ext_oficial_media_m", "divisa_ini", "fonte",
]

GEO_DROP = [
    "ra_hid", "ra_hid_leitura", "ra_hid_conf", "ra_hid_fonte",
    "ra_geo", "ra_geo_leitura", "ra_geo_conf", "ra_geo_fonte",
]
HIDRO_DROP = [
    "ra_geo", "ra_geo_leitura", "ra_geo_conf", "ra_geo_fonte",
    "ra_hid", "ra_hid_leitura", "ra_hid_conf", "ra_hid_fonte",
]


def _prep(gdf, hazard: str) -> gpd.GeoDataFrame:
    g = gdf.sort_values("id").copy()
    if hazard == "geo":
        g["hazard"] = "geo"
        g["ra"] = g["ra_geo"]
        g["ra_leitura"] = g.get("ra_geo_leitura")
        g["ra_conf"] = g.get("ra_geo_conf")
        g["ra_fonte"] = g.get("ra_geo_fonte")
        drop = [c for c in GEO_DROP if c in g.columns]
    else:
        g["hazard"] = "hidro"
        g["ra"] = g["ra_hid"]
        g["ra_leitura"] = g.get("ra_hid_leitura")
        g["ra_conf"] = g.get("ra_hid_conf")
        g["ra_fonte"] = g.get("ra_hid_fonte")
        drop = [c for c in HIDRO_DROP if c in g.columns]
    keep = BASE_COLS + ["hazard", "ra", "ra_leitura", "ra_conf", "ra_fonte"]
    keep = [c for c in keep if c in g.columns]
    g = g[keep + ["geometry"]]
    return g.drop(columns=drop, errors="ignore")


def export_split(gdf: gpd.GeoDataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _prep(gdf, "geo").to_file(OUT_GEO, driver="GeoJSON")
    _prep(gdf, "hidro").to_file(OUT_HIDRO, driver="GeoJSON")
    print(f"Salvo: {OUT_GEO} ({len(gdf)} UAs encosta)")
    print(f"Salvo: {OUT_HIDRO} ({len(gdf)} UAs hidro)")


def main():
    src = IN_UNIFIED if IN_UNIFIED.exists() else IN_POLYGONS
    if not src.exists():
        print(f"Fonte nao encontrada: {src}")
        sys.exit(1)
    gdf = gpd.read_file(src)
    export_split(gdf)


if __name__ == "__main__":
    main()
