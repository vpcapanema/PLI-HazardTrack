"""Extrai imagem nativa do mapa de figura do Produto 7 (sem reamostragem)."""
import glob

import fitz

pdf = [p for p in glob.glob('**/*PRODUTO 7 Plano*.pdf', recursive=True)
       if 'Tema30' in p][0]
doc = fitz.open(pdf)
pg = doc[55]  # page 56 Fig 3.3.3-7 Regiao 3 RA GEO

# Extrai a imagem nativa do mapa (xref 299) sem reamostragem
xref = 299
img = doc.extract_image(xref)
print('formato:', img['ext'], 'w', img['width'], 'h', img['height'])
out = '_fig_tmp/map_reg3_native.' + img['ext']
with open(out, 'wb') as f:
    f.write(img['image'])
print('saved', out)
