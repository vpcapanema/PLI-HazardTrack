"""POC: amostra RA por cor na malha DER sobre figura da Regiao 3."""
import colorsys
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString

ROOT = Path('.')
gx0, gx1, gy0, gy1 = np.load('_fig_tmp/georef_reg3.npy')  # x=gx0*E+gx1; y=gy0*N+gy1
im = Image.open('_fig_tmp/map_reg3_native.jpeg').convert('RGB')
a = np.asarray(im).astype(int)
H, W, _ = a.shape

# Cores de RA por matiz (legenda). Hue em graus.
# RA1 verde-lima ~79 (confirmado), RA2 amarelo ~55, RA3 laranja ~33, RA4 vermelho ~5
RA_COLORS = {1: (157, 226, 8), 2: (255, 255, 0),
             3: (245, 150, 30), 4: (235, 28, 36), 0: (190, 190, 190)}


def classify(rgb):
    r, g, b = [c / 255 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    hd = h * 360
    if v < 0.5:
        return None              # satelite escuro
    # magenta/rosa do limite da regiao -> excluir (faixa ampla)
    if 290 <= hd <= 350 and s > 0.30:
        return None
    if s < 0.35:
        return 0 if v > 0.65 else None   # cinza = RA0
    if hd <= 12 or hd >= 350:
        # vermelho estrito (evita rosa/magenta): exige saturacao alta
        return 4 if s > 0.6 else None
    if 12 < hd < 45:
        return 3                 # laranja
    if 45 <= hd < 70:
        return 2                 # amarelo
    if 70 <= hd < 160:
        return 1                 # verde-lima
    return None                  # azul/ciano (agua) etc.


def sample(east_utm, north_utm, win=2):
    pix_col = int(round(gx0 * east_utm + gx1))
    pix_row = int(round(gy0 * north_utm + gy1))
    if pix_col < 2 or pix_row < 2 or pix_col >= W - 2 or pix_row >= H - 2:
        return None, pix_col, pix_row
    if pix_col < 245 and pix_row > 430:      # ignora caixa da legenda
        return None, pix_col, pix_row
    votes = {}
    for dy in range(-win, win + 1):
        for dx in range(-win, win + 1):
            c = classify(a[pix_row + dy, pix_col + dx])
            if c is not None:
                votes[c] = votes.get(c, 0) + 1
    if not votes:
        return None, pix_col, pix_row
    # voto majoritario (robusto a artefatos JPEG nas bordas)
    best = max(votes, key=lambda key: votes[key])
    return best, pix_col, pix_row


# Bounds UTM da figura
E_MIN, E_MAX = 415000, 465000
N_MIN, N_MAX = 7355000, 7385000

gdf = gpd.read_file(ROOT / 'data' / 'der_sistema_rodoviario' / 'MALHA_RODOVIARIA.shp')
gdf = gdf.to_crs(epsg=31983)
rods = gdf['Rodovia'].astype(str).str.strip().str.upper()
sp055 = gdf[rods == 'SP 055'].copy()

pts = []  # (E,N,km)
for _, gdf_row in sp055.iterrows():
    geom = gdf_row.geometry
    if geom is None:
        continue
    lines = geom.geoms if geom.geom_type == 'MultiLineString' else [geom]
    for ln in lines:
        if not isinstance(ln, LineString):
            continue
        L = ln.length
        n = max(2, int(L // 20))
        for i in range(n + 1):
            p = ln.interpolate(i / n, normalized=True)
            if E_MIN <= p.x <= E_MAX and N_MIN <= p.y <= N_MAX:
                pts.append((p.x, p.y))

print('pontos densificados na bbox da figura:', len(pts))

# fundo escurecido para destacar as cores classificadas
bg = (np.asarray(im).astype(float) * 0.35).astype('uint8')
canvas = Image.fromarray(bg)
draw = ImageDraw.Draw(canvas)
OUT = {0: (190, 190, 190), 1: (60, 230, 30), 2: (255, 240, 0),
       3: (255, 140, 0), 4: (255, 0, 0)}
counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, None: 0}
for e_utm, n_utm in pts:
    cls, px, py = sample(e_utm, n_utm)
    counts[cls] = counts.get(cls, 0) + 1
    if cls is not None:
        draw.ellipse([px - 2, py - 2, px + 2, py + 2], fill=OUT[cls])

canvas.save('_fig_tmp/overlay_reg3.png')
print('classes amostradas:', {k: counts[k] for k in [0, 1, 2, 3, 4, None]})
tot = sum(counts[k] for k in [0, 1, 2, 3, 4])
if tot:
    print('proporcoes (entre amostrados com cor):',
          {k: f'{100*counts[k]/tot:.1f}%' for k in [0, 1, 2, 3, 4]})
print('overlay salvo: _fig_tmp/overlay_reg3.png')
