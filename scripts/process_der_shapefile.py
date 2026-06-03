"""
Processa shapefile oficial do DER/SP e extrai geometrias das rodovias monitoradas.

Fonte: https://dadosabertos.sp.gov.br/dataset/sistema-rodoviario-estadual
CRS original: EPSG:5880 (SIRGAS 2000 / UTM zone 23S)
Conversao: EPSG:4326 (WGS84) para compatibilidade com o sistema
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import geopandas as gpd

INPUT_SHP = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
OUTPUT_GEOJSON = ROOT / "data" / "malha_der" / "malha_der_oficial.geojson"


def main():
    if not INPUT_SHP.exists():
        print(f"Shapefile nao encontrado: {INPUT_SHP}")
        return

    gdf = gpd.read_file(INPUT_SHP)
    print(f"Shapefile carregado: {len(gdf)} registros")
    print(f"CRS original: {gdf.crs}")

    # Converte para WGS84 (EPSG:4326)
    gdf_wgs = gdf.to_crs(epsg=4326)
    print(f"CRS convertido: {gdf_wgs.crs}")

    # Filtra rodovias monitoradas pelo sistema
    rodovias_monitoradas = ['SP 055', 'SP 098', 'SP 131', 'SP 150', 'SP 148', 'SP 061', 'SP 066', 'SP 088', 'SP 092', 'SP 102', 'SP 043', 'SP 039', 'SP 099', 'SP 125', 'BR 101']

    # Tambem inclui variacoes com hifen
    filtro = gdf_wgs['Rodovia'].isin(rodovias_monitoradas)
    gdf_filtrado = gdf_wgs[filtro].copy()

    print(f"Rodovias monitoradas encontradas: {len(gdf_filtrado)} registros")
    print(f"Rodovias: {sorted(gdf_filtrado['Rodovia'].unique())}")

    # Salva como GeoJSON
    OUTPUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    gdf_filtrado.to_file(OUTPUT_GEOJSON, driver="GeoJSON")
    print(f"GeoJSON salvo: {OUTPUT_GEOJSON}")

    # Tambem salva CSV com atributos para referencia
    csv_path = ROOT / "data" / "malha_der" / "malha_der_oficial.csv"
    gdf_filtrado.drop(columns=['geometry']).to_csv(csv_path, index=False)
    print(f"CSV salvo: {csv_path}")


if __name__ == "__main__":
    main()
