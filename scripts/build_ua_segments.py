"""
Gera segmentos de rodovia com RA oficial a partir da malha DER/SP.

Como os shapefiles das 809 UAs nao estao disponiveis (o detalhamento
georreferenciado por UA esta no relatorio Etapa 1 / 2053-R02-20, Anexo B,
inacessivel), esta solucao corta a malha DER/SP nos TRECHOS criticos com RA
oficial e anexa a DISTRIBUICAO completa de RA por classe.

Fonte unica da verdade: core/ra_official.py
  - RA_GEO_BY_SEGMENT (Tabela 3.3.3.1-3 do Produto 7 / 2053-R04-21)
  - RA_HID_BY_SEGMENT (Tabela 3.3.3.1-4)

Politica (decisao: "distribuicao completa, motor decide por classe"):
- Trecho com RA oficial: grava dist_geo/dist_hid (JSON) + ra_geo_max/ra_hid_max
  (maior classe presente, usada para alerta de pior caso).
- Trecho sem RA: mantido como SEM_DADO. Nunca inventar RA.

Granularidade: TRECHO (km), nao UA individual. O GeoJSON e usado para o mapa;
a fonte canonica do motor de risco e o lookup por km em core/ra_official.py.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import geopandas as gpd  # noqa: E402  # pylint: disable=wrong-import-position

from core.ra_official import (  # noqa: E402  # pylint: disable=wrong-import-position
    RA_GEO_BY_SEGMENT,
    RA_HID_BY_SEGMENT,
    _max_class,
)

DER_SHP = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
OUTPUT_GEOJSON = ROOT / "data" / "ua_segments" / "ua_segments_ra.geojson"
MONITORED = ("SP 055", "SP 098")


def _overlap(a0, a1, b0, b1):
    """True se os intervalos [a0,a1] e [b0,b1] se tocam (inclui pontos)."""
    return max(a0, b0) <= min(a1, b1)


def _find_dist(rodovia, km_ini, km_fim, table):
    """Retorna (dist, meta) do trecho oficial que sobrepoe [km_ini,km_fim]."""
    for (r_rod, r_km0, r_km1), data in table.items():
        if r_rod != rodovia:
            continue
        if _overlap(km_ini, km_fim, r_km0, r_km1):
            return data["dist"], data
    return None, None


def main():
    if not DER_SHP.exists():
        print(f"Shapefile nao encontrado: {DER_SHP}")
        print("Execute scripts/process_der_shapefile.py primeiro")
        return

    gdf = gpd.read_file(DER_SHP)
    print(f"Malha DER/SP carregada: {len(gdf)} trechos | CRS: {gdf.crs}")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
        print("Convertido para WGS84")

    segments = []
    seg_id = 0
    com_ra = 0

    for _, row in gdf.iterrows():
        rodovia = (row.get("Rodovia", "") or "").strip().upper()
        if rodovia not in MONITORED:
            continue

        km_ini = row.get("KmInicial")
        km_fim = row.get("KmFinal")
        k0 = float(km_ini) if km_ini is not None else 0.0
        k1 = float(km_fim) if km_fim is not None else 9999.0
        if k1 < k0:
            k0, k1 = k1, k0

        dist_geo, meta_geo = _find_dist(rodovia, k0, k1, RA_GEO_BY_SEGMENT)
        dist_hid, meta_hid = _find_dist(rodovia, k0, k1, RA_HID_BY_SEGMENT)

        if dist_geo is None and dist_hid is None:
            props = {
                "id": f"SEG-{seg_id:04d}",
                "rodovia": rodovia,
                "km_ini": km_ini, "km_fim": km_fim,
                "ra_geo_max": None, "ra_hid_max": None, "ra": None,
                "dist_geo": None, "dist_hid": None,
                "regiao": None, "uba": None,
                "desc": "SEM_DADO", "source": "SEM_DADO",
            }
        else:
            ra_geo_max = _max_class(dist_geo)
            ra_hid_max = _max_class(dist_hid)
            ra = max([v for v in (ra_geo_max, ra_hid_max) if v is not None])
            meta = meta_geo or meta_hid
            props = {
                "id": f"SEG-{seg_id:04d}",
                "rodovia": rodovia,
                "km_ini": km_ini, "km_fim": km_fim,
                "ra_geo_max": ra_geo_max, "ra_hid_max": ra_hid_max, "ra": ra,
                # dist como JSON string (driver GeoJSON nao aceita dict)
                "dist_geo": json.dumps(dist_geo) if dist_geo else None,
                "dist_hid": json.dumps(dist_hid) if dist_hid else None,
                "regiao": meta.get("regiao"),
                "uba": meta.get("uba"),
                "desc": meta.get("desc"),
                "source": "regea2021",
            }
            com_ra += 1

        segments.append({
            "type": "Feature",
            "properties": props,
            "geometry": row.geometry.__geo_interface__,
        })
        seg_id += 1

    OUTPUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    gdf_out = gpd.GeoDataFrame.from_features(segments, crs="EPSG:4326")
    gdf_out.to_file(OUTPUT_GEOJSON, driver="GeoJSON")

    print(f"\nSegmentos gerados: {len(segments)}")
    print(f"  Com RA oficial: {com_ra}")
    print(f"  SEM_DADO: {len(segments) - com_ra}")
    print(f"GeoJSON salvo: {OUTPUT_GEOJSON}")

    cols = ["id", "rodovia", "km_ini", "km_fim", "ra_geo_max", "ra_hid_max",
            "ra", "dist_geo", "dist_hid", "regiao", "uba", "desc", "source"]
    csv_path = ROOT / "data" / "ua_segments" / "ua_segments_ra.csv"
    gdf_out[cols].to_csv(csv_path, index=False)
    print(f"CSV salvo: {csv_path}")


if __name__ == "__main__":
    main()
