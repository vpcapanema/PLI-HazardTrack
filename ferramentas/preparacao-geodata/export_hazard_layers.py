"""
Exporta as camadas de hazard (instabilidade de encosta e inundacao)
como shapefiles separados com todos os atributos.

Uso:
  python scripts/export_hazard_layers.py
  
Output:
  data/export/
    ├── instabilidade_encosta.shp
    ├── inundacao.shp
    └── ambos_hazards.shp (trechos com os dois hazards)
"""

from pathlib import Path
import sys
import geopandas as gpd
from typing import Any, cast

# Permite importar core/regions.py
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.regions import load_regions  # noqa: E402

SHP_IN = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
OUT_DIR = ROOT / "data" / "export"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Columns padrão para manter
KEEP = [
    "Rodovia", "TipoRodovi", "Orientacao", "Municipio",
    "CodRegiona", "SedeRegion", "Residencia",
    "KmInicial", "KmFinal", "Extensao",
    "Jurisdicao", "Administra", "Conservado",
    "TipoPista", "Denominaca",
    "geometry"
]

# Mapping de renomeação
RENAME_MAP = {
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
}

# Default hazards
DEFAULT_HAZARDS = ["instabilidade_encosta", "inundacao"]


def _drop_z(geom):
    """Remove coordenada Z da geometria para garantir 2D."""
    if geom is None:
        return None
    if hasattr(geom, "has_z") and geom.has_z:
        from shapely.ops import transform as shp_transform
        return shp_transform(lambda x, y, z=None: (x, y), geom)
    return geom


def _classify_region(geom):
    """
    Classifica um ponto/geometria em uma das 4 regioes (1..4) ou None.
    Usa a centroides da geometria para determinar a região.
    """
    regions = load_regions()
    if geom is None:
        return None, None
    
    # Usa o centroide para classificar
    centroid = geom.centroid if hasattr(geom, 'centroid') else geom
    lat, lon = centroid.y, centroid.x
    
    for region in regions:
        if region.contains(lat, lon):
            return region.id, region.nome
    
    return None, None


def process_shapefile():
    """Processa o shapefile e classifica cada trecho."""
    print(f"\n📖 Lendo shapefile: {SHP_IN}")
    gdf = gpd.read_file(SHP_IN)
    print(f"   {len(gdf)} features em CRS {gdf.crs}")

    # Reprojeta para WGS84
    gdf = gdf.to_crs("EPSG:4326")
    print("   Reprojetado para EPSG:4326 (WGS84)")

    # Mantém só colunas úteis
    keep_cols = [c for c in KEEP if c in gdf.columns]
    gdf = gdf[keep_cols]

    # Renomeia colunas
    rename_dict = {k: v for k, v in RENAME_MAP.items() if k in gdf.columns}
    gdf = gdf.rename(columns=rename_dict)

    # Remove coordenada Z
    gdf["geometry"] = gdf["geometry"].apply(_drop_z)

    # Classifica cada trecho em região
    print("\n🗺️  Classificando trechos por região...")
    gdf["region_id"] = None
    gdf["region_name"] = None
    gdf["monitored"] = False
    gdf["hazards"] = None

    for idx, geom in gdf["geometry"].items():
        region_id, region_name = _classify_region(geom)
        if region_id is not None:
            gdf.at[idx, "region_id"] = int(region_id)
            gdf.at[idx, "region_name"] = region_name
            gdf.at[idx, "monitored"] = True
            gdf.at[idx, "hazards"] = cast(Any, DEFAULT_HAZARDS)
    
    monitored = gdf[gdf["monitored"]].shape[0]
    print(f"   {monitored}/{len(gdf)} trechos monitorados")

    return gdf


def export_by_hazard(gdf):
    """Exporta camadas separadas por tipo de hazard."""
    
    # Filtra trechos com cada hazard
    gdf["has_encosta"] = gdf["hazards"].apply(
        lambda h: h is not None and "instabilidade_encosta" in h
    )
    gdf["has_inundacao"] = gdf["hazards"].apply(
        lambda h: h is not None and "inundacao" in h
    )

    encosta = gdf[gdf["has_encosta"]].drop(columns=["has_encosta", "has_inundacao"])
    inundacao = gdf[gdf["has_inundacao"]].drop(columns=["has_encosta", "has_inundacao"])
    ambos = gdf[gdf["has_encosta"] & gdf["has_inundacao"]].drop(
        columns=["has_encosta", "has_inundacao"]
    )

    # Exporta
    encosta_path = OUT_DIR / "instabilidade_encosta.shp"
    encosta.to_file(encosta_path)
    print(f"\n✅ Instabilidade de encosta: {len(encosta)} trechos")
    print(f"   Salvo em: {encosta_path}")

    inundacao_path = OUT_DIR / "inundacao.shp"
    inundacao.to_file(inundacao_path)
    print(f"\n✅ Inundação: {len(inundacao)} trechos")
    print(f"   Salvo em: {inundacao_path}")

    ambos_path = OUT_DIR / "ambos_hazards.shp"
    ambos.to_file(ambos_path)
    print(f"\n✅ Ambos os hazards: {len(ambos)} trechos")
    print(f"   Salvo em: {ambos_path}")

    # Estatísticas por região
    print("\n📊 Distribuição por região (Instabilidade de Encosta):")
    for rid in sorted(encosta["region_id"].dropna().unique()):
        count = len(encosta[encosta["region_id"] == rid])
        name = encosta[encosta["region_id"] == rid]["region_name"].iloc[0]
        print(f"   Região {int(rid)} ({name}): {count} trechos")

    print("\n📊 Distribuição por região (Inundação):")
    for rid in sorted(inundacao["region_id"].dropna().unique()):
        count = len(inundacao[inundacao["region_id"] == rid])
        name = inundacao[inundacao["region_id"] == rid]["region_name"].iloc[0]
        print(f"   Região {int(rid)} ({name}): {count} trechos")

    # Informações sobre atributos
    print("\n📋 Atributos preservados:")
    for col in sorted(encosta.columns):
        if col != "geometry":
            print(f"   - {col}")


def main():
    print("=" * 70)
    print("🚗 Exportador de Camadas de Hazard - PLI-HazardTrack")
    print("=" * 70)

    gdf = process_shapefile()
    export_by_hazard(gdf)

    print("\n" + "=" * 70)
    print("✨ Exportação concluída com sucesso!")
    print("=" * 70)


if __name__ == "__main__":
    main()
