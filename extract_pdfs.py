import PyPDF2, os

base_dir = r"D:\REPOSITORIOS\PLI-HazardTrack\Relatórios Plano de Contingência Banco Mundial abril 2021\Relatórios Plano de Contingência Banco Mundial abril 2021"

files = [
    "0 Contrato 20.595-3.PDF",
    "1 Produto 1 Plano de Trabalho.pdf",
    "2 PRODUTOS 2-5 Risco correlação chuva.pdf",
    "3 PRODUTO 6 Sistema.pdf",
    "4 PRODUTO 7 Plano de Contingência.pdf",
    "4 PRODUTO 7 zANEXO C - MANUAL DO USUÁRIO.pdf",
    "2053-Apresentação Produto Final - UBAs_REV00_16abr2021.pdf"
]

out_dir = r"D:\REPOSITORIOS\PLI-HazardTrack\_extracted_pdfs"
os.makedirs(out_dir, exist_ok=True)

for f in files:
    path = os.path.join(base_dir, f)
    out_path = os.path.join(out_dir, f.replace('.pdf','.txt').replace('.PDF','.txt'))
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
        with open(out_path, "w", encoding="utf-8") as outf:
            outf.write(text)
        print(f"  -> OK: {len(reader.pages)} pags, {len(text)} chars")
    except Exception as e:
        print(f"  ERRO: {e}")
