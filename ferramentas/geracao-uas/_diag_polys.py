"""Diagnostico: poligonos UA gerados sobre as figuras 3.3-x (temporario)."""
import sys
from pathlib import Path

import fitz
import geopandas as gpd
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ua_figure_utils import find_pdf, georef, get_map_image, utm_to_px
from build_ua_polygons import REGIONS

FIG = Path(__file__).resolve().parent / "figuras-diagnostico"
doc = fitz.open(find_pdf())
gj = gpd.read_file(ROOT / "data/ua_polygons/ua_polygons.geojson")
gj = gj.to_crs(epsg=31983)

COLORS = {"1:25.000 (UTB)": (0, 255, 0), "1:10.000 (UTB)": (0, 120, 255),
          "1:1.000 (SR)": (255, 0, 255)}

for rid, cfg in REGIONS.items():
    arr = get_map_image(doc, cfg["page_bnd"], cfg["bnd_idx"])
    gref = georef(arr, cfg["E"], cfg["N"])
    h, w, _ = arr.shape
    img = Image.fromarray(arr.astype(np.uint8))
    draw = ImageDraw.Draw(img)
    sub = gj[gj.regiao == rid]
    for _, row in sub.iterrows():
        col = COLORS.get(row.escala, (255, 255, 255))
        geoms = (row.geometry.geoms
                 if row.geometry.geom_type == "MultiPolygon"
                 else [row.geometry])
        for g in geoms:
            pts = [utm_to_px(x, y, gref) for x, y in g.exterior.coords]
            pts = [(x, y) for x, y in pts if 0 <= x < w and 0 <= y < h]
            if len(pts) >= 2:
                draw.line(pts + [pts[0]], fill=col, width=1)
    out = FIG / f"diag_polys_R{rid}.png"
    img.save(out)
    print(f"R{rid}: {len(sub)} UAs -> {out.name}")
