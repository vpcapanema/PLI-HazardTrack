"""
Gera as 809 Unidades de Analise (UAs) como poligonos individuais.

Insumos (todos oficiais):
1. EIXO: malha rodoviaria DER/SP (linhas com KmInicial/KmFinal por trecho)
   - data/der_sistema_rodoviario/MALHA_RODOVIARIA.shp
2. BUFFER: faixa estreita ao longo do eixo (500/3 m por lado, ~333 m total),
   derivada da faixa de 1 km do Produto 7 (2053-R04-21).
3. CORTES POR MUNICIPIO: Tabela 2-1 do Produto 7 (km exatos).
4. CORTES POR ESCALA: transicoes de cor nas Figuras 3.3-2 a 3.3-5
   (rodovia colorida por escala: verde=1:25.000, amarelo=1:10.000,
   laranja=1:1.000/SR), georreferenciadas pelo grid UTM SIRGAS 2000/23S.
5. CONTAGEM: Tabela 3.3-1 - numero oficial de UAs por regiao, municipio
   e escala (total 809).

As figuras NAO desenham as divisas individuais entre UAs vizinhas de
mesma escala. Dentro de cada trecho homogeneo (municipio x escala), as
divisas internas sao INTERPOLADAS uniformemente para reproduzir a
contagem oficial da Tabela 3.3-1. Cada divisa carrega sua proveniencia:
'tabela_2-1', 'figura_escala' ou 'interpolada'.

RA NAO e atribuido aqui (etapa seguinte, figuras 3.3.3-x).

Saida: data/ua_polygons/ua_polygons.geojson (EPSG:4326)
"""

import colorsys
import math
import sys
from pathlib import Path

import fitz
import geopandas as gpd
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ua_figure_utils import (  # noqa: E402
    find_pdf,
    georef,
    get_map_image,
    utm_to_px,
)

DER_SHP = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
OUT_DIR = ROOT / "data" / "ua_polygons"

# Faixa oficial: 500 m por lado; operacional: 1/3 (~167 m por lado)
BUFFER_M = 500.0 / 3.0
STEP_M = 10.0
MAX_AXIS_GAP_M = 500.0
OVERLAP_MIN_M2 = 0.5

# Extents lidos dos ticks do grid de CADA figura 3.3-2..5 (verificados
# visualmente nos overlays _fig_tmp/diag_R*_bnd.png)
REGIONS = {
    1: dict(rodovia="SP 098", km0=62.9, km1=98.1,
            page_bnd=37, bnd_idx=1,
            E=(380000, 400000), N=(7368000, 7386000)),
    2: dict(rodovia="SP 055", km0=53.6, km1=112.55,
            page_bnd=38, bnd_idx=0,
            E=(450000, 490000), N=(7380000, 7404000)),
    3: dict(rodovia="SP 055", km0=112.55, km1=191.4,
            page_bnd=38, bnd_idx=1,
            E=(420000, 460000), N=(7356000, 7380000)),
    4: dict(rodovia="SP 055", km0=191.4, km1=248.1,
            page_bnd=39, bnd_idx=0,
            E=(370000, 420000), N=(7350000, 7380000)),
}

# Tabela 2-1 (Produto 7): limites municipais por km
MUNICIPIOS = {
    1: [("Mogi das Cruzes", 62.9, 75.0),
        ("Biritiba-Mirim", 75.0, 82.4),
        ("Bertioga", 82.4, 98.1)],
    2: [("Ubatuba", 53.6, 81.97),
        ("Caraguatatuba", 81.97, 112.55)],
    3: [("Sao Sebastiao", 112.55, 191.4)],
    4: [("Bertioga", 191.4, 233.4),
        ("Santos", 233.4, 248.1)],
}

