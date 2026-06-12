"""
Pre-processa o shapefile da malha rodoviaria DER-SP:
- reprojeta para WGS84 (EPSG:4326)
- simplifica geometrias para reduzir payload web
- mantem so atributos uteis para o mapa
- divide em duas camadas: completa (download) e otimizada (mapa)
- CLASSIFICA cada trecho quanto a cobertura do sistema:
    monitored: bool
    region_id: int|None  (1..4)
    region_name: str|None
    hazards: lista (encosta + inundacao para trechos cobertos)
"""

from pathlib import Path
import sys
import geopandas as gpd
import json

# Permite importar core/regions.py (precisa rodar do projeto)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.regions import load_regions  # noqa: E402

SHP_IN = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
OUT_DIR = ROOT / "static" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Hazards cobertos pelo metodo REGEA-NIPPON 2021. Em todo trecho monitorado.
# Quando vier shapefile RA por tipo, isto vira uma lista variavel por feature.
DEFAULT_HAZARDS = ["instabilidade_encosta", "inundacao"]

def fix_text(value):
    """Re-export local para scripts de preparacao."""
    from core.text_encoding import fix_text as _fix
    return _fix(value)


def _save_geojson_utf8(gdf, path: Path):
    """Salva GeoJSON em UTF-8 (evita mojibake no Windows)."""
    import json
    from shapely.geometry import mapping

    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        props = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            val = row[col]
            if val is None:
                props[col] = None
                continue
            try:
                import pandas as pd
                if pd.isna(val):
                    props[col] = None
                    continue
            except Exception:
                pass
            if isinstance(val, str):
                val = fix_text(val)
            elif hasattr(val, "item"):
                try:
                    val = val.item()
                except Exception:
                    pass
            props[col] = val
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": mapping(geom),
        })
    path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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

# 4.5) CLASSIFICA cada trecho quanto a cobertura do sistema
print("Classificando trechos por cobertura do sistema...")
regions = load_regions()
print(f"  {len(regions)} regioes carregadas")

from shapely.geometry import shape  # noqa: E402

def _polygon_to_shapely(coords_lat_lon):
    """Converte lista [(lat, lon), ...] em Polygon shapely (lon, lat)."""
    from shapely.geometry import Polygon
    return Polygon([(lon, lat) for lat, lon in coords_lat_lon])

region_polys = {r.id: (_polygon_to_shapely(r.polygon), r) for r in regions}

def _classify(geom):
    """Para um trecho (LineString/MultiLineString), retorna a primeira regiao
    DER-SP que ele intersecta. Trecho que toca varias regioes pega a 1a."""
    if geom is None or geom.is_empty:
        return None, None
    for rid, (poly, r) in region_polys.items():
        try:
            if geom.intersects(poly):
                return rid, r.nome
        except Exception:
            continue
    return None, None

monitored_count = 0
region_distribution = {}
gdf["region_id"] = None
gdf["region_name"] = None
gdf["monitored"] = False
gdf["hazards"] = None  # vira list por feature

for idx, geom in gdf["geometry"].items():
    rid, rname = _classify(geom)
    if rid is not None:
        gdf.at[idx, "region_id"] = int(rid)
        gdf.at[idx, "region_name"] = fix_text(rname)
        gdf.at[idx, "monitored"] = True
        gdf.at[idx, "hazards"] = list(DEFAULT_HAZARDS)
        monitored_count += 1
        region_distribution[rname] = region_distribution.get(rname, 0) + 1
    else:
        gdf.at[idx, "hazards"] = []

print(f"  {monitored_count}/{len(gdf)} trechos cobertos pelo sistema")
for nome, qtd in sorted(region_distribution.items(), key=lambda kv: -kv[1]):
    print(f"    {nome}: {qtd}")

# Forca region_id como inteiro nativo (driver GeoJSON serializa tipo correto)
gdf["region_id"] = gdf["region_id"].astype("Int32")
gdf["monitored"] = gdf["monitored"].astype(bool)

# 5) Versao OTIMIZADA para o mapa: simplifica geometria e drop alguns campos pesados
# Tolerancia 0.0005 graus ~ 50m, perfeito para zoom estadual
gdf_opt = gdf.copy()
gdf_opt["geometry"] = gdf_opt["geometry"].simplify(0.0005, preserve_topology=True)

# Para a versao do mapa, mantem so o essencial
MAP_COLS = ["rodovia", "tipo", "municipio", "regional", "residencia",
            "km_ini", "km_fim", "extensao", "jurisdicao", "administra",
            "tipo_pista", "denominacao",
            # CAMADA DE COBERTURA (novos):
            "monitored", "region_id", "region_name", "hazards",
            "geometry"]
gdf_opt = gdf_opt[[c for c in MAP_COLS if c in gdf_opt.columns]]

# 6) Salva GeoJSON
out_full = OUT_DIR / "malha_der_full.geojson"
out_opt = OUT_DIR / "malha_der.geojson"

print(f"Salvando completo em {out_full}")
_save_geojson_utf8(gdf, out_full)
print(f"  {out_full.stat().st_size / 1024 / 1024:.1f} MB")

print(f"Salvando otimizado em {out_opt}")
_save_geojson_utf8(gdf_opt, out_opt)
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
    "bbox": list(gdf.total_bounds),
    # Cobertura PLI-HazardTrack:
    "monitored_count": int(gdf["monitored"].sum()),
    "monitored_km": float(gdf.loc[gdf["monitored"], "extensao"].sum())
                    if "extensao" in gdf else None,
    "monitored_by_region": region_distribution,
    "hazards_default": DEFAULT_HAZARDS,
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
