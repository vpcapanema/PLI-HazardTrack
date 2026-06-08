"""Renderiza paginas do PDF do Produto 7 em PNG para inspecao."""
import glob
import os
import sys

import fitz

pdfs = glob.glob('**/*PRODUTO 7 Plano*.pdf', recursive=True)
pdf = [p for p in pdfs if 'Tema30' in p][0]
doc = fitz.open(pdf)
print('pdf:', pdf)
print('paginas:', doc.page_count)

os.makedirs('_fig_tmp', exist_ok=True)
# paginas 1-based conforme marcadores do texto extraido
pages = [int(x) for x in sys.argv[1:]] or [56]
for p1 in pages:
    pg = doc[p1 - 1]
    pix = pg.get_pixmap(matrix=fitz.Matrix(4, 4))
    out = f'_fig_tmp/page_{p1}.png'
    pix.save(out)
    print('saved', out, pix.width, 'x', pix.height)
