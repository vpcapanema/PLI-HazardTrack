"""
Gera shapefile das 4 regioes PLI a partir dos poligonos aproximados.

Este e um placeholder ate que o shapefile oficial das UTBs/Setores de Risco
(contratos DER 20.088-8 e 20.292-7, IG 2020) seja incorporado.

Para substituir pelo shapefile oficial:
1. Colocar os arquivos .shp, .shx, .dbf, .prj em data/regioes_pli/
2. O regions.py carrega automaticamente se o diretorio existir
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import geopandas as gpd
from shapely.geometry import Polygon
from core.regions import APPROXIMATE_REGIONS

OUTPUT_DIR = ROOT / "data" / "regioes_pli"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    records = []
    for region in APPROXIMATE_REGIONS:
        poly = Polygon(region["polygon"])
        records.append({
            "id": region["id"],
            "nome": region["nome"],
            "rodovia": region["rodovia"],
            "k_geo": region["k_geo"],
            "cpc_b0": region["cpc_breaks"][0],
            "cpc_b1": region["cpc_breaks"][1],
            "cpc_b2": region["cpc_breaks"][2],
            "cpc_b3": region["cpc_breaks"][3],
            "hid_b0": region["hid24h_breaks"][0],
            "hid_b1": region["hid24h_breaks"][1],
            "hid_b2": region["hid24h_breaks"][2],
            "hid_b3": region["hid24h_breaks"][3],
            "geometry": poly,
        })

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    out_path = OUTPUT_DIR / "regioes_pli.shp"
    gdf.to_file(out_path)
    print(f"Shapefile gerado: {out_path}")
    print(f"Regioes: {len(gdf)}")


if __name__ == "__main__":
    main()
