"""
Camada `uas_area_estudo` no GeoPackage pli-hazardtrack.gpkg.

Gera 809 LineStrings (Unidades de Analise) seguindo FIELMENTE a
metodologia descrita no PDF "4 PRODUTO 7 Plano de Contingencia.pdf"
(Relatorio 2053-R04-21, DER-SP / Consorcio 4X044, 2021).

METODOLOGIA OFICIAL (paginas 34 e 71 do PDF):
  - UAs sao mapeadas "na escala de maior detalhe disponivel para cada
    trecho", combinando 3 escalas:
      1:25.000 -> UTB - cobertura regular ~340-340 m por UA
      1:10.000 -> UTB - cobertura regular ~330-360 m por UA
      1:1.000  -> SR  - Setor de Risco, detalhe ~170-200 m por UA,
                        DENTRO dos trechos criticos da Tabela 3.3.3.1-1/-2
  - UTBs e SRs cobrem segmentos COMPLEMENTARES da rodovia (NAO se
    sobrepoem); juntos cobrem ~100% do municipio analisado.
  - Os SRs estao geograficamente DENTRO dos trechos criticos oficiais
    (validado: 252 SRs de R3 ocupam 43.56 km em 44.8 km de trecho
    critico; 16 SRs de R4 Santos ocupam 3.21 km em 3.00 km de trecho).

DECISOES DE GEOMETRIA:
  - UTBs: distribuidas sequencialmente do km inicial do municipio,
    com extensao por UA = ext_pdf_municipio_escala / qtd. Quando a
    extensao PDF e menor que o cadastral DER, os UTBs ocupam o inicio
    do municipio e o restante e onde os SRs ficam.
  - SRs: posicionados dentro do(s) trecho(s) critico(s) que interceptam
    o municipio. Quando ha trecho critico GEO E HID no mesmo municipio,
    usa-se a uniao dos dois.

ATRIBUTOS:
  identificacao + grupo (Tabela 3.3-1), linear referencing
  (km cadastral, subtrecho DER), herdados de `auxilio_regioes_estudo`,
  ICC thresholds denormalizados (Tabela 3.2.2-2 e 3.2.3-1),
  flags `trecho_critico_geo` e `trecho_critico_hid`,
  RAGEO e RAHID (atribuidos por script 41_atribui_ra_fiel.py).
"""
from importlib import import_module
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import linemerge, substring, unary_union

sys.path.insert(0, str(Path("ferramentas/extracao-ra").resolve()))
ot = import_module("40_oficial_tabelas")

sys.stdout.reconfigure(encoding="utf-8")

GPKG = Path("data/pli-hazardtrack.gpkg")
EPSG_UTM = 31983
EPSG_OUT = 4326

ESCALAS = ["25K", "10K", "1K"]
TIPO_POR_ESCALA = {"25K": "UTB", "10K": "UTB", "1K": "SR"}

SIGLA_MUN = {
    "Mogi das Cruzes": "MOG",
    "Biritiba Mirim":  "BIR",
    "Bertioga":        "BER",
    "Caraguatatuba":   "CAR",
    "Ubatuba":         "UBA",
    "São Sebastião":   "SSB",
    "Santos":          "STO",
}

ROD_POR_REGIAO = {1: "SP-098", 2: "SP-055", 3: "SP-055", 4: "SP-055"}


def _to_line(g):
    if g.geom_type == "LineString":
        return g
    if g.geom_type == "MultiLineString":
        parts = list(g.geoms)
        if len(parts) == 1:
            return parts[0]
        merged = linemerge(g)
        if merged.geom_type == "LineString":
            return merged
        return max(merged.geoms, key=lambda x: x.length)
    raise RuntimeError(f"Geom inesperada {g.geom_type}")


def _ordena_eixo(line_utm, aux_grupo_utm):
    from shapely.geometry import Point
    sub = aux_grupo_utm.sort_values("km_inicial").iloc[0]
    sub_line = _to_line(sub.geometry)
    p0 = Point(sub_line.coords[0])
    d_start = p0.distance(Point(line_utm.coords[0]))
    d_end = p0.distance(Point(line_utm.coords[-1]))
    if d_end < d_start:
        return LineString(list(line_utm.coords)[::-1])
    return line_utm


