"""Detecta ticks UTM nas bordas da figura nativa da Regiao 3."""
import numpy as np
from PIL import Image

im = Image.open('_fig_tmp/map_reg3_native.jpeg').convert('RGB')
a = np.asarray(im).astype(int)
H, W, _ = a.shape
print('image', W, 'x', H)

# Os ticks sao marcas escuras (pretas) curtas nas bordas, alinhadas as
# gridlines. Procuramos colunas com pixels muito escuros numa faixa logo
# abaixo do topo (eixo X) e linhas escuras numa faixa a esquerda (eixo Y).

gray = a.mean(axis=2)


def dark_cols(band, thr=60, min_count=3):
    # band: (rows, W) -> colunas com pelo menos min_count pixels < thr
    dark = (band < thr).sum(axis=0)
    cols = np.where(dark >= min_count)[0]
    # agrupa colunas contiguas em centros
    groups = []
    if len(cols):
        start = prev = cols[0]
        for c in cols[1:]:
            if c - prev > 4:
                groups.append((start + prev) // 2)
                start = c
            prev = c
        groups.append((start + prev) // 2)
    return groups


print('\nTOP band rows 0..18 -> easting ticks (x):')
print(dark_cols(gray[0:18, :]))
print('BOTTOM band rows H-18..H -> easting ticks (x):')
print(dark_cols(gray[H-18:H, :]))


def dark_rows(band, thr=60, min_count=3):
    dark = (band < thr).sum(axis=1)
    rows = np.where(dark >= min_count)[0]
    groups = []
    if len(rows):
        start = prev = rows[0]
        for r in rows[1:]:
            if r - prev > 4:
                groups.append((start + prev) // 2)
                start = r
            prev = r
        groups.append((start + prev) // 2)
    return groups


print('\nLEFT band cols 0..18 -> northing ticks (y):')
print(dark_rows(gray[:, 0:18]))
print('RIGHT band cols W-18..W -> northing ticks (y):')
print(dark_rows(gray[:, W-18:W]))
