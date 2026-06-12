"""Extrai texto bruto dos PDFs do Plano de Contingencia (PyPDF2)."""
import os
from pathlib import Path

import PyPDF2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
base_dir = HERE / "pdfs-originais"
# subpasta aninhada do zip original
for sub in base_dir.iterdir():
    if sub.is_dir() and "Conting" in sub.name:
        base_dir = sub
        break

files = [
    "0 Contrato 20.595-3.PDF",
    "1 Produto 1 Plano de Trabalho.pdf",
    "2 PRODUTOS 2-5 Risco correlação chuva.pdf",
    "3 PRODUTO 6 Sistema.pdf",
    "4 PRODUTO 7 Plano de Contingência.pdf",
    "4 PRODUTO 7 zANEXO C - MANUAL DO USUÁRIO.pdf",
    "2053-Apresentação Produto Final - UBAs_REV00_16abr2021.pdf",
]

out_dir = HERE / "extracted-pdfs"
out_dir.mkdir(parents=True, exist_ok=True)

for f in files:
    path = base_dir / f
    out_path = out_dir / f.replace(".pdf", ".txt").replace(".PDF", ".txt")
    print(f"Extraindo: {f} ...")
    try:
        reader = PyPDF2.PdfReader(open(path, "rb"))
        text = ""
        for i, page in enumerate(reader.pages):
            try:
                ptext = page.extract_text()
                if ptext:
                    text += f"\n--- PAGE {i+1} ---\n" + ptext
            except Exception as e:
                text += f"\n--- PAGE {i+1} ERRO: {e} ---\n"
        out_path.write_text(text, encoding="utf-8")
        print(f"  -> OK: {len(reader.pages)} pags, {len(text)} chars")
    except Exception as e:
        print(f"  ERRO: {e}")