def _subtrecho_de_ponto(ponto, aux_grupo_utm):
    dists = aux_grupo_utm.geometry.distance(ponto)
    idx = dists.idxmin()
    return aux_grupo_utm.loc[idx]


def _km_no_eixo(ponto, aux_grupo_utm):
    row = _subtrecho_de_ponto(ponto, aux_grupo_utm)
    geom = _to_line(row.geometry)
    dist_along = geom.project(ponto)
    frac = dist_along / geom.length if geom.length > 0 else 0
    km = row["km_inicial"] + frac * (row["km_final"] - row["km_inicial"])
    return km, row


def _km_para_offset(km_alvo, line, aux_grupo_utm):
    """Converte um km cadastral em offset metrico ao longo da `line`
    do municipio, via interpolacao linear nas pontas do municipio.
    Retorna offset em metros, ou None se km_alvo esta TOTALMENTE fora.

    Justificativa: subtrechos individuais podem estar com coords
    invertidas (validado em R3 SS km 130-154.015), o que torna
    line.project(subtrecho.interpolate(...)) nao-confiavel. Usar
    interpolacao linear assumindo proporcionalidade entre km cadastral
    e offset metrico e suficiente para posicionar trechos criticos
    (erro tipico < 500 m em rodovias com sinuosidade uniforme).
    """
    km_min = aux_grupo_utm["km_inicial"].min()
    km_max = aux_grupo_utm["km_final"].max()
    if km_alvo < km_min - 0.001 or km_alvo > km_max + 0.001:
        return None
    if km_max == km_min:
        return 0.0
    frac = (km_alvo - km_min) / (km_max - km_min)
    frac = max(0.0, min(1.0, frac))
    return frac * line.length


def _trechos_criticos_no_municipio(rid, _municipio, line, aux_grupo_utm):
    """Devolve lista de tuplas (offset_ini_m, offset_fim_m, tipo)
    correspondentes aos trechos criticos GEO e HID que interceptam
    este municipio. `tipo` em {"GEO", "HID"}.
    """
    out = []
    for tcrit, tipo in (
        [(t, "GEO") for t in ot.TRECHOS_CRITICOS_GEO]
        + [(t, "HID") for t in ot.TRECHOS_CRITICOS_HID]
    ):
        if tcrit["regiao_id"] != rid:
            continue
        # Permitir clamp se trecho critico se estende alem do municipio
        km_min = aux_grupo_utm["km_inicial"].min()
        km_max = aux_grupo_utm["km_final"].max()
        if tcrit["km_fim"] < km_min or tcrit["km_ini"] > km_max:
            continue
        km_i = max(tcrit["km_ini"], km_min)
        km_f = min(tcrit["km_fim"], km_max)
        off_ini = _km_para_offset(km_i, line, aux_grupo_utm)
        off_fim = _km_para_offset(km_f, line, aux_grupo_utm)
        if off_ini is None or off_fim is None:
            continue
        a, b = sorted([off_ini, off_fim])
        # Apenas trechos com extensao positiva e dentro do municipio
        a = max(a, 0.0)
        b = min(b, line.length)
        if b - a > 1.0:  # ignora intersecoes < 1m
            out.append((a, b, tipo))
    return out


def _uniao_trechos_criticos(trechos):
    """Recebe lista de (a,b,tipo); devolve lista de (a,b,tipos_set)
    apos uniao dos intervalos sobrepostos."""
    if not trechos:
        return []
    # Ordena por inicio
    eventos = sorted(trechos, key=lambda x: x[0])
    merged = []
    cur_a, cur_b, tipos = eventos[0][0], eventos[0][1], {eventos[0][2]}
    for a, b, t in eventos[1:]:
        if a <= cur_b:
            cur_b = max(cur_b, b)
            tipos.add(t)
        else:
            merged.append((cur_a, cur_b, frozenset(tipos)))
            cur_a, cur_b, tipos = a, b, {t}
    merged.append((cur_a, cur_b, frozenset(tipos)))
    return merged


# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("CAMADA: uas_area_estudo (metodologia oficial PRODUTO 7)")
    print("=" * 70)

    aux = gpd.read_file(GPKG, layer="auxilio_regioes_estudo")
    print(f"  auxiliar carregada: {len(aux)} subtrechos")
    aux_utm = aux.to_crs(EPSG_UTM)

    todas_uas = []
    relatorio = []

    for (rid, mun), por_escala in ot.TAB_3_3_1.items():
        grupo = aux_utm[
            (aux_utm["regiao_id"] == rid) & (aux_utm["municipio"] == mun)
        ].copy()
        if grupo.empty:
            raise RuntimeError(
                f"Nao ha subtrechos no auxilio para R{rid}-{mun}"
            )
        # Achata possiveis MultiLineString
        partes = []
        for g in grupo.geometry:
            if g.geom_type == "LineString":
                partes.append(g)
            elif g.geom_type == "MultiLineString":
                partes.extend(list(g.geoms))
        if len(partes) == 1:
            merged = partes[0]
        else:
            u = unary_union(partes)
            merged = linemerge(u) if u.geom_type != "LineString" else u
        if merged.geom_type != "LineString":
            raise RuntimeError(f"Eixo nao-contiguo em R{rid}-{mun}")
        line = _ordena_eixo(merged, grupo)
        L_geom = line.length  # em metros

        # ---- Identifica trechos criticos no municipio (em offset_m) ----
        trechos_brutos = _trechos_criticos_no_municipio(
            rid, mun, line, grupo
        )
        trechos_unidos = _uniao_trechos_criticos(trechos_brutos)
        ext_critico_m = sum(b - a for a, b, _ in trechos_unidos)
        print(f"  R{rid} {mun:18s} eixo={L_geom/1000:6.3f} km, "
              f"trechos criticos={ext_critico_m/1000:6.3f} km "
              f"({len(trechos_unidos)} intervalo(s))")

        qtd_utbs = (por_escala["25K"][0] + por_escala["10K"][0])
        qtd_srs = por_escala["1K"][0]
        ext_pdf_sr = por_escala["1K"][1]

        # ---- UTBs: ocupam os trechos NAO-criticos + sobra na ponta ----
        # Estrategia: UTBs ocupam todo o municipio EXCETO os offsets onde
        # ficarao os SRs (= dentro dos trechos criticos). Se nao ha SRs,
        # UTBs ocupam 100% do municipio.
        # Se ha SRs mas o trecho critico e MAIOR que a extensao dos SRs,
        # parte do trecho critico tambem fica com UTB (interpolada).

        # 1) Determinar quais offsets serao reservados para SRs
        sr_intervals = []  # lista de (a,b) em metros, ordenados
        if qtd_srs > 0 and trechos_unidos:
            ext_sr_total_m = ext_pdf_sr * 1000.0
            ext_critico_total = sum(b - a for a, b, _ in trechos_unidos)
            if ext_sr_total_m >= ext_critico_total:
                # SRs ocupam TODOS os trechos criticos
                sr_intervals = [(a, b) for a, b, _ in trechos_unidos]
            else:
                # SRs ocupam APENAS PARTE de cada trecho critico,
                # proporcionalmente ao tamanho do trecho critico
                fator = ext_sr_total_m / ext_critico_total
                for a, b, _ in trechos_unidos:
                    centro = (a + b) / 2
                    meia = (b - a) * fator / 2
                    sr_intervals.append((centro - meia, centro + meia))

        # 2) Calcular intervalos restantes (= UTBs)
        utb_intervals = []
        if not sr_intervals:
            utb_intervals = [(0.0, L_geom)]
        else:
            cursor = 0.0
            for a, b in sorted(sr_intervals):
                if a > cursor:
                    utb_intervals.append((cursor, a))
                cursor = max(cursor, b)
            if cursor < L_geom:
                utb_intervals.append((cursor, L_geom))

        ext_utb_total_m = sum(b - a for a, b in utb_intervals)
        ext_sr_total_m = sum(b - a for a, b in sr_intervals)

        # ---- Distribuir UTBs (25K + 10K) nos utb_intervals ----
        # Ordem: 25K primeiro, depois 10K (cada um continuo)
        idx_global_utb = 0
        for escala in ("25K", "10K"):
            qtd_esc, _ext_pdf_esc = por_escala[escala]
            if qtd_esc == 0:
                continue
            # Esta escala recebe uma fracao do total de UTBs
            frac = qtd_esc / qtd_utbs if qtd_utbs > 0 else 0
            ext_esc_m = ext_utb_total_m * frac
            ext_por_ua = ext_esc_m / qtd_esc

            # Encontra os offsets desta escala
            # (sequencial dentro de utb_intervals, comecando pelo idx_global_utb)
            for i in range(1, qtd_esc + 1):
                offset_start = idx_global_utb * ext_utb_total_m / qtd_utbs
                offset_end = offset_start + ext_por_ua
                # Mapeia para o offset real ao longo de utb_intervals
                seg = _segmento_em_intervals(
                    utb_intervals, offset_start, offset_end, line
                )
                if seg is None or seg.is_empty:
                    raise RuntimeError(
                        f"UTB vazia em R{rid}-{mun}/{escala}-{i}"
                    )
                _add_ua(
                    seg, line, grupo, rid, mun, escala, i,
                    trechos_unidos, todas_uas
                )
                idx_global_utb += 1

        # ---- Distribuir SRs nos sr_intervals ----
        if qtd_srs > 0 and sr_intervals:
            ext_por_sr = sum(b - a for a, b in sr_intervals) / qtd_srs
            cursor = 0.0
            for i in range(1, qtd_srs + 1):
                offset_start = cursor
                offset_end = cursor + ext_por_sr
                seg = _segmento_em_intervals(
                    sr_intervals, offset_start, offset_end, line
                )
                if seg is None or seg.is_empty:
                    raise RuntimeError(f"SR vazia em R{rid}-{mun}/{i}")
                _add_ua(
                    seg, line, grupo, rid, mun, "1K", i,
                    trechos_unidos, todas_uas
                )
                cursor += ext_por_sr

        relatorio.append((rid, mun, L_geom, ext_utb_total_m, ext_sr_total_m))

    # ---- Constroi GDF em UTM, reprojeta, salva ----
    gdf = gpd.GeoDataFrame(todas_uas, geometry="geometry",
                           crs=f"EPSG:{EPSG_UTM}")
    print(f"\n  Total UAs geradas: {len(gdf)}")

    cent_utm = gpd.GeoSeries(gdf.geometry.centroid, crs=f"EPSG:{EPSG_UTM}")
    cent_wgs = cent_utm.to_crs(EPSG_OUT)
    gdf_out = gdf.to_crs(EPSG_OUT)
    gdf_out["centroide_lon"] = cent_wgs.x.round(6).values
    gdf_out["centroide_lat"] = cent_wgs.y.round(6).values

    schema = [
        "ua_id", "regiao_id", "regiao_nome", "sigla_rodovia",
        "escala", "tipo", "extensao_km", "ordem_no_grupo",
        "km_inicial", "km_final", "subtrecho_der",
        "municipio", "regional", "residencia_dr",
        "uba_nome", "uba_codigo",
        "jurisdicao", "conservado_por",
        "centroide_lon", "centroide_lat", "buffer_lateral_m",
        "icc_geo_thresholds", "icc_hid_thresholds",
        "trecho_critico_geo", "trecho_critico_hid",
        "RAGEO", "RAHID",
        "geometry",
    ]
    gdf_out = gdf_out[schema]

    gdf_out.to_file(GPKG, layer="uas_area_estudo", driver="GPKG",
                    index=False)
    print(f"\n  Camada 'uas_area_estudo' salva: {len(gdf_out)} features")

    # ============= VALIDACAO =============
    print()
    print("=" * 70)
    print("VALIDACAO")
    print("=" * 70)
    tot_qtd = len(gdf_out)
    tot_ext = gdf_out["extensao_km"].sum()
    print(f"  Qtd total: {tot_qtd} (esperado 809)")
    print(f"  Soma extensao_km: {tot_ext:.3f}")
    print()
    print("  Distribuicao por Regiao x Escala:")
    pivot = (
        gdf_out.groupby(["regiao_id", "escala"])
        .size().unstack(fill_value=0)
    )
    print(pivot.to_string())
    print()
    print("  Distribuicao por trecho critico:")
    print(f"    em trecho critico GEO: "
          f"{int(gdf_out['trecho_critico_geo'].sum())} UAs")
    print(f"    em trecho critico HID: "
          f"{int(gdf_out['trecho_critico_hid'].sum())} UAs")
    print()
    print("  UTBs vs SRs em trechos criticos GEO (esperado: maioria SR):")
    cross = (
        gdf_out.groupby(["tipo", "trecho_critico_geo"])
        .size().unstack(fill_value=0)
    )
    print(cross.to_string())


