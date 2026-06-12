"""
Gera as 809 Unidades de Analise (UAs) como poligonos individuais a partir
das figuras oficiais do Produto 7 (2053-R04-21).

Metodo:
1. Limites: Figuras 3.3-2 a 3.3-5 (segmentacao por componentes conexas nas
   figuras de limites; blobs grandes subdivididos por watershed interno).
2. RA: amostra a moda de RA GEO e RA HID dentro de cada poligono nas figuras
   3.3.3-x (sem mesclar UAs, sem calibracao histograma).

Politica: NUNCA mesclar UAs adjacentes com mesmo RA. Cada componente = 1 UA.

Saida: data/ua_zones/ua_zones.geojson (Polygon, EPSG:4326)
"""

import collections
import sys
from pathlib import Path

import fitz
import geopandas as gpd
import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from skimage.feature import peak_local_max
from skimage.measure import find_contours
from skimage.segmentation import watershed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ua_figure_utils import (  # noqa: E402
    classify_ra,
    classify_ra_colored,
    find_pdf,
    georef,
    get_map_image,
    is_ua_fill,
    mode_int,
    px_to_utm,
    utm_to_px,
)

DER_SHP = ROOT / "data" / "der_sistema_rodoviario" / "MALHA_RODOVIARIA.shp"
OUT_DIR = ROOT / "data" / "ua_zones"
FIG_DIR = Path(__file__).resolve().parent / "figuras-diagnostico"

# Paginas PDF (1-based) e indice do mapa na pagina (Fig. 3.3-2..-5)
REGIONS = {
    1: dict(
        rodovia="SP 098", page_bnd=37, bnd_idx=1,
        page_geo=52, page_hid=63,
        E=(350000, 430000), N=(7370000, 7410000), expected=111,
    ),
    2: dict(
        rodovia="SP 055", page_bnd=38, bnd_idx=0,
        page_geo=54, page_hid=65,
        E=(430000, 530000), N=(7370000, 7430000), expected=188,
    ),
    3: dict(
        rodovia="SP 055", page_bnd=38, bnd_idx=1,
        page_geo=56, page_hid=67,
        E=(420000, 460000), N=(7360000, 7380000), expected=355,
    ),
    4: dict(
        rodovia="SP 055", page_bnd=39, bnd_idx=0,
        page_geo=58, page_hid=69,
        E=(360000, 420000), N=(7350000, 7380000), expected=155,
    ),
}

BORDER_DIL = 3
MIN_AREA_PX = 30
MAX_AREA_PX = 1200
WATERSHED_MD = 4


def _split_large_blob(mask: np.ndarray, md: int) -> list:
    dist = ndimage.distance_transform_edt(mask)
    coords = peak_local_max(
        dist, min_distance=md, labels=mask.astype(int), exclude_border=False,
    )
    if len(coords) < 2:
        return [mask]
    markers = np.zeros_like(dist, dtype=int)
    for i, (r, c) in enumerate(coords, 1):
        markers[r, c] = i
    labels = watershed(-dist, markers, mask=mask)
    parts = []
    for i in range(1, labels.max() + 1):
        part = labels == i
        if part.sum() >= MIN_AREA_PX:
            parts.append(part)
    return parts if parts else [mask]


def _masks_from_boundary(arr: np.ndarray) -> list:
    h, w, _ = arr.shape
    fill = np.zeros((h, w), bool)
    for y in range(h):
        for x in range(w):
            fill[y, x] = is_ua_fill(arr[y, x])
    border = arr.mean(axis=2) < 75
    sep = ndimage.binary_dilation(
        border, structure=np.ones((BORDER_DIL, BORDER_DIL), bool),
    )
    mask = fill & ~sep
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 3), bool))
    labeled, n = ndimage.label(mask)
    out = []
    for i in range(1, n + 1):
        m = labeled == i
        area = int(m.sum())
        if area < MIN_AREA_PX:
            continue
        if area <= MAX_AREA_PX:
            out.append(m)
        else:
            out.extend(_split_large_blob(m, WATERSHED_MD))
    return out


def _mask_to_polygon(mask: np.ndarray, gref) -> Polygon | None:
    contours = find_contours(mask.astype(float), 0.5)
    if not contours:
        return None
    contour = max(contours, key=len)
    if len(contour) < 4:
        return None
    ring = [px_to_utm(c[1], c[0], gref) for c in contour]
    ring.append(ring[0])
    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area < 200:
        return None
    return poly.simplify(2.0)


