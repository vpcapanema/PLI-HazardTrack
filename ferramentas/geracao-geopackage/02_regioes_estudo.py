"""
Camadas 02 e 03 do GeoPackage `pli-hazardtrack.gpkg`:

  - auxilio_regioes_estudo (LineString, 23 features)
      1 feature por subtrecho cadastral oficial do DER que cai na area
      de estudo (Tabela 2-1 do PRODUTO 7). Atributos preservados do
      DER + regiao_id (1..4) + UBA via cruzamento espacial com o shape
      de Residencias de Conservacao.

  - regioes_estudo (Polygon, 4 features)
      1 feature por regiao operacional. Geometria construida por:
        * dissolucao (linemerge) dos subtrechos contiguos por regiao
        * buffer lateral de 1000 m com cap_style="flat" para que as
          emendas entre R2-R3 e R3-R4 coincidam aresta-a-aresta
        * union com Point.buffer(1000) nas pontas absolutas (nao-emendas)
          para arredondar essas extremidades

Fontes:
  - data/_der_src/MALHA_RODOVIARIA.shp  (DER-SP sistema rodoviario, 2024)
  - data/RESIDENCIAS_CONSERVA_POLIGONOS/residencia_conserva_poligonos.shp
  - Tabela 2-1 do PRODUTO 7 (Relatorio 2053-R04-21)

Saida em EPSG:4326. Calculos metricos em EPSG:31983 (SIRGAS 2000 / UTM 23S).
"""
import sys
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, MultiPolygon
from shapely.ops import unary_union, linemerge

sys.stdout.reconfigure(encoding="utf-8")

SHP_DER = Path("data/_der_src/MALHA_RODOVIARIA.shp")
SHP_RC = Path(
    "data/RESIDENCIAS_CONSERVA_POLIGONOS/"
    "residencia_conserva_poligonos.shp"
)
GPKG = Path("data/pli-hazardtrack.gpkg")

EPSG_UTM = 31983   # SIRGAS 2000 / UTM zone 23S
EPSG_OUT = 4326    # WGS84 lat/lon
BUFFER_M = 1000    # 1 km lateral -> faixa total 2 km (Secao 2 P7)

# Definicao oficial (Tabela 2-1 PRODUTO 7)
REGIOES = {
    1: dict(nome="Mogi-Bertioga",
            rodovia_shp="SP 098", sigla="SP-098",
            km_ini=62.900, km_fim=98.100, ext_oficial=35.200),
    2: dict(nome="Caraguatatuba-Ubatuba",
            rodovia_shp="SP 055", sigla="SP-055",
            km_ini=53.600, km_fim=112.550, ext_oficial=58.950),
    3: dict(nome="São Sebastião",
            rodovia_shp="SP 055", sigla="SP-055",
            km_ini=112.550, km_fim=191.400, ext_oficial=78.850),
    4: dict(nome="Santos-Bertioga",
            rodovia_shp="SP 055", sigla="SP-055",
            km_ini=191.400, km_fim=248.100, ext_oficial=56.700),
}


