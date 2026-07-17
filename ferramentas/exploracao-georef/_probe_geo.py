"""Inspeciona georreferencia UTM de figura do Produto 7 via rotulos do PDF."""
import glob
import re

import fitz

pdf = [p for p in glob.glob('**/*PRODUTO 7 Plano*.pdf', recursive=True)
       if 'Tema30' in p][0]
doc = fitz.open(pdf)
pg = doc[55]  # page 56 Fig 3.3.3-7

# Retangulo (em coords de pagina, pt) onde a imagem do mapa esta colocada
for xref in (299,):
    rects = pg.get_image_rects(xref)
    print('xref', xref, 'rects:', rects)

# Palavras numericas (rotulos UTM) e suas posicoes
words = pg.get_text('words')  # (x0,y0,x1,y1, word, block, line, wordno)
print('\nrotulos numericos (UTM candidatos):')
for w in words:
    txt = w[4]
    if re.fullmatch(r'\d{6,7}', txt):
        cx = (float(w[0]) + float(w[2])) / 2
        cy = (float(w[1]) + float(w[3])) / 2
        print(f'  {txt:>8}  cx={cx:7.1f} cy={cy:7.1f}')