# Tabela 3.3-1 (Produto 7): (quantidade, extensao_km) de UAs por
# (regiao, municipio, escala).
# escala: '25K' (UTB 1:25.000), '10K' (UTB 1:10.000), '1K' (SR 1:1.000)
UA_TABLE = {
    (1, "Mogi das Cruzes"): {"25K": (41, 14.28)},
    (1, "Biritiba-Mirim"): {"25K": (22, 8.51), "1K": (5, 0.66)},
    (1, "Bertioga"): {"10K": (11, 5.68), "1K": (32, 5.54)},
    (2, "Ubatuba"): {"10K": (30, 16.40), "1K": (60, 12.85)},
    (2, "Caraguatatuba"): {"10K": (68, 22.32), "1K": (30, 7.19)},
    (3, "Sao Sebastiao"): {"10K": (103, 34.60), "1K": (252, 43.56)},
    (4, "Bertioga"): {"10K": (87, 36.59), "1K": (16, 5.92)},
    (4, "Santos"): {"10K": (36, 11.56), "1K": (16, 3.21)},
}
UA_COUNTS = {k: {e: q for e, (q, _) in v.items()} for k, v in UA_TABLE.items()}
UA_EXT_KM = {k: {e: x for e, (_, x) in v.items()} for k, v in UA_TABLE.items()}

ESCALA_LABEL = {
    "25K": "1:25.000 (UTB)",
    "10K": "1:10.000 (UTB)",
    "1K": "1:1.000 (SR)",
}