# ---------------------------------------------------------------------------
# ETAPA A - auxilio_regioes_estudo
# ---------------------------------------------------------------------------
def construir_auxilio():
    print("=" * 70)
    print("ETAPA A: auxilio_regioes_estudo")
    print("=" * 70)

    # Le shape DER. Encoding: o CPG diz UTF-8 mas testes mostraram que o
    # DBF estA em CP-1252; tentamos UTF-8 primeiro e caimos no fallback.
    try:
        gdf = gpd.read_file(SHP_DER, encoding="utf-8")
        # Sanity check
        if any("Ã" in str(m) for m in gdf["Municipio"].head(50)):
            raise UnicodeDecodeError("dbf", b"", 0, 1, "mojibake")
    except (UnicodeDecodeError, Exception):
        gdf = gpd.read_file(SHP_DER, encoding="latin-1")
    print(f"  DER total: {len(gdf)} features  CRS: {gdf.crs}")

    # Filtra por rodovia + area de estudo (KmInicial>=ki E KmFinal<=kf)
    blocos = []
    for rid, meta in REGIOES.items():
        sel = gdf[
            (gdf["Rodovia"] == meta["rodovia_shp"])
            & (gdf["KmInicial"] >= meta["km_ini"] - 1e-3)
            & (gdf["KmFinal"] <= meta["km_fim"] + 1e-3)
        ].copy()
        sel["regiao_id"] = rid
        sel["regiao_nome"] = meta["nome"]
        sel["sigla_rodovia"] = meta["sigla"]
        blocos.append(sel)
        print(f"  R{rid} {meta['sigla']} km {meta['km_ini']}-{meta['km_fim']}: "
              f"{len(sel)} subtrechos, "
              f"Sigma Extensao={sel['Extensao'].sum():.3f} km "
              f"(oficial {meta['ext_oficial']})")
    aux = gpd.GeoDataFrame(
        pd.concat(blocos, ignore_index=True), crs=gdf.crs
    )

    # ----- spatial join para preencher UBA -----
    rc = gpd.read_file(SHP_RC, encoding="utf-8")
    print(f"\n  Residencias: {len(rc)} poligonos  CRS: {rc.crs}")
    aux_utm = aux.to_crs(EPSG_UTM)
    rc_utm = rc.to_crs(EPSG_UTM)

    ubas, rcs, regionais_rc = [], [], []
    for geom in aux_utm.geometry:
        # tenta com centroide (50% do comprimento)
        ponto = geom.interpolate(0.5, normalized=True)
        hit = rc_utm[rc_utm.contains(ponto)]
        if len(hit) == 0:
            hit = rc_utm[rc_utm.intersects(geom)]
        if len(hit) > 0:
            ubas.append(hit.iloc[0]["UBA"])
            rcs.append(hit.iloc[0]["RC"])
            regionais_rc.append(hit.iloc[0]["Regional"])
        else:
            ubas.append(None)
            rcs.append(None)
            regionais_rc.append(None)
    aux["uba_nome"] = ubas
    aux["uba_codigo"] = rcs
    aux["dr_codigo_rc"] = regionais_rc
    print(f"  Subtrechos com UBA identificada: "
          f"{sum(u is not None for u in ubas)}/{len(aux)}")

    # Renomeacao final
    aux = aux.rename(columns={
        "KmInicial": "km_inicial",
        "KmFinal": "km_final",
        "Extensao": "extensao_km",
        "Municipio": "municipio",
        "SedeRegion": "regional",
        "CodRegiona": "residencia_dr",
        "Jurisdicao": "jurisdicao",
        "Conservado": "conservado_por",
        "Subtrecho": "subtrecho_der",
    })
    schema = [
        "regiao_id", "regiao_nome", "sigla_rodovia",
        "km_inicial", "km_final", "extensao_km",
        "municipio", "regional", "residencia_dr",
        "uba_nome", "uba_codigo",
        "jurisdicao", "conservado_por", "subtrecho_der",
        "geometry",
    ]
    aux = aux[schema].sort_values(
        ["regiao_id", "km_inicial"]
    ).reset_index(drop=True)
    aux = aux.to_crs(EPSG_OUT)

    aux.to_file(GPKG, layer="auxilio_regioes_estudo",
                driver="GPKG", index=False)
    print(f"\n  Camada 'auxilio_regioes_estudo' salva: "
          f"{len(aux)} features no GPKG")
    return aux


# ---------------------------------------------------------------------------
# ETAPA B - regioes_estudo
# ---------------------------------------------------------------------------
ROD_POR_REGIAO = {1: "SP-098", 2: "SP-055", 3: "SP-055", 4: "SP-055"}


def _endpoints(geom):
    if hasattr(geom, "geoms"):
        pts = []
        for g in geom.geoms:
            pts.append(Point(g.coords[0]))
            pts.append(Point(g.coords[-1]))
        return pts
    return [Point(geom.coords[0]), Point(geom.coords[-1])]


def _is_emenda(ponto, regiao_id, linhas_por_regiao, tol=1.0):
    """Eh emenda se a < tol de outra regiao da MESMA rodovia."""
    rod = ROD_POR_REGIAO[regiao_id]
    for rid, line in linhas_por_regiao.items():
        if rid == regiao_id:
            continue
        if ROD_POR_REGIAO[rid] != rod:
            continue
        if ponto.distance(line) < tol:
            return True
    return False


