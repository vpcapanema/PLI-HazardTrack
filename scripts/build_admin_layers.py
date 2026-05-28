"""
Constroi as camadas administrativas (limites) para o mapa:

  1. Municipios SP    (IGC 2021)            -> static/data/municipios.geojson
  2. Residencias de Conserva (RC)           -> static/data/rc_poligonos.geojson
  3. Unidades Basicas de Atendimento (UBA)  -> static/data/uba_poligonos.geojson
  4. Coord. Gerais Regionais (CGR)          -> static/data/cgr_poligonos.geojson

Para 2..4: parte do shape "RESIDENCIAS_CONSERVA_POLIGONOS" (granularidade RC)
e dissolve por UBA e Regional. No shape atual cada RC equivale a uma UBA, mas
mantemos as 4 camadas separadas como definicao logica - quando a granularidade
do dado mudar, basta rodar este script de novo.

O codigo das regionais e migrado de "DR" para "CGR" para refletir a
nomenclatura atual (Coordenadoria Geral Regional).
"""

from pathlib import Path
import geopandas as gpd
import json

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "static" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Tolerancias de simplificacao (em graus). 0.0005 ~ 50 m.
SIMPLIFY_MUN = 0.0015
SIMPLIFY_ADMIN = 0.0015


def _reproj_4326(gdf):
    if gdf.crs is None:
        return gdf
    try:
        if gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")
    except Exception:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def _save(gdf, path, label):
    if path.exists():
        path.unlink()
    # Usa pyogrio com COORDINATE_PRECISION para reduzir tamanho do arquivo
    try:
        gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=5)
    except Exception:
        gdf.to_file(path, driver="GeoJSON")
    size_kb = path.stat().st_size / 1024
    print(f"  -> {label}: {len(gdf)} feicoes, {size_kb:.1f} KB ({path.name})")


# ----------------------------------------------------------------------------
# 1. Municipios SP
# ----------------------------------------------------------------------------
print("\n[1/4] Municipios SP (IGC 2021)")
mun_shp = ROOT / "data" / "dradt_mvw_lml_municipio_a_2021" / "dradt_mvw_lml_municipio_a_2021.shp"
mun = gpd.read_file(mun_shp)
print(f"  {len(mun)} municipios em CRS {mun.crs}")
mun = _reproj_4326(mun)

# Mantem o essencial. Os campos exatos podem variar entre versoes do shape;
# pega o que existir.
KEEP_MUN = ["geocodigo", "nome", "geocodig_m", "nm_municip", "municipio", "cd_geocodm"]
keep = [c for c in KEEP_MUN if c in mun.columns]
if keep:
    mun = mun[keep + ["geometry"]]

# Renomeia para nomes amigaveis
rename_map = {}
for col in mun.columns:
    cl = col.lower()
    if "nome" in cl or "munici" in cl or cl in {"nm_municip"}:
        rename_map[col] = "nome"
    if "geocodig" in cl or cl == "cd_geocodm":
        rename_map[col] = "codigo"
mun = mun.rename(columns=rename_map)
mun["geometry"] = mun["geometry"].simplify(SIMPLIFY_MUN, preserve_topology=True)
_save(mun, OUT_DIR / "municipios.geojson", "municipios")


# ----------------------------------------------------------------------------
# 2..4. Residencias / UBA / CGR a partir do shape de RC
# ----------------------------------------------------------------------------
print("\n[2..4] Camadas administrativas DER")
rc_shp = ROOT / "data" / "RESIDENCIAS_CONSERVA_POLIGONOS" / "residencia_conserva_poligonos.shp"
rc = gpd.read_file(rc_shp)
print(f"  {len(rc)} feicoes em CRS {rc.crs}; colunas: {list(rc.columns)}")
rc = _reproj_4326(rc)

# Normaliza nomes de coluna - aceita variacoes
def _find(cols, *candidates):
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in low:
            return low[cand.lower()]
    return None

col_rc = _find(rc.columns, "RC", "rc")
col_uba = _find(rc.columns, "UBA", "uba")
col_reg = _find(rc.columns, "Regional", "regional", "DR", "dr")

print(f"  colunas detectadas: RC='{col_rc}', UBA='{col_uba}', Regional='{col_reg}'")
assert col_rc and col_uba and col_reg, "shape nao tem as colunas esperadas (RC/UBA/Regional)"

# Garante string e remove espacos
for c in [col_rc, col_uba, col_reg]:
    rc[c] = rc[c].astype(str).str.strip()

# --- 2. Residencias de Conserva (RC)
print("\n[2/4] Residencias de Conserva (RC)")
rc_lyr = rc[[col_rc, col_uba, col_reg, "geometry"]].copy()
rc_lyr = rc_lyr.rename(columns={col_rc: "rc", col_uba: "uba", col_reg: "regional"})
rc_lyr["regional_cgr"] = rc_lyr["regional"].str.replace(r"^\s*DR\b", "CGR", regex=True)
rc_lyr["geometry"] = rc_lyr["geometry"].simplify(SIMPLIFY_ADMIN, preserve_topology=True)
_save(rc_lyr, OUT_DIR / "rc_poligonos.geojson", "RC")

# --- 3. UBA: dissolve por uba (no shape atual e 1:1 com RC, mas mantemos
# camada separada por definicao logica - se o dado mudar, ja agrega certo).
print("\n[3/4] Unidades Basicas de Atendimento (UBA)")
uba_lyr = rc[[col_uba, col_reg, "geometry"]].copy()
uba_lyr = uba_lyr.rename(columns={col_uba: "uba", col_reg: "regional"})
uba_lyr = uba_lyr.dissolve(by="uba", aggfunc={"regional": "first"}, as_index=False)
uba_lyr["regional_cgr"] = uba_lyr["regional"].str.replace(r"^\s*DR\b", "CGR", regex=True)
uba_lyr["geometry"] = uba_lyr["geometry"].simplify(SIMPLIFY_ADMIN, preserve_topology=True)
_save(uba_lyr, OUT_DIR / "uba_poligonos.geojson", "UBA")

# --- 4. CGR (Coord. Geral Regional, ex-DR): dissolve por regional
print("\n[4/4] Coordenadorias Gerais Regionais (CGR, ex-DR)")
cgr_lyr = rc[[col_reg, "geometry"]].copy()
cgr_lyr = cgr_lyr.rename(columns={col_reg: "regional"})
cgr_lyr["regional_cgr"] = cgr_lyr["regional"].str.replace(r"^\s*DR\b", "CGR", regex=True)
cgr_lyr = cgr_lyr.dissolve(by="regional_cgr", as_index=False)
cgr_lyr = cgr_lyr.drop(columns=["regional"], errors="ignore")
cgr_lyr["geometry"] = cgr_lyr["geometry"].simplify(SIMPLIFY_ADMIN, preserve_topology=True)
_save(cgr_lyr, OUT_DIR / "cgr_poligonos.geojson", "CGR")

print("\nOK. Camadas administrativas geradas.")
