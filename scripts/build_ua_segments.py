"""
Gera segmentos de rodovia com RA oficial a partir da malha DER/SP.

Como os shapefiles das 809 UAs nao estao disponiveis (Google Drive do
Anexo B inacessivel), esta solucao alternativa:

1. Carrega a malha DER/SP oficial (LineString por trecho)
2. Corta a malha nos trechos com RA oficial (km ini/fim dos relatorios)
3. Para cada segmento, associa RA geo/hid + ICC da regiao
4. Gera GeoJSON com todos os segmentos (com e sem RA)

Politica:
- Trechos com RA oficial: segmento com ra_geo/ra_hid reais
- Trechos sem RA: segmento mantido mas marcado como SEM_DADO
- Nunca inventar RA para segmentos nao mapeados
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import geopandas as gpd
import json

# Malha DER/SP oficial (ja em WGS84)
DER_SHP = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
OUTPUT_GEOJSON = ROOT / "data" / "ua_segments" / "ua_segments_ra.geojson"

# Trechos com RA oficial (do core/ra_official.py)
RA_SEGMENTS = [
    # (rodovia, km_ini, km_fim, ra_geo, ra_hid, regiao, uba, desc)
    ("SP 055", 53.6, 102.0, 1, 0, 2, "UBA 06.04-CGT",
     "Caraguatatuba-Ubatuba"),
    ("SP 055", 114.0, 127.8, 1, 1, 3, "UBA 06.04-CGT",
     "Sao Sebastiao (norte)"),
    ("SP 055", 128.0, 153.0, 4, 2, 3, "UBA 05.04-SVC",
     "Sao Sebastiao (critico)"),
    ("SP 055", 156.0, 162.0, 4, 2, 3, "UBA 05.04-SVC",
     "Sao Sebastiao (km 156-162)"),
    ("SP 055", 178.1, 191.4, 4, 1, 3, "UBA 05.04-SVC",
     "Sao Sebastiao (hidro)"),
    ("SP 055", 191.4, 223.6, 1, 0, 4, "UBA 05.04-SVC",
     "Santos-Bertioga"),
    ("SP 055", 235.0, 238.0, 1, 0, 4, "UBA 05.04-SVC",
     "Santos-Bertioga (km 235-238)"),
    ("SP 055", 93.0, 93.0, 1, 0, 2, "UBA 06.04-CGT",
     "Caraguatatuba-Ubatuba (hidro, km 93)"),
    ("SP 055", 97.0, 97.0, 1, 1, 2, "UBA 06.04-CGT",
     "Caraguatatuba-Ubatuba (hidro, km 97)"),
    ("SP 055", 112.0, 112.0, 1, 1, 2, "UBA 06.04-CGT",
     "Caraguatatuba-Ubatuba (hidro, km 112)"),
    ("SP 098", 77.0, 98.0, 1, 1, 1, "UBA 10.04-MCZ",
     "Mogi-Bertioga"),
]


def main():
    if not DER_SHP.exists():
        print(f"Shapefile nao encontrado: {DER_SHP}")
        print("Execute scripts/process_der_shapefile.py primeiro")
        return

    gdf = gpd.read_file(DER_SHP)
    print(f"Malha DER/SP carregada: {len(gdf)} trechos")
    print(f"CRS: {gdf.crs}")

    # Converte para WGS84 se necessario
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
        print(f"Convertido para WGS84")

    segments = []
    seg_id = 0

    for _, row in gdf.iterrows():
        rodovia = row.get("Rodovia", "").strip().upper()
        km_ini = row.get("KmInicial")
        km_fim = row.get("KmFinal")

        # Filtra apenas rodovias monitoradas
        if rodovia not in ("SP 055", "SP 098"):
            continue

        # Verifica se este trecho intersecta algum trecho com RA
        matched = False
        for (ra_rod, ra_km0, ra_km1, ra_geo, ra_hid,
             regiao, uba, desc) in RA_SEGMENTS:
            if rodovia == ra_rod:
                # Verifica overlap de km
                # Trecho da malha: [km_ini, km_fim]
                # Trecho com RA: [ra_km0, ra_km1]
                overlap_start = max(km_ini or 0, ra_km0)
                overlap_end = min(km_fim or 9999, ra_km1)
                if overlap_start < overlap_end:
                    # Ha overlap - este trecho tem RA
                    segments.append({
                        "type": "Feature",
                        "properties": {
                            "id": f"SEG-{seg_id:04d}",
                            "rodovia": rodovia,
                            "km_ini": km_ini,
                            "km_fim": km_fim,
                            "ra_geo": ra_geo,
                            "ra_hid": ra_hid,
                            "ra": max(ra_geo, ra_hid),
                            "regiao": regiao,
                            "uba": uba,
                            "desc": desc,
                            "source": "regea2021",
                        },
                        "geometry": row.geometry.__geo_interface__,
                    })
                    matched = True
                    seg_id += 1
                    break

        if not matched:
            # Trecho sem RA oficial
            segments.append({
                "type": "Feature",
                "properties": {
                    "id": f"SEG-{seg_id:04d}",
                    "rodovia": rodovia,
                    "km_ini": km_ini,
                    "km_fim": km_fim,
                    "ra_geo": None,
                    "ra_hid": None,
                    "ra": None,
                    "regiao": None,
                    "uba": None,
                    "desc": "SEM_DADO",
                    "source": "SEM_DADO",
                },
                "geometry": row.geometry.__geo_interface__,
            })
            seg_id += 1

    # Salva como GeoJSON
    OUTPUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    gdf_out = gpd.GeoDataFrame.from_features(segments, crs="EPSG:4326")
    gdf_out.to_file(OUTPUT_GEOJSON, driver="GeoJSON")

    # Estatisticas
    com_ra = sum(1 for s in segments
                 if s["properties"]["source"] == "regea2021")
    sem_ra = sum(1 for s in segments
                  if s["properties"]["source"] == "SEM_DADO")
    print(f"\nSegmentos gerados: {len(segments)}")
    print(f"  Com RA oficial: {com_ra}")
    print(f"  SEM_DADO: {sem_ra}")
    print(f"GeoJSON salvo: {OUTPUT_GEOJSON}")

    # Tambem salva CSV para referencia
    csv_path = ROOT / "data" / "ua_segments" / "ua_segments_ra.csv"
    cols = ["id", "rodovia", "km_ini", "km_fim", "ra_geo",
            "ra_hid", "ra", "regiao", "uba", "desc", "source"]
    gdf_out[cols].to_csv(csv_path, index=False)
    print(f"CSV salvo: {csv_path}")


if __name__ == "__main__":
    main()
