"""Recorte ampliado de figura do Produto 7 para inspecao de cores."""
import glob

import fitz

pdf = [p for p in glob.glob('**/*PRODUTO 7 Plano*.pdf', recursive=True)
       if 'Tema30' in p][0]
doc = fitz.open(pdf)
pg = doc[55]  # page 56 Fig 3.3.3-7 Regiao 3

# Recorte na regiao costeira (onde ha transicao de cores na rodovia),
# renderizado em alta amplificacao para ver a resolucao real.
# clip em coords de pagina (pt). Mapa rect ~ (111,78)-(730,489).
clip = fitz.Rect(330, 360, 560, 470)
pix = pg.get_pixmap(matrix=fitz.Matrix(10, 10), clip=clip)
pix.save('_fig_tmp/zoom_reg3_coast.png')
print('saved', pix.width, 'x', pix.height)
