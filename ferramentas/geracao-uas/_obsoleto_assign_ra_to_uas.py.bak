"""
Atribui RA GEO e RA HID as 809 UAs (ua_polygons.geojson).

Metodo (4 passos):
1. Amostragem nas figuras 3.3.3-x (cor -> classe) ao longo do km de cada UA
2. Regularizacao Tobler (lacunas/ruido; transicoes reais preservadas)
3. Alocacao por ranking com orcamento oficial (Tab. 3.3.1-2 / 3.3.2-2)
4. Validacao nos trechos criticos (Tab. 3.3.3.1-3/-4 via ra_official)

Saida: data/ua_zones/ua_geo.geojson + ua_hidro.geojson (EPSG:4326)
"""

import sys
from collections import Counter
from pathlib import Path

import fitz
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "ferramentas" / "relatorios-plano-contingencia"))

from ra_official import RA_GEO_BY_SEGMENT, RA_HID_BY_SEGMENT  # noqa: E402
from ua_figure_utils import (  # noqa: E402
    classify_ra,
    classify_ra_colored,
    find_pdf,
    georef,
    get_map_image,
    utm_to_px,
)
from ua_ra_budgets import (  # noqa: E402
    ESCALA_TO_KEY,
    RA_FIGURES,
    RA_GEO_BUDGET,
    RA_HID_BUDGET,
)
from build_ua_polygons import (  # noqa: E402
    DER_SHP,
    REGIONS,
    build_axis_chain,
)
from export_ua_split import export_split  # noqa: E402

IN_PATH = ROOT / "data" / "ua_polygons" / "ua_polygons.geojson"
OUT_GEO = ROOT / "data" / "ua_zones" / "ua_geo.geojson"
OUT_HIDRO = ROOT / "data" / "ua_zones" / "ua_hidro.geojson"
SAMPLE_STEP_KM = 0.05
SEARCH_PX = 3
TOBLER_CONF = 0.35


def _hist_score(hist: Counter) -> tuple:
    """Retorna (score 0-4, confianca 0-1, moda ou None)."""
    tot = sum(hist.values())
    if tot == 0:
        return 0.0, 0.0, None
    moda = max(hist, key=lambda c: (hist[c], c))
    score = sum(c * hist[c] for c in hist) / tot
    return score, min(1.0, tot / 20.0), moda


