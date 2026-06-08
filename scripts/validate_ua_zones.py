"""
Valida as zonas digitalizadas (data/ua_zones/ua_zones.geojson) contra as
distribuicoes oficiais das Tabelas 3.3.3.1-3 (GEO) e 3.3.3.1-4 (HID),
agregadas por regiao.

NOTA HONESTA: as tabelas oficiais cobrem apenas os TRECHOS CRITICOS (faixas
de km especificas), enquanto as figuras mostram o RA ao longo de TODA a
rodovia. Portanto nao se espera coincidencia exata de proporcoes; a validacao
checa (a) a classe dominante e (b) a presenca/peso relativo das classes altas
na regiao correta, e que HID << GEO.
"""
import sys
import collections
from pathlib import Path

import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ra_official import (  # noqa: E402  # pylint: disable=wrong-import-position
    RA_GEO_BY_SEGMENT,
    RA_HID_BY_SEGMENT,
)

GJ = ROOT / 'data' / 'ua_zones' / 'ua_zones.geojson'


def table_by_region(segmap):
    agg = collections.defaultdict(collections.Counter)
    for (_rod, _k0, _k1), d in segmap.items():
        rid = d['regiao']
        for c, n in d['dist'].items():
            agg[rid][c] += n
    return agg


def pct(counter):
    tot = sum(counter.values())
    if not tot:
        return {}
    return {c: round(100 * counter.get(c, 0) / tot, 1) for c in range(5)}


def main():
    gj = gpd.read_file(GJ).to_crs(epsg=31983)
    geo_len = collections.defaultdict(collections.Counter)
    hid_len = collections.defaultdict(collections.Counter)
    for _, row in gj.iterrows():
        rid = int(row['regiao'])
        L = row.geometry.length
        if not pd.isna(row['ra_geo']):
            geo_len[rid][int(row['ra_geo'])] += L
        if not pd.isna(row['ra_hid']):
            hid_len[rid][int(row['ra_hid'])] += L

    tg = table_by_region(RA_GEO_BY_SEGMENT)
    th = table_by_region(RA_HID_BY_SEGMENT)

    for rid in (1, 2, 3, 4):
        print(f"\n===== REGIAO {rid} =====")
        print("  GEO  zonas(%/comprimento):", pct(geo_len[rid]))
        print("  GEO  tabela(%/UA crit.)  :", pct(tg[rid]))
        print("  HID  zonas(%/comprimento):", pct(hid_len[rid]))
        print("  HID  tabela(%/UA crit.)  :", pct(th[rid]))
        # km total por canal
        gtot = sum(geo_len[rid].values()) / 1000
        htot = sum(hid_len[rid].values()) / 1000
        print(f"  cobertura: GEO {gtot:.1f} km | HID {htot:.1f} km")


if __name__ == '__main__':
    main()
