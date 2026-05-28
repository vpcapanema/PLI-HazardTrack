"""
Gera pontos de monitoramento PROVISORIOS amostrados sobre a malha real.

Substitui os 24 pontos hardcoded com lat/lon chutadas (alguns caiam no mar)
por pontos derivados da geometria oficial DER-SP. Estrategia:

  1. Le a malha ja classificada (static/data/malha_der.geojson).
  2. Filtra trechos monitored=True (cobertura das 4 regioes DER-SP).
  3. Para cada trecho, calcula o centroide da geometria.
  4. Salva em core/monitoring_points_data.json (lido pelo monitoring_points.py).

RA = 1 em todos (neutralizado). A unidade real do metodo e a UA, nao um ponto;
ao obter o shape RA por trecho/UA (CPRM + iRAP-DER ou shapefile oficial REGEA),
substituir esta amostragem.
"""
from pathlib import Path
import json
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
GEOJSON_IN = ROOT / "static" / "data" / "malha_der.geojson"
JSON_OUT = ROOT / "core" / "monitoring_points_data.json"

print(f"Lendo {GEOJSON_IN}")
gdf = gpd.read_file(GEOJSON_IN)
print(f"  {len(gdf)} trechos no total")

mon = gdf[gdf["monitored"] == True].copy()
print(f"  {len(mon)} trechos com cobertura do sistema")

points = []
for _, row in mon.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    # Centroide ao longo da linha (interpolate em 50% do comprimento)
    try:
        c = geom.interpolate(0.5, normalized=True)
        lon, lat = c.x, c.y
    except Exception:
        c = geom.centroid
        lon, lat = c.x, c.y

    rod = (row.get("rodovia") or "").strip()
    km_ini = row.get("km_ini")
    km_fim = row.get("km_fim")
    municipio = (row.get("municipio") or "").strip()
    region_id = row.get("region_id")
    region_name = (row.get("region_name") or "").strip()

    # km de referencia (centro do trecho)
    if km_ini is not None and km_fim is not None:
        km_ref = round((float(km_ini) + float(km_fim)) / 2, 1)
    else:
        km_ref = None

    pid = f"{rod.replace(' ', '')}-R{int(region_id) if region_id else 0}-{len(points)+1:03d}"

    points.append({
        "id": pid,
        "rodovia": rod,
        "km": km_ref,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "ra": 1,                        # neutralizado ate vir RA oficial / proxy
        "nome": f"{municipio} · {rod} km {km_ref}" if km_ref else f"{municipio} · {rod}",
        "region_id_hint": int(region_id) if region_id else None,
        "region_name_hint": region_name or None,
    })

print(f"  {len(points)} pontos gerados sobre a geometria real")

JSON_OUT.write_text(
    json.dumps(points, ensure_ascii=False, indent=2),
    encoding="utf-8"
)
print(f"  -> {JSON_OUT.name}")

# Distribuicao por regiao
by_region = {}
for p in points:
    r = p["region_name_hint"] or "—"
    by_region[r] = by_region.get(r, 0) + 1
print("\nDistribuicao por regiao:")
for r, n in sorted(by_region.items(), key=lambda kv: -kv[1]):
    print(f"  {r}: {n}")
