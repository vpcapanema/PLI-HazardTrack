"""Exporta as camadas regionais do GeoPackage `pli-hazardtrack.gpkg` em
dois GeoJSONs consumidos pelo runtime do sistema:

  data/regioes/regioes_estudo.geojson  - 4 Polygons (uma por regiao)
  data/regioes/regioes_eixos.geojson   - 4 LineStrings (eixo da rodovia
                                         por regiao, dissolvido)

Politica: SEM normalizacao de nomes. As features carregam EXATAMENTE os
atributos nativos da camada-mae (`regioes_estudo` + dissolucao de
`auxilio_regioes_estudo` por `regiao_id`). Apenas os parametros
hidro-meteorologicos (k_geo, cpc_breaks, hid24h_breaks), que vem das
Tabelas 3.1.1-2 / 3.1.2-1 do PRODUTO 6 (REGEA-NIPPON, 2021) e nao do
GeoPackage, sao injetados durante o export por meio do dict
`CLIMATIC_PARAMS` abaixo.

Backend (`core/regions.py`) le exclusivamente estes dois arquivos.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from shapely.ops import linemerge
from shapely.geometry import LineString, MultiLineString

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
GPKG = ROOT / "data" / "pli-hazardtrack.gpkg"
LAYER_POLY = "regioes_estudo"
LAYER_EIXO = "auxilio_regioes_estudo"
OUT_DIR = ROOT / "data" / "regioes"
OUT_POLY = OUT_DIR / "regioes_estudo.geojson"
OUT_EIXO = OUT_DIR / "regioes_eixos.geojson"

# Parametros calibrados das Tabelas 3.1.1-2 (CPC/K geologico) e 3.1.2-1
# (chuva 24h hidrologico) do Relatorio PRODUTO 6 (REGEA-NIPPON, 2021).
# Indexados por `regiao_id` (1..4). Mantidos aqui para que o GeoJSON
# saia auto-contido (o backend nao precisa de tabela de lookup).
CLIMATIC_PARAMS: dict[int, dict] = {
    1: {  # Mogi-Bertioga (SP-098)
        "k_geo": 1000,
        "cpc_breaks": [1, 3, 6, 15],
        "hid24h_breaks": [110, 160, 200, 280],
    },
    2: {  # Caraguatatuba-Ubatuba (SP-055)
        "k_geo": 400,
        "cpc_breaks": [1, 6, 12, 24],
        "hid24h_breaks": [70, 80, 120, 143],
    },
    3: {  # Sao Sebastiao (SP-055)
        "k_geo": 200,
        "cpc_breaks": [1, 8, 16, 24],
        "hid24h_breaks": [60, 85, 110, 126],
    },
    4: {  # Santos-Bertioga (SP-055)
        "k_geo": 1000,
        "cpc_breaks": [1, 4, 8, 16],
        "hid24h_breaks": [150, 200, 230, 300],
    },
}


def _inject_climatic(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = gdf.copy()
    g["k_geo"] = g["regiao_id"].map(
        lambda rid: CLIMATIC_PARAMS[int(rid)]["k_geo"]
    )
    g["cpc_breaks"] = g["regiao_id"].map(
        lambda rid: ";".join(
            str(x) for x in CLIMATIC_PARAMS[int(rid)]["cpc_breaks"]
        )
    )
    g["hid24h_breaks"] = g["regiao_id"].map(
        lambda rid: ";".join(
            str(x) for x in CLIMATIC_PARAMS[int(rid)]["hid24h_breaks"]
        )
    )
    return g


def _flatten_lines(geom) -> list[LineString]:
    """Explode MultiLineString/LineString em uma lista de LineString."""
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [g for g in geom.geoms if not g.is_empty]
    return []


def _dissolve_eixos(gdf_lines: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Dissolve LineStrings de `auxilio_regioes_estudo` por `regiao_id`.

    Aplica `linemerge` para obter uma polilinha continua por regiao
    (ou MultiLineString quando ha gap real). Retorna um GeoDataFrame
    com `regiao_id`, `regiao_nome`, `sigla_rodovia`, `geometry`.
    """
    rows = []
    cols = ["regiao_id", "regiao_nome", "sigla_rodovia"]
    for rid, sub in gdf_lines.groupby("regiao_id"):
        flat: list[LineString] = []
        for g in sub.geometry.tolist():
            flat.extend(_flatten_lines(g))
        merged = linemerge(MultiLineString(flat))
        if isinstance(merged, (LineString, MultiLineString)):
            geom = merged
        else:
            geom = MultiLineString(flat)
        row = {c: sub.iloc[0][c] for c in cols}
        row["regiao_id"] = int(rid)
        row["n_subtrechos_der"] = int(len(sub))
        row["geometry"] = geom
        rows.append(row)
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=gdf_lines.crs)
    return out.sort_values("regiao_id").reset_index(drop=True)


def main() -> None:
    print("=" * 70)
    print("EXPORT regioes_estudo + auxilio_regioes_estudo -> GeoJSON")
    print("=" * 70)
    if not GPKG.exists():
        print(f"ERRO: GPKG nao encontrado: {GPKG}")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Poligonos ---
    poly = gpd.read_file(GPKG, layer=LAYER_POLY)
    print(f"  {LAYER_POLY}: {len(poly)} features (CRS {poly.crs})")
    if poly.crs is None or str(poly.crs).upper() != "EPSG:4326":
        poly = poly.to_crs(4326)
    poly = poly.sort_values("regiao_id").reset_index(drop=True)
    poly = _inject_climatic(poly)
    if OUT_POLY.exists():
        OUT_POLY.unlink()
    poly.to_file(OUT_POLY, driver="GeoJSON")
    print(f"    -> {OUT_POLY.relative_to(ROOT)}")
    print(f"       {len(poly)} features, {len(poly.columns)} atributos")

    # --- Eixos (dissolvidos) ---
    eixo = gpd.read_file(GPKG, layer=LAYER_EIXO)
    print(f"  {LAYER_EIXO}: {len(eixo)} features (CRS {eixo.crs})")
    if eixo.crs is None or str(eixo.crs).upper() != "EPSG:4326":
        eixo = eixo.to_crs(4326)
    eixos = _dissolve_eixos(eixo)
    if OUT_EIXO.exists():
        OUT_EIXO.unlink()
    eixos.to_file(OUT_EIXO, driver="GeoJSON")
    print(f"    -> {OUT_EIXO.relative_to(ROOT)}")
    print(f"       {len(eixos)} features (dissolvido por regiao_id)")

    print()
    cols = sorted(c for c in poly.columns if c != "geometry")
    print(f"  Atributos do poligono: {cols}")
    print()
    for _, r in poly.iterrows():
        print(
            f"   regiao {int(r['regiao_id'])} {r['regiao_nome']:<22} "
            f"{r['sigla_rodovia']} | "
            f"k_geo={r['k_geo']} cpc={r['cpc_breaks']} "
            f"hid={r['hid24h_breaks']} | "
            f"area={r['area_km2']:.2f} km^2"
        )


if __name__ == "__main__":
    main()