def construir_regioes(aux_4326):
    print()
    print("=" * 70)
    print("ETAPA B: regioes_estudo")
    print("=" * 70)
    aux_utm = aux_4326.to_crs(EPSG_UTM)

    # Linha dissolvida por regiao
    linhas_por_regiao = {}
    for rid in [1, 2, 3, 4]:
        sub = aux_utm[aux_utm["regiao_id"] == rid]
        merged = linemerge(unary_union(sub.geometry.tolist()))
        linhas_por_regiao[rid] = merged
        if hasattr(merged, "geoms"):
            parts = list(merged.geoms)
            print(f"  R{rid}: MultiLineString {len(parts)} partes, "
                  f"L_geom={merged.length / 1000:.3f} km")
        else:
            print(f"  R{rid}: LineString {len(merged.coords)} vertices, "
                  f"L_geom={merged.length / 1000:.3f} km")

    # Buffer com cap flat + Point.buffer nas absolutas
    polygons_utm = []
    n_round_caps = {}
    for rid in [1, 2, 3, 4]:
        line = linhas_por_regiao[rid]
        buf = line.buffer(BUFFER_M, cap_style="flat", join_style="round")
        added = 0
        eps = _endpoints(line)
        # Remove duplicatas perfeitas (MultiLineString pode listar mais
        # endpoints internos)
        unique_eps = []
        for ep in eps:
            dup = any(ep.distance(u) < 0.5 for u in unique_eps)
            if not dup:
                unique_eps.append(ep)
        for ep in unique_eps:
            if not _is_emenda(ep, rid, linhas_por_regiao):
                cap = ep.buffer(BUFFER_M)
                buf = buf.union(cap)
                added += 1
        n_round_caps[rid] = added
        print(f"  R{rid}: buffer area={buf.area / 1e6:.3f} km^2  "
              f"endpoints={len(unique_eps)}  caps round adicionadas={added}")
        polygons_utm.append(buf)

    # Atributos agregados a partir da camada auxiliar.
    # Inclui todos os atributos textuais nao-especificos-de-trecho,
    # alem de subtrechos_der (lista de IDs cadastrais que compoem a regiao,
    # ordenada por km_inicial - util para rastreabilidade/auditoria).
    aux_sorted = aux_4326.sort_values(["regiao_id", "km_inicial"])
    agg = aux_sorted.groupby("regiao_id").agg(
        municipios=("municipio",
                    lambda s: ";".join(sorted(set(x for x in s if x)))),
        ubas=("uba_nome",
              lambda s: ";".join(sorted(set(x for x in s if x)))),
        ubas_codigo=("uba_codigo",
                     lambda s: ";".join(sorted(set(x for x in s if x)))),
        residencias_dr=("residencia_dr",
                        lambda s: ";".join(sorted(set(x for x in s if x)))),
        regionais=("regional",
                   lambda s: ";".join(sorted(set(x for x in s if x)))),
        jurisdicoes=("jurisdicao",
                     lambda s: ";".join(sorted(set(x for x in s if x)))),
        conservado_por=("conservado_por",
                        lambda s: ";".join(sorted(set(x for x in s if x)))),
        subtrechos_der=("subtrecho_der",
                        lambda s: ";".join([str(x) for x in s if x])),
        n_subtrechos_der=("regiao_id", "size"),
        extensao_oficial_km=("extensao_km", "sum"),
    ).reset_index()

    # Anexa geometrias e metadados oficiais
    agg["geometry"] = polygons_utm
    agg["regiao_nome"] = agg["regiao_id"].map(lambda r: REGIOES[r]["nome"])
    agg["sigla_rodovia"] = agg["regiao_id"].map(
        lambda r: REGIOES[r]["sigla"])
    agg["km_inicial"] = agg["regiao_id"].map(lambda r: REGIOES[r]["km_ini"])
    agg["km_final"] = agg["regiao_id"].map(lambda r: REGIOES[r]["km_fim"])
    agg["buffer_lateral_m"] = BUFFER_M
    agg["tampas_round"] = agg["regiao_id"].map(
        {1: "inicio,fim", 2: "inicio", 3: "—", 4: "fim"})
    agg["n_caps_round_adicionadas"] = agg["regiao_id"].map(n_round_caps)
    agg["extensao_oficial_km"] = agg["extensao_oficial_km"].round(3)

    gdf = gpd.GeoDataFrame(agg, geometry="geometry",
                           crs=f"EPSG:{EPSG_UTM}")
    gdf["area_km2"] = (gdf.geometry.area / 1e6).round(3)
    gdf["perimetro_km"] = (gdf.geometry.length / 1000).round(3)

    schema = [
        "regiao_id", "regiao_nome", "sigla_rodovia",
        "km_inicial", "km_final", "extensao_oficial_km",
        "n_subtrechos_der",
        "municipios", "ubas", "ubas_codigo",
        "residencias_dr", "regionais", "jurisdicoes",
        "conservado_por", "subtrechos_der",
        "area_km2", "perimetro_km",
        "buffer_lateral_m", "tampas_round", "n_caps_round_adicionadas",
        "geometry",
    ]
    gdf = gdf[schema].sort_values("regiao_id").reset_index(drop=True)
    gdf = gdf.to_crs(EPSG_OUT)
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: g if isinstance(g, MultiPolygon) else MultiPolygon([g])
    )
    gdf.to_file(GPKG, layer="regioes_estudo", driver="GPKG", index=False)
    print(f"\n  Camada 'regioes_estudo' salva: {len(gdf)} features no GPKG")
    return gdf, linhas_por_regiao


