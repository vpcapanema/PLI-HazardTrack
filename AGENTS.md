# AGENTS.md - PLI-HazardTrack

## Sistema
Sistema Automatizado de Monitoramento, Analise e Alerta Geodinamico
para rodovias da Regiao do Litoral Norte de Sao Paulo (DER-SP).

## Build e Test
- `python -m unittest discover -s tests -p "test_*.py"` - roda todos os testes
- Limite de linha: 79 caracteres (Flake8)

## Arquitetura
- `app.py` - Flask backend + scheduler
- `core/risk.py` - Calculo de Risco Dinamico (RD = RA x ICC)
- `core/ra_official.py` - RA real por trecho (relatorios REGEA-NIPPON)
- `core/aggregator.py` - Agrega dados de chuva + risco
- `core/merge_inpe.py` - Fonte MERGE/INPE para chuva
- `core/forecast_cptec.py` - Previsao CPTEC/INPE
- `core/regions.py` - Poligonos das 4 regioes
- `static/app.js` - Frontend (mapa, paineis, graficos)

## Regras de Risco (Metodologia DER-SP)
- RD = max(RDGEO, RDHID)
- RDGEO = RAGEO x ICCGEO (chuva intensidade)
- RDHID = RAHID x ICCHID (chuva 24h)
- Niveis: 0=Monitoramento, 1=Observacao, 2=Atencao, 3=Alerta, 4=Alerta Maximo

## Dados Oficiais Implementados
1. **RA por trecho**: Tabelas 3.3.3.1-3 e 3.3.3.1-4 do Relatorio 2053-R04-21
   - 6 trechos geologicos mapeados (SP-055, SP-098)
   - 5 trechos hidrologicos mapeados
   - Pontos sem dado retornam RA=None (SEM_DADO)

2. **Shapefile DER/SP**: Malha rodoviaria oficial do portal dadosabertos.sp.gov.br
   - 161 trechos de 15 rodovias
   - CRS: EPSG:4326 (WGS84)

3. **Previsao**: CPTEC/INPE (http://servicos.cptec.inpe.br/XML/)
   - Substitui Open-Meteo (fonte internacional generica)

## Politica Critica
- **NUNCA inventar RA**. Sem dado oficial = SEM_DADO.
- **NUNCA usar shapefile aproximado**. Usar apenas dados oficiais.
- **NUNCA usar previsao generica**. Usar fontes calibradas para o Brasil.

## Gaps Conhecidos
- RA nao mapeado para rodovias secundarias (SP 131, SPA, etc.)
- Previsao CPTEC fornece condicoes, nao precipitacao em mm exata
- Modulo DAEE existe mas nao integrado ao pipeline principal
- Shapefile das 809 UAs (REGEA-NIPPON) ainda nao obtido
