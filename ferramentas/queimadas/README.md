# ferramentas/queimadas

Scripts de preparacao, ingestao e processamento do modulo estadual de
risco de queimadas/incendio.

**Especificacao completa (metodologia, entradas, saidas, integracao):**
leia primeiro `data/queimadas/README.md`.

Estes scripts ficam fora do backend operacional. O runtime Flask deve ler
somente produtos ja gerados em `data/queimadas/processed/` ou artefatos
leves em `static/data/queimadas/`.

## Pipeline planejado

```cmd
python ferramentas/queimadas/01_prepare_base_layers.py
python ferramentas/queimadas/02_fetch_imerg.py
python ferramentas/queimadas/03_fetch_gfs.py
python ferramentas/queimadas/04_fetch_focos_inpe.py
python ferramentas/queimadas/05_compute_rf_grid.py
python ferramentas/queimadas/06_aggregate_to_der_segments.py
python ferramentas/queimadas/07_export_public_layers.py
```

Detalhe de cada script, esquemas de dados e contratos de API: ver secao 5
de `data/queimadas/README.md`.

## Escopo

- Cobertura: Estado de Sao Paulo.
- Saida operacional: risco de queimadas por trecho rodoviario DER-SP.
- Metodologia base: INPE Risco de Fogo v11; INMET/Nesterov auxiliar.
- Horizonte: observado diario + previsao D+1 a D+5.

## Regras de isolamento

- Nao importar nem alterar `core/risk.py`, `core/aggregator.py` ou
  `core/merge_ingest.py` para calcular queimadas.
- Integracao runtime via `core/fire_risk.py` (leitura/publicacao only).
- Downloads brutos: `data/queimadas/raw/`.
- Intermediarios: `data/queimadas/interim/`.