# ---------------------------------------------------------------------------
# VALIDACAO
# ---------------------------------------------------------------------------
def validar(aux, regs, linhas):
    print()
    print("=" * 70)
    print("VALIDACAO")
    print("=" * 70)
    # 1) Soma extensoes
    by_reg = aux.groupby("regiao_id")["extensao_km"].sum()
    diffs = []
    for rid, ext in by_reg.items():
        of = REGIOES[rid]["ext_oficial"]
        diffs.append(ext - of)
        print(f"  R{rid} extensao soma={ext:.3f}  oficial={of:.3f}  "
              f"diff={(ext - of):+.4f}")
    print(f"  Sigma sum extensao = {by_reg.sum():.3f} "
          f"(oficial 229.700)  diff={by_reg.sum() - 229.700:+.4f}")

    # 2) Emendas: distancia entre vertices terminais que devem coincidir
    print("\n  Emendas (distancia entre endpoints adjacentes na MESMA "
          "polilinha contigua, deve ser ~0):")
    for (a, b) in [(2, 3), (3, 4)]:
        la, lb = linhas[a], linhas[b]
        # Compara cada endpoint de a com cada endpoint de b
        eps_a = _endpoints(la)
        eps_b = _endpoints(lb)
        min_d = min(pa.distance(pb) for pa in eps_a for pb in eps_b)
        print(f"    R{a}-R{b}: min distance vertices = {min_d:.6f} m")

    # 3) Sobreposicao geometrica entre poligonos
    print("\n  Sobreposicao entre poligonos das regioes (em km^2):")
    regs_utm = regs.to_crs(EPSG_UTM)
    polys = {row["regiao_id"]: row.geometry
             for _, row in regs_utm.iterrows()}
    for i in [1, 2, 3, 4]:
        for j in [1, 2, 3, 4]:
            if j <= i:
                continue
            inter = polys[i].intersection(polys[j])
            a = inter.area / 1e6
            mesma_rod = ROD_POR_REGIAO[i] == ROD_POR_REGIAO[j]
            tag = "MESMA rodovia" if mesma_rod else "rodovias diferentes"
            print(f"    R{i} x R{j}  ({tag}): {a:.4f} km^2")


# ---------------------------------------------------------------------------
def main():
    aux = construir_auxilio()
    regs, linhas = construir_regioes(aux)
    validar(aux, regs, linhas)


if __name__ == "__main__":
    main()
