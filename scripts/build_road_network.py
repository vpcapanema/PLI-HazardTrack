"""
Pre-processa o shapefile da malha rodoviaria DER-SP:
- reprojeta para WGS84 (EPSG:4326)
- simplifica geometrias para reduzir payload web
- mantem so atributos uteis para o mapa
- divide em duas camadas: completa (download) e otimizada (mapa)
"""

from pathlib import Path
import geopandas as gpd
import json

ROOT = Path(__file__).resolve().parent.parent
SHP_IN = ROOT / "data" / "malha_der" / "MALHA_RODOVIARIA.shp"
OUT_DIR = ROOT / "static" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"Lendo {SHP_IN}")
gdf = gpd.read_file(SHP_IN)
print(f"  {len(gdf)} feicoes em CRS {gdf.crs}")

# 1) Reprojeta para WGS84
gdf = gdf.to_crs("EPSG:4326")

# 2) Mantem so as colunas uteis
KEEP = [
    "Rodovia", "TipoRodovi", "Orientacao", "Municipio",
    "CodRegiona", "SedeRegion", "Residencia",
    "KmInicial", "KmFinal", "Extensao",
    "Jurisdicao", "Administra", "Conservado",
    "TipoPista", "Denominaca",
    "geometry"
]
keep_cols = [c for c in KEEP if c in gdf.columns]
gdf = gdf[keep_cols]

# 3) Renomeia para nomes mais claros
gdf = gdf.rename(columns={
    "Rodovia": "rodovia",
    "TipoRodovi": "tipo",
    "Orientacao": "orientacao",
    "Municipio": "municipio",
    "CodRegiona": "regional",
    "SedeRegion": "sede_regional",
    "Residencia": "residencia",
    "KmInicial": "km_ini",
    "KmFinal": "km_fim",
    "Extensao": "extensao",
    "Jurisdicao": "jurisdicao",
    "Administra": "administra",
    "Conservado": "conservado",
    "TipoPista": "tipo_pista",
    "Denominaca": "denominacao"
})

# 4) Drop Z (forca 2D)
from shapely.ops import transform as shp_transform

def _drop_z(geom):
    if geom is None:
        return None
    if hasattr(geom, "has_z") and geom.has_z:
        return shp_transform(lambda x, y, z=None: (x, y), geom)
    return geom

gdf["geometry"] = gdf["geometry"].apply(_drop_z)

# 5) Versao OTIMIZADA para o mapa: simplifica geometria e drop alguns campos pesados
# Tolerancia 0.0005 graus ~ 50m, perfeito para zoom estadual
gdf_opt = gdf.copy()
gdf_opt["geometry"] = gdf_opt["geometry"].simplify(0.0005, preserve_topology=True)

# Para a versao do mapa, mantem so o essencial
MAP_COLS = ["rodovia", "tipo", "municipio", "regional", "residencia",
            "km_ini", "km_fim", "extensao", "jurisdicao", "administra",
            "tipo_pista", "denominacao", "geometry"]
gdf_opt = gdf_opt[[c for c in MAP_COLS if c in gdf_opt.columns]]

# 6) Salva GeoJSON
out_full = OUT_DIR / "malha_der_full.geojson"
out_opt = OUT_DIR / "malha_der.geojson"

print(f"Salvando completo em {out_full}")
gdf.to_file(out_full, driver="GeoJSON")
print(f"  {out_full.stat().st_size / 1024 / 1024:.1f} MB")

print(f"Salvando otimizado em {out_opt}")
gdf_opt.to_file(out_opt, driver="GeoJSON")
print(f"  {out_opt.stat().st_size / 1024 / 1024:.1f} MB")

# 7) Estatisticas para a UI
stats = {
    "total_trechos": len(gdf),
    "extensao_total_km": float(gdf["extensao"].sum()) if "extensao" in gdf else None,
    "rodovias_unicas": gdf["rodovia"].nunique(),
    "tipos_pista": sorted(gdf["tipo_pista"].dropna().unique().tolist()),
    "tipos_rodovia": sorted(gdf["tipo"].dropna().unique().tolist()),
    "regionais": sorted(gdf["regional"].dropna().unique().tolist()),
    "jurisdicoes": sorted(gdf["jurisdicao"].dropna().unique().tolist()),
    "administra": sorted(gdf["administra"].dropna().unique().tolist()),
    "bbox": list(gdf.total_bounds)  # [minx, miny, maxx, maxy]
}
(OUT_DIR / "malha_der_stats.json").write_text(
    json.dumps(stats, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
)
print("\nEstatisticas:")
print(f"  {stats['total_trechos']} trechos")
print(f"  {stats['extensao_total_km']:.0f} km totais")
print(f"  {stats['rodovias_unicas']} rodovias distintas")
print(f"  Tipos de pista: {stats['tipos_pista']}")
print(f"  Bbox: {stats['bbox']}")
