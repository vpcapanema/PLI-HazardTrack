"""POC: calibra georreferencia e inspeciona legenda/malha para Regiao 3."""
import colorsys
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image

ROOT = Path('.')
im = Image.open('_fig_tmp/map_reg3_native.jpeg').convert('RGB')
a = np.asarray(im).astype(int)
H, W, _ = a.shape
gray = a.mean(axis=2)


def centroids(mask_positions, gap=40):
    pos = sorted(mask_positions)
    groups, cur = [], [pos[0]]
    for p in pos[1:]:
        if p - cur[-1] > gap:
            groups.append(sum(cur) / len(cur))
            cur = [p]
        else:
            cur.append(p)
    groups.append(sum(cur) / len(cur))
    return groups


def hsv(rgb):
    r, g, b = [c / 255 for c in rgb]
    return colorsys.rgb_to_hsv(r, g, b)


# Easting ticks: digitos escuros na faixa inferior
botband = gray[H - 18:H, :]
darkx = np.where((botband < 60).sum(axis=0) >= 3)[0]
ex = centroids(darkx, gap=40)
# Northing ticks: faixa esquerda
leftband = gray[:, 0:18]
darky = np.where((leftband < 60).sum(axis=1) >= 3)[0]
ny = centroids(darky, gap=40)
print('easting tick x centers:', [round(v, 1) for v in ex])
print('northing tick y centers:', [round(v, 1) for v in ny])

# Ajuste linear (assume 420000..460000 step 10000 e 7380000..7360000)
E_vals = [420000, 430000, 440000, 450000, 460000]
N_vals = [7380000, 7370000, 7360000]
ex = ex[:5]
ny = ny[:3]
# x = a*E + b
A = np.polyfit(E_vals, ex, 1)
B = np.polyfit(N_vals, ny, 1)
print('fit x=f(E):', A, ' residuo px:',
      [round(ex[i] - (A[0] * E_vals[i] + A[1]), 2) for i in range(5)])
print('fit y=f(N):', B, ' residuo px:',
      [round(ny[i] - (B[0] * N_vals[i] + B[1]), 2) for i in range(3)])
np.save('_fig_tmp/georef_reg3.npy', np.array([A[0], A[1], B[0], B[1]]))

# ---- Cores da legenda (swatches vivos na regiao inferior-esquerda) ----
print('\nlegenda swatches (procura cores vivas col 40..70):')
for y in range(465, 625, 2):
    px = a[y, 45:75].mean(axis=0)
    h, s, v = hsv(px)
    if s > 0.5 and v > 0.4:
        print(f'  y={y} rgb={px.round().astype(int).tolist()} '
              f'hsv=({h * 360:.0f},{s:.2f},{v:.2f})')

# ---- Malha DER ----
shp = ROOT / 'data' / 'der_sistema_rodoviario' / 'MALHA_RODOVIARIA.shp'
gdf = gpd.read_file(shp)
print('\nmalha CRS:', gdf.crs, 'feiçoes:', len(gdf))
print('colunas:', list(gdf.columns))
rods = gdf['Rodovia'].astype(str).str.strip().str.upper()
print('SP 055 trechos:', int((rods == 'SP 055').sum()))