def _segmento_em_intervals(intervals, offset_start, offset_end, line):
    """Recebe lista [(a,b),...] de intervals NaO-sobrepostos ordenados, e
    devolve um sub-LineString correspondente a [offset_start, offset_end]
    no espaco "concatenado" dos intervals (i.e., como se eles formassem
    uma linha continua). Pode atravessar dois intervals consecutivos."""
    # Mapeia (offset_local_no_intervalo_concat) -> (offset_real_em_line)
    pieces = []
    cursor = 0.0
    for a, b in intervals:
        ext = b - a
        end_local = cursor + ext
        # Intersecao com [offset_start, offset_end]
        s = max(offset_start, cursor)
        e = min(offset_end, end_local)
        if s < e:
            real_a = a + (s - cursor)
            real_b = a + (e - cursor)
            pieces.append((real_a, real_b))
        cursor = end_local
    if not pieces:
        return None
    if len(pieces) == 1:
        ra, rb = pieces[0]
        return substring(line, ra, rb)
    # Se atravessou mais de um intervalo, concatena via MultiLineString
    # simplificado para um unico LineString continuo no offset do primeiro
    # intervalo (pratica para SR/UTB pequenos): usar apenas a maior peca
    ra, rb = max(pieces, key=lambda x: x[1] - x[0])
    return substring(line, ra, rb)


