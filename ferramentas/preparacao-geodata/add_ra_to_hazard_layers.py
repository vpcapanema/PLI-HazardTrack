"""
Adiciona campos RA (Risco Analisado) aos shapefiles de hazard.

Processa dados da Tabela 3.3.3.1-3 e 3.3.3.1-4 (Relatório REGEA-NIPPON 2021)
e associa o RA geológico e hidrológico a cada trecho rodoviário.

Estratégia:
1. Para cada trecho, busca RA_GEO e RA_HID no RA_OFFICIAL
2. Se o trecho estiver em um segmento mapeado, usa aquele RA
3. Se não, tenta calcular um RA regional médio baseado em outros trechos
   da mesma região
4. Adiciona campos: ra_geo, ra_hid, ra_geo_moda_region, ra_hid_moda_region
"""

from pathlib import Path
import sys
import geopandas as gpd
import pandas as pd

# Permite importar ra_official (tabelas do Produto 7)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ferramentas" / "relatorios-plano-contingencia"))
from ra_official import RA_GEO_BY_SEGMENT, RA_HID_BY_SEGMENT  # noqa: E402

# Shapefiles já exportados
EXPORT_DIR = ROOT / "data" / "export"
INPUT_FILES = [
    EXPORT_DIR / "instabilidade_encosta.shp",
    EXPORT_DIR / "inundacao.shp",
    EXPORT_DIR / "ambos_hazards.shp",
]


def get_region_ra_stats():
    """
    Calcula estatísticas de RA por região usando dados oficiais.
    Retorna: {region_id: {'geo_moda': int, 'hid_moda': int, 'count': int}}
    """
    region_stats = {}
    
    # Coleta todos os RAs por região
    for (rodovia, km_ini, km_fim), geo_data in RA_GEO_BY_SEGMENT.items():
        region_id = geo_data.get("regiao")
        if region_id not in region_stats:
            region_stats[region_id] = {"geo_modas": [], "hid_modas": []}
        
        region_stats[region_id]["geo_modas"].append(geo_data["moda"])
    
    for (rodovia, km_ini, km_fim), hid_data in RA_HID_BY_SEGMENT.items():
        region_id = hid_data.get("regiao")
        if region_id not in region_stats:
            region_stats[region_id] = {"geo_modas": [], "hid_modas": []}
        
        region_stats[region_id]["hid_modas"].append(hid_data["moda"])
    
    # Calcula moda por região
    result = {}
    for region_id, data in region_stats.items():
        geo_modas = data.get("geo_modas", [])
        hid_modas = data.get("hid_modas", [])
        
        # Calcula moda (valor mais frequente)
        geo_moda = max(set(geo_modas), key=geo_modas.count) if geo_modas else None
        hid_moda = max(set(hid_modas), key=hid_modas.count) if hid_modas else None
        
        result[region_id] = {
            "geo_moda": geo_moda,
            "hid_moda": hid_moda,
            "geo_count": len(geo_modas),
            "hid_count": len(hid_modas),
        }
    
    return result


def find_ra_for_segment(rodovia, km_ini, km_fim, is_hid=False):
    """
    Encontra RA para um segmento de trecho (km_ini a km_fim).
    Busca em RA_GEO_BY_SEGMENT ou RA_HID_BY_SEGMENT por interseção de KMs.
    
    Retorna: (ra_moda, uba, source) ou (None, None, "SEM_DADO")
    """
    rodovia_norm = (rodovia or "").strip().upper()
    
    # Escolhe dicionário de busca
    search_dict = RA_HID_BY_SEGMENT if is_hid else RA_GEO_BY_SEGMENT
    
    # Procura segmentos que se sobrepõem com (km_ini, km_fim)
    for (seg_rod, seg_km0, seg_km1), data in search_dict.items():
        if rodovia_norm != seg_rod:
            continue
        
        # Verifica se há interseção entre [km_ini, km_fim] e [seg_km0, seg_km1]
        # Interseção existe se: max(ini1, ini2) <= min(fim1, fim2)
        overlap_start = max(km_ini, seg_km0)
        overlap_end = min(km_fim, seg_km1)
        
        if overlap_start <= overlap_end:
            # Há interseção! Retorna o RA deste segmento
            ra_moda = int(data["moda"])
            uba = data.get("uba", "?")
            source = f"REGEA2021:{rodovia_norm}:{uba}:{seg_km0}-{seg_km1}"
            return (ra_moda, uba, source)
    
    # Nenhuma interseção encontrada
    return (None, None, "SEM_DADO")


