"""Analisa vetores e cores de desenho em figura do Produto 7."""
import glob
from collections import Counter

import fitz

pdf = [p for p in glob.glob('**/*PRODUTO 7 Plano*.pdf', recursive=True)
       if 'Tema30' in p][0]
doc = fitz.open(pdf)
pg = doc[55]  # page 56 = Fig 3.3.3-7 Regiao 3 RA GEO

drawings = pg.get_drawings()
print('num drawings:', len(drawings))

# Conta cores de stroke/fill e tipos de item
stroke_colors = Counter()
fill_colors = Counter()
item_types = Counter()
seg_count = 0
for d in drawings:
    sc = d.get('color')
    fc = d.get('fill')
    if sc:
        stroke_colors[tuple(round(c, 2) for c in sc)] += 1
    if fc:
        fill_colors[tuple(round(c, 2) for c in fc)] += 1
    for it in d['items']:
        item_types[it[0]] += 1
        if it[0] in ('l', 'c'):
            seg_count += 1

print('\nstroke colors (rgb 0-1) -> count:')
for c, n in stroke_colors.most_common(20):
    print('  ', c, n)
print('\nfill colors -> count:')
for c, n in fill_colors.most_common(20):
    print('  ', c, n)
print('\nitem types:', dict(item_types))
print('total line/curve segments:', seg_count)

# Tambem checa imagens raster na pagina
print('\nraster images on page:', len(pg.get_images(full=True)))
for img in pg.get_images(full=True):
    print('  xref', img[0], 'w', img[2], 'h', img[3])