def _ra_in_mask(arr_geo, arr_hid, mask, gref_bnd, gref_geo) -> tuple:
    rg, rh = [], []
    ys, xs = np.where(mask)
    gh, gw, _ = arr_geo.shape
    hh, hw, _ = arr_hid.shape
    for y, x in zip(ys, xs):
        e, n = px_to_utm(x, y, gref_bnd)
        gx, gy = utm_to_px(e, n, gref_geo)
        if not (0 <= gx < gw and 0 <= gy < gh):
            continue
        cg = classify_ra_colored(arr_geo[gy, gx])
        if cg is not None:
            rg.append(cg)
        if 0 <= gx < hw and 0 <= gy < hh:
            ch = classify_ra_colored(arr_hid[gy, gx])
            if ch is not None:
                rh.append(ch)
    if not rg:
        # fallback: centroide com classificador completo
        cy, cx = int(np.mean(ys)), int(np.mean(xs))
        e, n = px_to_utm(cx, cy, gref_bnd)
        gx, gy = utm_to_px(e, n, gref_geo)
        if 0 <= gx < gw and 0 <= gy < gh:
            cg = classify_ra(arr_geo[gy, gx])
            if cg is not None:
                rg.append(cg)
            if 0 <= gx < hw and 0 <= gy < hh:
                ch = classify_ra(arr_hid[gy, gx])
                if ch is not None:
                    rh.append(ch)
    ra_geo = mode_int(rg)
    ra_hid = mode_int(rh)
    if ra_hid is None and ra_geo is not None:
        ra_hid = ra_geo
    present = [v for v in (ra_geo, ra_hid) if v is not None]
    ra = max(present) if present else None
    return ra_geo, ra_hid, ra


def _km_for_polygon(poly: Polygon, gdf_road, rodovia: str) -> float | None:
    sub = gdf_road[gdf_road.Rodovia.str.strip().str.upper() == rodovia]
    if sub.empty:
        return None
    roads = unary_union(sub.geometry.values)
    c = poly.centroid
    nearest = roads.interpolate(roads.project(c))
    best_km, best_d = None, float("inf")
    for _, row in sub.iterrows():
        ln = row.geometry
        d = ln.distance(nearest)
        if d >= best_d:
            continue
        best_d = d
        km0 = row.get("KmInicial")
        km1 = row.get("KmFinal")
        if km0 is None or km1 is None:
            continue
        frac = ln.project(nearest, normalized=True)
        best_km = float(km0) + frac * (float(km1) - float(km0))
    return round(best_km, 2) if best_km is not None else None


def main():
    pdf = find_pdf()
    doc = fitz.open(pdf)
    gdf_road = gpd.read_file(DER_SHP).to_crs(epsg=31983)
    FIG_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    features = []
    stats = {}

    for rid, cfg in REGIONS.items():
        arr_bnd = get_map_image(doc, cfg["page_bnd"], cfg["bnd_idx"])
        arr_geo = get_map_image(doc, cfg["page_geo"])
        arr_hid = get_map_image(doc, cfg["page_hid"])
        gref_bnd = georef(arr_bnd, cfg["E"], cfg["N"])
        gref_geo = georef(arr_geo, cfg["E"], cfg["N"])

        masks = _masks_from_boundary(arr_bnd)
        n_ok = 0
        for mask in masks:
            poly = _mask_to_polygon(mask, gref_bnd)
            if poly is None:
                continue
            ra_geo, ra_hid, ra = _ra_in_mask(
                arr_geo, arr_hid, mask, gref_bnd, gref_geo,
            )
            if ra is None:
                continue
            km = _km_for_polygon(poly, gdf_road, cfg["rodovia"])
            idx = n_ok
            n_ok += 1
            features.append({
                "type": "Feature",
                "properties": {
                    "id": f"UA-R{rid}-{idx:03d}",
                    "regiao": rid,
                    "rodovia": cfg["rodovia"],
                    "km": km,
                    "ra_geo": ra_geo,
                    "ra_hid": ra_hid,
                    "ra": ra,
                    "fonte": "figura",
                    "fonte_geo": "figura",
                    "fonte_hid": "figura",
                },
                "geometry": mapping(poly),
            })
        stats[rid] = dict(n=n_ok, expected=cfg["expected"])
        print(
            f"Regiao {rid}: {n_ok} poligonos "
            f"(esperado Tabela 3.3-1: {cfg['expected']})"
        )

    total = sum(s["n"] for s in stats.values())
    print(f"\nTotal: {total} UAs (esperado 809)")
    exp = sum(s["expected"] for s in stats.values())
    if total != exp:
        print(
            "AVISO: contagem difere do relatorio. "
            "Ajuste BORDER_DIL / MAX_AREA_PX / WATERSHED_MD ou revise figuras."
        )

    gj = gpd.GeoDataFrame.from_features(features, crs="EPSG:31983")
    gj = gj.to_crs(epsg=4326)
    out = OUT_DIR / "ua_zones.geojson"
    gj.to_file(out, driver="GeoJSON")
    print(f"Salvo: {out}")

    c = collections.Counter(f["properties"]["ra"] for f in features)
    print("UAs por RA(max):", dict(sorted(c.items())))


if __name__ == "__main__":
    main()