def add_ra_to_shapefile(shp_path):
    """Adiciona campos RA ao shapefile."""
    print(f"\n📥 Carregando: {shp_path.name}")
    gdf = gpd.read_file(shp_path)
    print(f"   {len(gdf)} features")
    
    # Obtém estatísticas por região
    region_stats = get_region_ra_stats()
    
    # Inicializa colunas
    gdf["ra_geo"] = None
    gdf["ra_hid"] = None
    gdf["ra_geo_mod_rg"] = None  # moda regional (abreviado para caber em 10 chars)
    gdf["ra_hid_mod_rg"] = None
    gdf["ra_geo_src"] = ""
    gdf["ra_hid_src"] = ""
    
    # Para cada feature, tenta encontrar RA por interseção de segmento
    for idx, row in gdf.iterrows():
        rodovia = str(row.get("rodovia", "")).strip()
        km_ini = row.get("km_ini")
        km_fim = row.get("km_fim")
        region_id = row.get("region_id")
        
        # Só faz match se temos KM válidos
        if km_ini is not None and km_fim is not None:
            # Busca RA Geológico
            ra_geo, uba_geo, source_geo = find_ra_for_segment(
                rodovia, km_ini, km_fim, is_hid=False
            )
            if ra_geo is not None:
                gdf.at[idx, "ra_geo"] = int(ra_geo)
                gdf.at[idx, "ra_geo_src"] = source_geo
            
            # Busca RA Hidrológico
            ra_hid, uba_hid, source_hid = find_ra_for_segment(
                rodovia, km_ini, km_fim, is_hid=True
            )
            if ra_hid is not None:
                gdf.at[idx, "ra_hid"] = int(ra_hid)
                gdf.at[idx, "ra_hid_src"] = source_hid
        
        # Atribui moda regional como fallback
        if region_id is not None and int(region_id) in region_stats:
            stats = region_stats[int(region_id)]
            if stats["geo_moda"] is not None:
                gdf.at[idx, "ra_geo_mod_rg"] = int(stats["geo_moda"])
            if stats["hid_moda"] is not None:
                gdf.at[idx, "ra_hid_mod_rg"] = int(stats["hid_moda"])
    
    # Salva arquivo atualizado
    gdf.to_file(shp_path)
    print(f"   ✅ Salvo com campos RA")
    
    # Estatísticas
    com_ra_geo = gdf["ra_geo"].notna().sum()
    com_ra_hid = gdf["ra_hid"].notna().sum()
    print(f"   📊 RA Geológico: {com_ra_geo}/{len(gdf)} trechos")
    print(f"   📊 RA Hidrológico: {com_ra_hid}/{len(gdf)} trechos")
    
    # Detalha quais trechos têm RA
    with_geo = gdf[gdf["ra_geo"].notna()]
    if len(with_geo) > 0:
        print(f"   📍 Trechos com RAGEO específico:")
        for _, row in with_geo.iterrows():
            print(f"      {row['rodovia']} km {row['km_ini']}-{row['km_fim']}: "
                  f"RA={int(row['ra_geo'])} ({row['ra_geo_src']})")
    
    return gdf


def print_summary(region_stats):
    """Exibe resumo das modas por região."""
    print("\n" + "=" * 70)
    print("📋 RESUMO: RA MODA POR REGIÃO (do relatório REGEA-NIPPON 2021)")
    print("=" * 70)
    
    regions_map = {
        1: "Mogi-Bertioga (SP-098)",
        2: "Caraguatatuba-Ubatuba (SP-055)",
        3: "São Sebastião (SP-055)",
        4: "Santos-Bertioga (SP-055)"
    }
    
    for region_id in sorted(region_stats.keys()):
        stats = region_stats[region_id]
        region_name = regions_map.get(region_id, f"Região {region_id}")
        print(f"\nRegião {region_id}: {region_name}")
        print(f"  RAGEO Moda: {stats['geo_moda']} (de {stats['geo_count']} segmentos)")
        print(f"  RAHID Moda: {stats['hid_moda']} (de {stats['hid_count']} segmentos)")


def main():
    print("=" * 70)
    print("🔗 Adicionador de Campos RA - Camadas de Hazard")
    print("=" * 70)
    
    # Calcula estatísticas por região
    region_stats = get_region_ra_stats()
    print_summary(region_stats)
    
    # Processa cada shapefile
    print("\n" + "=" * 70)
    print("📝 PROCESSANDO SHAPEFILES")
    print("=" * 70)
    
    for shp_path in INPUT_FILES:
        if shp_path.exists():
            add_ra_to_shapefile(shp_path)
        else:
            print(f"\n⚠️  Não encontrado: {shp_path}")
    
    print("\n" + "=" * 70)
    print("✨ Conclusão: Campos RA adicionados aos shapefiles!")
    print("=" * 70)
    print("\nCampos adicionados:")
    print("  - ra_geo: RA Geológico do trecho (valores oficiais)")
    print("  - ra_hid: RA Hidrológico do trecho (valores oficiais)")
    print("  - ra_geo_mod_rg: Moda regional de RAGEO (fallback)")
    print("  - ra_hid_mod_rg: Moda regional de RAHID (fallback)")
    print("  - ra_geo_src: Fonte do RA Geológico (REGEA2021 ou SEM_DADO)")
    print("  - ra_hid_src: Fonte do RA Hidrológico (REGEA2021 ou SEM_DADO)")


if __name__ == "__main__":
    main()