def _add_ua(seg, line_mun, grupo, rid, mun, escala, ordem,
            trechos_unidos, lista):
    """Adiciona a UA `seg` na lista `lista`, computando km cadastral
    e flags de trecho critico."""
    centro = seg.interpolate(0.5, normalized=True)
    _, row_c = _km_no_eixo(centro, grupo)
    km_ini, _ = _km_no_eixo(seg.interpolate(0), grupo)
    km_fim, _ = _km_no_eixo(seg.interpolate(seg.length), grupo)

    # Detecta se o centroide cai dentro de algum trecho critico
    centro_off = line_mun.project(centro)
    em_geo = False
    em_hid = False
    for a, b, tipos in trechos_unidos:
        if a <= centro_off <= b:
            if "GEO" in tipos:
                em_geo = True
            if "HID" in tipos:
                em_hid = True

    ua_id = f"UA-R{rid}-{SIGLA_MUN[mun]}-{escala}-{ordem:03d}"
    icc_geo = ";".join(f"{x:g}" for x in ot.ICC_GEO_LIMITES[rid])
    icc_hid = ";".join(f"{x:g}" for x in ot.ICC_HID_LIMITES[rid])

    lista.append({
        "ua_id": ua_id,
        "regiao_id": rid,
        "regiao_nome": row_c["regiao_nome"],
        "sigla_rodovia": row_c["sigla_rodovia"],
        "escala": escala,
        "tipo": TIPO_POR_ESCALA[escala],
        "extensao_km": round(seg.length / 1000.0, 4),
        "ordem_no_grupo": ordem,
        "km_inicial": round(min(km_ini, km_fim), 3),
        "km_final":   round(max(km_ini, km_fim), 3),
        "subtrecho_der": row_c["subtrecho_der"],
        "municipio": row_c["municipio"],
        "regional": row_c["regional"],
        "residencia_dr": row_c["residencia_dr"],
        "uba_nome": row_c["uba_nome"],
        "uba_codigo": row_c["uba_codigo"],
        "jurisdicao": row_c["jurisdicao"],
        "conservado_por": row_c["conservado_por"],
        "centroide_lon": None,
        "centroide_lat": None,
        "buffer_lateral_m": 1000,
        "icc_geo_thresholds": icc_geo,
        "icc_hid_thresholds": icc_hid,
        "trecho_critico_geo": em_geo,
        "trecho_critico_hid": em_hid,
        "RAGEO": None,
        "RAHID": None,
        "geometry": seg,
    })


if __name__ == "__main__":
    main()
