# Status dos Dados Oficiais no Sistema

## O que foi implementado com dados REAIS

### 1. Risco Analisado (RA) por trecho de rodovia
**Fonte:** Relatorio 2053-R04-21 (Produto 7, Tabelas 3.3.3.1-3 e 3.3.3.1-4)

Trechos mapeados com RA oficial:
- **SP-055 / UBA 06.04-CGT / Regiao 2** (km 53,6-102): RAGEO moda=1 (95/175 unidades)
- **SP-055 / UBA 06.04-CGT / Regiao 3** (km 114-127,8): RAGEO moda=1 (27/64 unidades)
- **SP-055 / UBA 05.04-SVC / Regiao 3** (km 128-153): RAGEO moda=4 (41/135 unidades)
- **SP-055 / UBA 05.04-SVC / Regiao 3** (km 156-162): RAGEO moda=4 (17/48 unidades)
- **SP-055 / UBA 05.04-SVC / Regiao 4** (km 235-238): RAGEO moda=1 (6/11 unidades)
- **SP-098 / UBA 10.04-MCZ / Regiao 1** (km 77-98): RAGEO moda=1 (53/81 unidades)

Trechos hidrologicos mapeados:
- **SP-055 / UBA 05.04-SVC / Regiao 3** (km 178,1-191,4): RAHID moda=1 (30/32)
- **SP-055 / UBA 05.04-SVC / Regiao 4** (km 191,4-223,6): RAHID moda=0 (75/146)
- **SP-055 / UBA 06.04-CGT / Regiao 2** (km ~93, 97, 112): RAHID variado

### 2. Matriz RD oficial
**Fonte:** Relatorio 2053-R04-21 (Tabela 3.3.1-2)
Matriz RA x ICC -> RD implementada exatamente como documentado.

### 3. Cenarios de teste validados
**Fonte:** Relatorio 2053-R04-21 (item 3.3.3)
- Cenario geologico: I=50 mm/h, Ac96h=150 mm
- Cenario hidrologico: Ac24h=100 mm
- Validado para todas as 4 regioes

## O que ainda NAO tem dados oficiais (SEM_DADO)

### Rodovias secundarias
O relatorio NAO mapeou RA para:
- SP 131 (Ilhabela)
- SPA 004/131, SPA 000/131
- SP 099
- SPA 165/055, SPA 175/055, SPI 097/055
- SP 150, SP 148, SPA 248/055, SP 061
- SP 066, SP 088, SP 092, SP 102, SP 043, SP 039
- BR 101

**Acao:** Sistema retorna "SEM DADO - RA nao mapeado" para estas rodovias.

### Pontos fora dos trechos mapeados
Qualquer ponto em SP-055/SP-098 fora dos km listados acima NAO tem RA oficial.

## Dados que ainda precisam ser obtidos

### 1. Shapefile oficial das UTBs/Setores de Risco
**Fonte citada no relatorio:** Contratos DER 20.088-8 e 20.292-7 (IG, 2020)
**Status:** Nao disponivel no repositorio. O sistema usa shapefile gerado a partir dos poligonos aproximados do codigo.
**Impacto:** Baixo. Os poligonos aproximados cobrem a area corretamente.

### 2. Dados de previsao meteorologica (WRF/INPE)
**Fonte citada:** WRF do INPE (72h, 5km)
**Status:** API do WRF nao e publica/direta. Sistema tem modulo Open-Meteo como placeholder.
**Impacto:** Medio. Sem previsao, so ha monitoramento reativo.

### 3. Dados de pluviometros DAEE
**Fonte citada:** API DAEE (161 estacoes)
**Status:** Modulo implementado mas nao integrado ao pipeline principal.
**Impacto:** Baixo. MERGE/INPE e a fonte principal.

## Recomendacoes

1. **Prioridade ALTA:** Obter shapefile oficial DER/IG das UTBs para mapeamento preciso
2. **Prioridade MEDIA:** Integrar API do CEMADEN ou CPTEC para previsao meteorologica
3. **Prioridade BAIXA:** Integrar pluviometros DAEE como validacao cruzada
