# Relatorios — Plano de Contingencia (Banco Mundial / REGEA-NIPPON 2021)

Material fonte e exportacoes de texto usados para extrair tabelas, figuras
e metodologia do sistema HazardTrack. **Nao e carregado pelo backend.**

## Conteudo

| Item | Descricao |
|------|-----------|
| `pdfs-originais/` | Pacote original dos relatorios (Contrato, Produtos 1–7, Apresentacao) |
| `pdf-forge-exports/` | Texto (.txt) e PNGs-chave exportados do Produto 7 (Tab. 2-1, 3.3-1, figuras 3.3-2..5) |
| `extracted-pdfs/` | Texto bruto via PyPDF2 (`extract_pdfs.py`) |
| `METODOLOGIA_E_GAPS.md` | Base cientifica, comparacao SAMAEG original vs implementacao atual |
| `DADOS_OFICIAIS_STATUS.md` | Status de cada fonte de dados oficial |

## Onde foi usado no projeto

- **Tabela 2-1** → cortes municipais em `geracao-uas/build_ua_polygons.py`
- **Tabela 3.3-1** → contagem 809 UAs por regiao/municipio/escala
- **Tabelas 3.3.1-2 / 3.3.2-2** → orcamento RA em `geracao-uas/ua_ra_budgets.py`
- **Tabelas 3.3.3.1-3 / 3.3.3.1-4** → trechos criticos em `core/ra_official.py`
- **Figuras 3.3-2..5** → escala cartografica por UA
- **Figuras 3.3.3-x** → leitura de cor RA em `assign_ra_to_uas.py`
- **`ra_official.py`** → Tabelas 3.3.3.1-3/-4 transcritas (trechos criticos);
  usado por scripts de geracao/validacao e por `tests/test_scenarios.py`

## PDF operacional (runtime dos scripts UA)

O script de geracao usa a copia em:

`data/Tema30_Resiliencia/Relatorio_Plano_Contingencia BIRD_2021/`

## Extrair texto dos PDFs

```cmd
python ferramentas/relatorios-plano-contingencia/extract_pdfs.py
```

Saida: `extracted-pdfs/*.txt`

## Fonte da verdade

Relatorio **2053-R04-21** (Produto 7 — Plano de Contingencia), abril/2021.
Politica do projeto: sem dado oficial → `SEM_DADO`; nunca inventar RA.
