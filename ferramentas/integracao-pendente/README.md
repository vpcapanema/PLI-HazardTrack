# Integracao pendente

Modulos implementados mas **ainda nao conectados** ao ciclo principal
(`core/aggregator.py`). Mantidos aqui para referencia e futura integracao.

## `daee_rain.py`

Ingestao da API pluviometrica do DAEE-SP
(`http://sibh.daee.sp.gov.br/api/eventos_ultimas_horas`).

Documentado no Produto 6 (secao 4.5.4.1.2). O sistema original SAMAEG
(TerraMA²) usava esta fonte como complemento ao Hidroestimador.

**Status:** codigo pronto; pipeline operacional usa apenas MERGE/INPE + WRF.
Politica: fonte complementar / fallback — nunca substituir MERGE sem validacao.

### Uso experimental

```cmd
python -c "import sys; from pathlib import Path; r=Path('.').resolve(); sys.path.insert(0,str(r/'ferramentas'/'integracao-pendente')); from daee_rain import fetch_daee_batch; print(fetch_daee_batch([(-23.8,-45.4)]))"
```

### Para integrar no futuro

1. Importar em `core/aggregator.py` como fallback quando MERGE falhar
2. Ou usar para validacao cruzada em `ferramentas/exploracao-georef/`
3. Variaveis de ambiente: `SAMAEG_DAEE_URL`, `SAMAEG_DAEE_TIMEOUT`
