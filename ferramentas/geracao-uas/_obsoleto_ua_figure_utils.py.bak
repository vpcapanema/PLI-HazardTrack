"""
Utilitarios compartilhados para digitalizacao das figuras do Produto 7.
"""

import io
import colorsys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def find_pdf() -> Path:
    return next(
        p for p in ROOT.glob("**/*PRODUTO 7 Plano*.pdf") if "Tema30" in str(p)
    )


def classify_ra(rgb) -> Optional[int]:
    """Classe RA0..RA4 a partir da cor do pixel (legenda Produto 7)."""
    r, g, b = [c / 255 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    hd = h * 360
    if v < 0.5:
        return None
    if 290 <= hd <= 350 and s > 0.30:
        return None
    if s < 0.35:
        return 0 if v > 0.65 else None
    if hd <= 12 or hd >= 350:
        return 4 if s > 0.6 else None
    if 12 < hd < 45:
        return 3
    if 45 <= hd < 70:
        return 2
    if 70 <= hd < 160:
        return 1
    return None


def classify_ra_colored(rgb) -> Optional[int]:
    """RA em pixels claramente coloridos (ignora cinza de fundo do mapa)."""
    r, g, b = [c / 255 for c in rgb]
    _, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v < 0.5 or s < 0.35:
        return None
    return classify_ra(rgb)


def is_ua_fill(rgb) -> bool:
    """Pixel preenchido (UA) nas figuras de limites 3.3-x."""
    g = float(np.mean(rgb))
    if g < 75:
        return False
    r, g, b = rgb / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v > 0.93 and s < 0.12:
        return False
    if 290 <= h * 360 <= 350 and s > 0.25:
        return False
    if v < 0.4:
        return False
    return True


def _centroids(positions, gap=40):
    pos = sorted(int(p) for p in positions)
    groups, cur = [], [pos[0]]
    for p in pos[1:]:
        if p - cur[-1] > gap:
            groups.append(sum(cur) / len(cur))
            cur = [p]
        else:
            cur.append(p)
    groups.append(sum(cur) / len(cur))
    return groups


def georef(arr, eminmax, nminmax) -> Tuple[float, float, float, float]:
    """Ajuste linear pixel <-> UTM pelos ticks extremos do grid."""
    h, _, _ = arr.shape
    gray = arr.mean(axis=2)
    ex = _centroids(np.where((gray[h - 18:h, :] < 60).sum(axis=0) >= 3)[0])
    ny = _centroids(np.where((gray[:, 0:18] < 60).sum(axis=1) >= 3)[0])
    x_lo, x_hi = min(ex), max(ex)
    y_lo, y_hi = min(ny), max(ny)
    gx0 = (x_hi - x_lo) / (eminmax[1] - eminmax[0])
    gx1 = x_lo - gx0 * eminmax[0]
    gy0 = (y_hi - y_lo) / (nminmax[0] - nminmax[1])
    gy1 = y_lo - gy0 * nminmax[1]
    return gx0, gx1, gy0, gy1


def px_to_utm(col, row, gref):
    gx0, gx1, gy0, gy1 = gref
    return (col - gx1) / gx0, (row - gy1) / gy0


def utm_to_px(e, n, gref):
    gx0, gx1, gy0, gy1 = gref
    return int(round(gx0 * e + gx1)), int(round(gy0 * n + gy1))


def get_map_image(doc, pno, img_idx=-1):
    """Extrai mapa RGB da pagina (img_idx=-1 = maior imagem)."""
    pg = doc[pno - 1]
    items = []
    for img in pg.get_images(full=True):
        xref, w, h = img[0], img[2], img[3]
        if h < 300:
            continue
        rects = pg.get_image_rects(xref)
        if not rects:
            continue
        y0 = rects[0].y0
        ext = doc.extract_image(xref)
        pil = Image.open(io.BytesIO(ext["image"])).convert("RGB")
        items.append((y0, w * h, np.asarray(pil).astype(int)))
    if not items:
        raise ValueError(f"nenhuma imagem de mapa na pagina {pno}")
    items.sort(key=lambda t: t[0])
    if img_idx < 0:
        return max(items, key=lambda t: t[1])[2]
    return items[img_idx][2]


def mode_int(values: List[int]) -> Optional[int]:
    if not values:
        return None
    from collections import Counter
    cnt = Counter(values)
    top = max(cnt.values())
    return max(c for c, n in cnt.items() if n == top)
