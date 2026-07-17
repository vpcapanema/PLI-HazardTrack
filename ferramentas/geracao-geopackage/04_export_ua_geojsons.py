"""
Exporta a camada `uas_area_estudo` do GeoPackage em DOIS GeoJSONs
mono-canal consumidos pelo sistema:

  data/ua_zones/ua_geo.geojson    - encosta (RAGEO + flag GEO + ICC GEO)
  data/ua_zones/ua_hidro.geojson  - inundacao (RAHID + flag HID + ICC HID)

Politica: SEM normalizacao de nomes. Cada feature carrega EXATAMENTE
os mesmos atributos da camada-mae (uas_area_estudo) menos os do canal
oposto, MAIS um atributo `hazard` = "geo" | "hidro". O backend e o
frontend consomem direto esses nomes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd

_reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(_reconfigure_stdout):
    _reconfigure_stdout(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
GPKG = ROOT / "data" / "pli-hazardtrack.gpkg"
LAYER = "uas_area_estudo"
OUT_DIR = ROOT / "data" / "ua_zones"
OUT_GEO = OUT_DIR / "ua_geo.geojson"
OUT_HIDRO = OUT_DIR / "ua_hidro.geojson"

# Colunas exclusivas de cada canal, removidas no GeoJSON do outro canal
GEO_ONLY = ("RAGEO", "icc_geo_thresholds", "trecho_critico_geo")
HID_ONLY = ("RAHID", "icc_hid_thresholds", "trecho_critico_hid")


def _prep(gdf: gpd.GeoDataFrame, hazard: str) -> gpd.GeoDataFrame:
    g = gdf.copy()
    g["hazard"] = hazard
    drop = HID_ONLY if hazard == "geo" else GEO_ONLY
    g = g.drop(columns=[c for c in drop if c in g.columns],
               errors="ignore")
    # Garante a ordem estavel das features para uso determinístico
    g = g.sort_values("ua_id").reset_index(drop=True)
    return g


def main() -> None:
    print("=" * 70)
    print("EXPORTACAO uas_area_estudo -> ua_geo.geojson + ua_hidro.geojson")
    print("=" * 70)
    if not GPKG.exists():
        print(f"ERRO: GPKG nao encontrado: {GPKG}")
        sys.exit(1)

    gdf = gpd.read_file(GPKG, layer=LAYER)
    print(f"  {LAYER}: {len(gdf)} features (CRS {gdf.crs})")

    if gdf.crs is None or str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs(4326)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Remove qualquer GeoJSON pre-existente para evitar mistura de schema
    for out in (OUT_GEO, OUT_HIDRO):
        if out.exists():
            out.unlink()

    ggeo = _prep(gdf, "geo")
    ghid = _prep(gdf, "hidro")
    ggeo.to_file(OUT_GEO, driver="GeoJSON")
    ghid.to_file(OUT_HIDRO, driver="GeoJSON")

    print("\n  Salvos:")
    print(f"    {OUT_GEO.relative_to(ROOT)} - "
          f"{len(ggeo)} features, {len(ggeo.columns)} atributos")
    print(f"    {OUT_HIDRO.relative_to(ROOT)} - "
          f"{len(ghid)} features, {len(ghid.columns)} atributos")
    print(f"\n  Atributos geo:   {sorted(c for c in ggeo.columns if c != 'geometry')}")
    print(f"\n  Atributos hidro: {sorted(c for c in ghid.columns if c != 'geometry')}")
    print()
    print(f"  RAGEO por classe: "
          f"{ggeo['RAGEO'].value_counts().sort_index().to_dict()}")
    print(f"  RAHID por classe: "
          f"{ghid['RAHID'].value_counts().sort_index().to_dict()}")


if __name__ == "__main__":
    main()