def sample_ra_along_km(chain, km0, km1, arr, gref):
    """Histograma de classes RA no intervalo [km0, km1]."""
    hist = Counter()
    for km, x, y in chain:
        if km < km0 - 1e-6 or km > km1 + 1e-6:
            continue
        px, py = utm_to_px(x, y, gref)
        h, w, _ = arr.shape
        found = None
        for r in range(SEARCH_PX + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    qx, qy = px + dx, py + dy
                    if not (0 <= qx < w and 0 <= qy < h):
                        continue
                    c = classify_ra_colored(arr[qy, qx])
                    if c is None:
                        c = classify_ra(arr[qy, qx])
                    if c is not None:
                        found = c
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is not None:
            hist[found] += 1
    return hist


def tobler_smooth(scores, confs, modas):
    """Preenche lacunas e corrige ruído isolado (vizinhos concordantes)."""
    n = len(scores)
    out_s = list(scores)
    out_c = list(confs)
    out_m = list(modas)
    # preenchimento por vizinho
    for i in range(n):
        if out_c[i] >= TOBLER_CONF:
            continue
        nb = []
        for j in (i - 1, i + 1):
            if 0 <= j < n and out_c[j] >= TOBLER_CONF:
                nb.append(out_s[j])
        if nb:
            out_s[i] = sum(nb) / len(nb)
            out_c[i] = 0.5
            out_m[i] = int(round(out_s[i]))
    # ruído: leitura destoa dos dois vizinhos que concordam
    for i in range(1, n - 1):
        if out_c[i] < TOBLER_CONF:
            continue
        l, r = out_s[i - 1], out_s[i + 1]
        if abs(l - r) <= 1.0 and abs(out_s[i] - l) > 1.5:
            if out_c[i - 1] >= out_c[i + 1]:
                out_s[i] = l
            else:
                out_s[i] = r
            out_m[i] = int(round(out_s[i]))
            out_c[i] = min(out_c[i], 0.6)
    return out_s, out_c, out_m


def allocate_by_rank(scores, budget: dict) -> list:
    """Atribui classes conforme orcamento; maiores scores -> classes altas."""
    n = len(scores)
    target = sum(budget.values())
    if n == 0:
        return []
    if target != n:
        raise ValueError(f"orcamento {target} != n_uas {n}")
    order = sorted(range(n), key=lambda i: scores[i], reverse=True)
    out = [0] * n
    idx = 0
    for cls in (4, 3, 2, 1, 0):
        for _ in range(budget.get(cls, 0)):
            if idx >= n:
                break
            out[order[idx]] = cls
            idx += 1
    return out


def validate_critical(gdf):
    """Compara distribuicao gerada vs ra_official nos trechos criticos."""
    print("\n=== Validacao trechos criticos (Tab. 3.3.3.1-3/-4) ===")
    for segmap, col, label in (
        (RA_GEO_BY_SEGMENT, "ra_geo", "GEO"),
        (RA_HID_BY_SEGMENT, "ra_hid", "HID"),
    ):
        for (rod, k0, k1), data in segmap.items():
            sub = gdf[
                (gdf.rodovia.str.strip().str.upper() == rod)
                & (gdf.km >= k0 - 0.5)
                & (gdf.km <= k1 + 0.5)
            ]
            if sub.empty:
                continue
            got = Counter(sub[col].astype(int).tolist())
            exp = data["dist"]
            exp_n = sum(exp.values())
            got_n = len(sub)
            print(f"  {label} {rod} km{k0}-{k1}: "
                  f"n_ua={got_n} (ref {exp_n} UAs no trecho)")
            for c in range(5):
                g = got.get(c, 0)
                e = exp.get(c, 0)
                if e or g:
                    print(f"    RA{c}: gerado={g} oficial={e}")


def continuity_metric(gdf, col):
    """Fracao de pares vizinhos (mesma regiao+escala) com |dRA|<=1."""
    ok = tot = 0
    for (_, esc), grp in gdf.sort_values("km_ini").groupby(
            ["regiao", "escala"]):
        vals = grp[col].astype(int).tolist()
        for i in range(len(vals) - 1):
            tot += 1
            if abs(vals[i + 1] - vals[i]) <= 1:
                ok += 1
    return ok / tot if tot else 0.0


def main():
    if not IN_PATH.exists():
        print(f"Arquivo nao encontrado: {IN_PATH}")
        print("Rode scripts/build_ua_polygons.py primeiro.")
        return

    gdf = gpd.read_file(IN_PATH).to_crs(epsg=31983)
    doc = fitz.open(find_pdf())
    road = gpd.read_file(DER_SHP).to_crs(epsg=31983)

    chains = {}
    grefs = {}
    for rid, cfg in REGIONS.items():
        chains[rid] = build_axis_chain(
            road, cfg["rodovia"], cfg["km0"], cfg["km1"],
        )
        rf = RA_FIGURES[rid]
        grefs[rid] = {
            "geo": georef(
                get_map_image(doc, rf["page_geo"]),
                rf["E"], rf["N"],
            ),
            "hid": georef(
                get_map_image(doc, rf["page_hid"]),
                rf["E"], rf["N"],
            ),
            "arr_geo": get_map_image(doc, rf["page_geo"]),
            "arr_hid": get_map_image(doc, rf["page_hid"]),
        }

    for channel in ("geo", "hid"):
        budget_map = RA_GEO_BUDGET if channel == "geo" else RA_HID_BUDGET
        col = f"ra_{channel}"
        col_leitura = f"ra_{channel}_leitura"
        col_fonte = f"ra_{channel}_fonte"
        col_conf = f"ra_{channel}_conf"

        for (rid, escala_key), budget in sorted(budget_map.items()):
            mask = (
                (gdf.regiao == rid)
                & (gdf.escala.map(ESCALA_TO_KEY) == escala_key)
            )
            sub = gdf[mask].sort_values("km_ini")
            if sub.empty:
                continue
            idxs = sub.index.tolist()
            scores, confs, modas = [], [], []
            chain = chains[rid]
            gr = grefs[rid]
            arr = gr[f"arr_{channel}"]
            gref = gr[channel]

            for _, row in sub.iterrows():
                hist = sample_ra_along_km(
                    chain, row.km_ini, row.km_fim, arr, gref,
                )
                sc, cf, mo = _hist_score(hist)
                scores.append(sc)
                confs.append(cf)
                modas.append(mo)

            scores, confs, modas = tobler_smooth(scores, confs, modas)
            assigned = allocate_by_rank(scores, budget)

            for i, ix in enumerate(idxs):
                gdf.at[ix, col] = assigned[i]
                gdf.at[ix, col_leitura] = modas[i]
                gdf.at[ix, col_conf] = round(confs[i], 2)
                if confs[i] >= TOBLER_CONF and modas[i] is not None:
                    src = "figura"
                elif assigned[i] == modas[i]:
                    src = "figura+ranking"
                else:
                    src = "ranking"
                gdf.at[ix, col_fonte] = src

            got = Counter(assigned)
            print(f"R{rid} {escala_key} {channel}: "
                  f"budget={budget} got={dict(got)}")

    gdf["ra"] = gdf[["ra_geo", "ra_hid"]].max(axis=1)
    gdf["fonte"] = "tabela_3.3.1-2+figura_3.3.3"

    geo_cont = continuity_metric(gdf, "ra_geo")
    hid_cont = continuity_metric(gdf, "ra_hid")
    print(f"\nContinuidade Tobler (|dRA|<=1): GEO={geo_cont:.1%} "
          f"HID={hid_cont:.1%}")

    validate_critical(gdf)

    out = gdf.to_crs(epsg=4326)
    out.to_file(IN_PATH, driver="GeoJSON")
    export_split(out)
    print(f"\nSalvo: {IN_PATH}")


if __name__ == "__main__":
    main()