def classify_escala(rgb):
    """Cor da legenda 'fase' das Fig. 3.3-2..5 -> escala da UA."""
    r, g, b = [c / 255 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    hd = h * 360
    if v < 0.45 or s < 0.45:
        return None
    if 70 <= hd <= 160:
        return "25K"     # verde
    if 45 <= hd < 70:
        return "10K"     # amarelo
    if hd < 45 or hd >= 350:
        return "1K"      # laranja/vermelho
    return None


def _dist_m_xy(x0, y0, x1, y1):
    return math.hypot(x1 - x0, y1 - y0)


def _run_length_m(run):
    total = 0.0
    for i in range(len(run) - 1):
        _, x0, y0 = run[i]
        _, x1, y1 = run[i + 1]
        total += _dist_m_xy(x0, y0, x1, y1)
    return total


def _segment_lines(gdf, rodovia, km0, km1):
    """Trechos DER (ki, kf, LineString) recortados ao intervalo pedido."""
    sub = gdf[gdf["Rodovia"].astype(str).str.strip().str.upper() == rodovia]
    segments = []
    for _, row in sub.iterrows():
        ki, kf = row.get("KmInicial"), row.get("KmFinal")
        if ki is None or kf is None:
            continue
        ki, kf = float(ki), float(kf)
        if kf < ki:
            ki, kf = kf, ki
        if kf < km0 or ki > km1:
            continue
        geom = row.geometry
        if geom is None:
            continue
        lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for ln in lines:
            if ln.length <= 0:
                continue
            segments.append((ki, kf, ln))
    segments.sort(key=lambda t: (t[0], t[1]))
    return segments


def build_axis_chain(gdf, rodovia, km0, km1):
    """Cadeia (km, x, y) na ordem de percurso — sem reordenar por km."""
    chain = []
    for ki, kf, ln in _segment_lines(gdf, rodovia, km0, km1):
        n = max(1, int(ln.length // STEP_M))
        for i in range(n + 1):
            t = i / n
            km = ki + t * (kf - ki)
            if not (km0 <= km <= km1):
                continue
            p = ln.interpolate(t, normalized=True)
            chain.append((km, p.x, p.y))
    return chain


def extract_axis_coords(chain, km_a, km_b, max_gap_m=MAX_AXIS_GAP_M):
    """Coordenadas UTM do eixo entre km_a e km_b; descarta saltos da malha."""
    sel = [(km, x, y) for km, x, y in chain if km_a <= km <= km_b + 1e-9]
    if len(sel) < 2:
        return []
    runs = []
    cur = [sel[0]]
    for i in range(1, len(sel)):
        _, x0, y0 = sel[i - 1]
        _, x1, y1 = sel[i]
        if _dist_m_xy(x0, y0, x1, y1) > max_gap_m:
            runs.append(cur)
            cur = [sel[i]]
        else:
            cur.append(sel[i])
    runs.append(cur)
    best = max(runs, key=_run_length_m)
    if len(best) < 2:
        return []
    return [(x, y) for _, x, y in best]


def _clean_geom(geom):
    """Repara auto-intersecoes e descarta fragmentos minusculos."""
    if geom is None or geom.is_empty:
        return geom
    geom = geom.buffer(0)
    if geom.is_empty:
        return geom
    if geom.geom_type == "GeometryCollection":
        parts = [
            g for g in geom.geoms
            if g.geom_type in ("Polygon", "MultiPolygon")
            and not g.is_empty and g.area >= OVERLAP_MIN_M2
        ]
        if not parts:
            return Polygon()
        geom = unary_union(parts)
    return geom


def resolve_overlaps(feats, chain):
    """UAs vizinhas: trecho mais a jusante cede area sobreposta."""
    feats.sort(key=lambda f: f["km_ini"])
    for j in range(1, len(feats)):
        gj = _clean_geom(feats[j]["geometry"])
        for i in range(j):
            gi = _clean_geom(feats[i]["geometry"])
            if feats[j]["km_ini"] - feats[i]["km_fim"] > 0.05:
                continue
            if not gi.intersects(gj):
                continue
            gj = _clean_geom(gj.difference(gi))
            if gj.is_empty:
                break
        feats[j]["geometry"] = gj
    return feats


def _buffer_along_axis(coords):
    if len(coords) < 2:
        return None
    poly = LineString(coords).buffer(BUFFER_M, cap_style=2, join_style=2)
    return _clean_geom(poly) if poly is not None and not poly.is_empty else None


def sample_escala(chain, arr, gref, search_px=3):
    """Escala (cor) em cada ponto do eixo; busca o pixel colorido mais
    proximo num raio pequeno (a linha desenhada tem ~3 px de largura)."""
    h, w, _ = arr.shape
    out = []
    for km, x, y in chain:
        px, py = utm_to_px(x, y, gref)
        found = None
        for r in range(search_px + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    qx, qy = px + dx, py + dy
                    if not (0 <= qx < w and 0 <= qy < h):
                        continue
                    c = classify_escala(arr[qy, qx])
                    if c is not None:
                        found = c
                        break
                if found:
                    break
            if found:
                break
        out.append(found)
    return out


def smooth_mode(seq, k=9):
    """Moda em janela k; ignora None; preenche None pelo vizinho."""
    n = len(seq)
    half = k // 2
    out = []
    for i in range(n):
        win = [seq[j] for j in range(max(0, i - half), min(n, i + half + 1))
               if seq[j] is not None]
        if not win:
            out.append(None)
            continue
        from collections import Counter
        cnt = Counter(win)
        out.append(cnt.most_common(1)[0][0])
    # preenche None remanescentes pelo ultimo valor valido
    last = None
    for i in range(n):
        if out[i] is None:
            out[i] = last
        else:
            last = out[i]
    last = None
    for i in range(n - 1, -1, -1):
        if out[i] is None:
            out[i] = last
        else:
            last = out[i]
    return out


def runs_by_escala(chain, escalas, km0, km1, min_run_m=150.0):
    """Trechos contiguos de mesma escala [(escala, km_a, km_b)].
    Runs muito curtos (ruido de classificacao) sao absorvidos pelo
    vizinho maior."""
    runs = []
    for (km, _, _), esc in zip(chain, escalas):
        if not (km0 <= km <= km1):
            continue
        if runs and runs[-1][0] == esc:
            runs[-1][2] = km
        else:
            runs.append([esc, km, km])
    # absorve ruido
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (esc, a, b) in enumerate(runs):
            if (b - a) * 1000 >= min_run_m:
                continue
            j = i - 1 if i > 0 else i + 1
            if i > 0 and i + 1 < len(runs):
                la = runs[i - 1][2] - runs[i - 1][1]
                lb = runs[i + 1][2] - runs[i + 1][1]
                j = i - 1 if la >= lb else i + 1
            if j < i:
                runs[j][2] = b
            else:
                runs[j][1] = a
            runs.pop(i)
            changed = True
            break
    # funde adjacentes iguais apos absorcao
    merged = []
    for esc, a, b in runs:
        if merged and merged[-1][0] == esc:
            merged[-1][2] = b
        else:
            merged.append([esc, a, b])
    return [(e, a, b) for e, a, b in merged]


def absorb_foreign_runs(runs, allowed):
    """Runs de escala ausente na Tabela 3.3-1 do municipio (ruido de
    classificacao) sao absorvidos pelo vizinho mais longo."""
    runs = [list(r) for r in runs]
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (esc, a, b) in enumerate(runs):
            if esc in allowed:
                continue
            cands = [j for j in (i - 1, i + 1) if 0 <= j < len(runs)]
            j = max(cands, key=lambda j: runs[j][2] - runs[j][1])
            if j < i:
                runs[j][2] = b
            else:
                runs[j][1] = a
            runs.pop(i)
            changed = True
            break
    merged = []
    for esc, a, b in runs:
        if merged and merged[-1][0] == esc:
            merged[-1][2] = b
        else:
            merged.append([esc, a, b])
    return [(e, a, b) for e, a, b in merged]


def distribute(counts, runs):
    """Distribui n UAs (por escala) entre os runs daquela escala,
    proporcional ao comprimento (maior resto), minimo 1 por run."""
    plan = []   # (escala, km_a, km_b, n_uas)
    for esc, n_target in counts.items():
        sel = [(a, b) for e, a, b in runs if e == esc]
        if not sel:
            # figura nao mostra a escala neste municipio: usa o
            # municipio inteiro como 1 run (divisas todas interpoladas)
            sel = [(min(a for _, a, _ in runs),
                    max(b for _, _, b in runs))] if runs else []
            if not sel:
                continue
        total = sum(b - a for a, b in sel)
        if total <= 0:
            continue
        raw = [(b - a) / total * n_target for a, b in sel]
        base = [max(1, int(r)) for r in raw]
        # ajusta para somar exatamente n_target
        while sum(base) > n_target:
            i = max(range(len(base)),
                    key=lambda i: base[i] - raw[i] if base[i] > 1 else -9e9)
            base[i] -= 1
        rema = [r - b for r, b in zip(raw, base)]
        while sum(base) < n_target:
            i = max(range(len(rema)), key=lambda i: rema[i])
            base[i] += 1
            rema[i] = -9e9
        for (a, b), n in zip(sel, base):
            plan.append((esc, a, b, n))
    return plan


def cut_polygons(chain, plan, municipio):
    """Subdivide cada run em n UAs; cortes no meio entre vizinhas."""
    specs = []
    for esc, a, b, n in plan:
        width = (b - a) / n
        for i in range(n):
            ka = a + i * width
            kb = a + (i + 1) * width
            specs.append(dict(
                escala=esc, municipio=municipio,
                km_ini=round(ka, 3), km_fim=round(kb, 3),
                divisa_ini=("figura_escala" if i == 0 else "interpolada"),
            ))
    specs.sort(key=lambda s: s["km_ini"])

    feats = []
    for idx, spec in enumerate(specs):
        km_lo = spec["km_ini"] if idx == 0 else (
            (specs[idx - 1]["km_fim"] + spec["km_ini"]) / 2
        )
        km_hi = spec["km_fim"] if idx == len(specs) - 1 else (
            (spec["km_fim"] + specs[idx + 1]["km_ini"]) / 2
        )
        coords = extract_axis_coords(chain, km_lo, km_hi)
        poly = _buffer_along_axis(coords)
        if poly is None:
            continue
        feats.append(spec | dict(geometry=poly))

    return feats


def finalize_region_uas(feats, chain):
    """Limpa geometrias e remove sobreposicao residual na regiao."""
    feats = resolve_overlaps(feats, chain)
    kept = []
    for f in feats:
        geom = _clean_geom(f["geometry"])
        if geom is None or geom.is_empty or geom.area < OVERLAP_MIN_M2:
            continue
        kept.append(f | dict(geometry=geom))
    return kept


def main():
    doc = fitz.open(find_pdf())
    gdf = gpd.read_file(DER_SHP).to_crs(epsg=31983)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    features = []
    print(f"Buffer: {BUFFER_M:.0f} m por lado "
          f"(~{2 * BUFFER_M:.0f} m total, 1/3 da faixa oficial)\n")

    for rid, cfg in REGIONS.items():
        chain = build_axis_chain(gdf, cfg["rodovia"], cfg["km0"], cfg["km1"])
        if len(chain) < 2:
            print(f"Regiao {rid}: eixo vazio")
            continue
        arr = get_map_image(doc, cfg["page_bnd"], cfg["bnd_idx"])
        gref = georef(arr, cfg["E"], cfg["N"])
        escalas = smooth_mode(sample_escala(chain, arr, gref))

        n_reg = 0
        reg_feats = []
        for municipio, m0, m1 in MUNICIPIOS[rid]:
            counts = UA_COUNTS.get((rid, municipio), {})
            if not counts:
                continue
            runs = runs_by_escala(chain, escalas, m0, m1)
            runs = absorb_foreign_runs(runs, set(counts))
            plan = distribute(counts, runs)
            feats = cut_polygons(chain, plan, municipio)
            # primeira divisa do municipio vem da Tabela 2-1
            if feats:
                feats[0]["divisa_ini"] = "tabela_2-1"
            target = sum(counts.values())
            got = len(feats)
            n_reg += got
            print(f"  R{rid} {municipio}: alvo={target} gerado={got}")
            # validacao: extensao gerada vs extensao oficial (Tab. 3.3-1)
            ext_ofic = UA_EXT_KM[(rid, municipio)]
            for esc in counts:
                ger = sum(f["km_fim"] - f["km_ini"] for f in feats
                          if f["escala"] == esc)
                ofic = ext_ofic.get(esc, 0.0)
                medio_ger = ger / counts[esc] * 1000
                medio_ofic = ofic / counts[esc] * 1000
                print(f"    {esc}: ext gerada={ger:.2f} km "
                      f"oficial={ofic:.2f} km | media/UA "
                      f"gerada={medio_ger:.0f} m oficial={medio_ofic:.0f} m")
            for f in feats:
                ofic_m = (ext_ofic.get(f["escala"], 0.0)
                          / counts[f["escala"]] * 1000)
                reg_feats.append(f | dict(
                    regiao=rid, rodovia=cfg["rodovia"],
                    ext_oficial_media_m=round(ofic_m, 0),
                ))
        reg_feats = finalize_region_uas(reg_feats, chain)
        n_reg = len(reg_feats)
        print(f"Regiao {rid}: {n_reg} UAs\n")
        features.extend(reg_feats)

    # numera sequencialmente por regiao/km
    features.sort(key=lambda f: (f["regiao"], f["km_ini"]))
    out_feats = []
    seq = {}
    for f in features:
        rid = f["regiao"]
        seq[rid] = seq.get(rid, 0) + 1
        out_feats.append({
            "type": "Feature",
            "properties": {
                "id": f"UA-R{rid}-{seq[rid]:03d}",
                "regiao": rid,
                "rodovia": f["rodovia"],
                "municipio": f["municipio"],
                "escala": ESCALA_LABEL[f["escala"]],
                "km_ini": f["km_ini"],
                "km_fim": f["km_fim"],
                "km": round((f["km_ini"] + f["km_fim"]) / 2, 3),
                "extensao_m": round((f["km_fim"] - f["km_ini"]) * 1000, 0),
                "ext_oficial_media_m": f["ext_oficial_media_m"],
                "divisa_ini": f["divisa_ini"],
                "ra_geo": None, "ra_hid": None, "ra": None,
                "fonte": "tabela_3.3-1+figura_3.3-x",
            },
            "geometry": mapping(f["geometry"]),
        })

    print(f"Total: {len(out_feats)} UAs (Tabela 3.3-1: 809)")
    gj = gpd.GeoDataFrame.from_features(out_feats, crs="EPSG:31983")
    gj = gj.to_crs(epsg=4326)
    out = OUT_DIR / "ua_polygons.geojson"
    gj.to_file(out, driver="GeoJSON")
    print(f"Salvo: {out}")


if __name__ == "__main__":
    main()
