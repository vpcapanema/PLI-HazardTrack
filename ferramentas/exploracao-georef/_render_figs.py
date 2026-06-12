"""Renderiza paginas do PDF do Produto 7 em PNG para inspecao."""
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ferramentas" / "geracao-uas" / "figuras-diagnostico"
OUT.mkdir(parents=True, exist_ok=True)

pdfs = list(ROOT.glob("**/*PRODUTO 7 Plano*.pdf"))
pdf = next(p for p in pdfs if "Tema30" in str(p))
doc = fitz.open(pdf)
print("pdf:", pdf)
print("paginas:", doc.page_count)

pages = [int(x) for x in sys.argv[1:]] or [56]
for p1 in pages:
    pg = doc[p1 - 1]
    pix = pg.get_pixmap(matrix=fitz.Matrix(4, 4))
    out = OUT / f"page_{p1}.png"
    pix.save(str(out))
    print("saved", out, pix.width, "x", pix.height)
