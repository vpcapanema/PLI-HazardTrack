# Metodologia, Sistema Original (SAMAEG) e Gaps a Resolver

Documento de referencia que consolida a base cientifica do projeto
(Relatorios REGEA-NIPPON / Consorcio 4X044, Banco Mundial, abril/2021),
descreve a primeira versao implementada (SAMAEG sobre TerraMA2 + ArcGIS)
e compara com a implementacao atual (PLI-HazardTrack / Flask + Leaflet),
sinalizando os gaps ainda em aberto.

**Fontes:** Contrato DER 20.595-3; Produtos 01 a 07 (relatorio 2053);
Anexo C - Manual do Usuario; Apresentacao Produto Final (16/abr/2021).

---

## 1. Base cientifica (Produtos 02 a 05)

### 1.1 Modelo de Risco Dinamico

- Formula central: `RD = RA x ICC`, com `RD = max(RD_GEO, RD_HID)`.
- Envoltoria de Tatizana (Cubatao / Serra do Mar):
  `I = K * Ac96h^-0,9`, onde `I` = intensidade (mm/h) e
  `Ac96h` = acumulado de chuva nas 96 h anteriores.
  - O expoente real ajustado em Sao Sebastiao foi -0,933, mas foi
    **padronizado para -0,9** em todas as regioes.
- Janelas de analise:
  - **Geologico:** intensidade + acumulado **96 h**.
  - **Hidrologico:** acumulado **24 h** (via probabilidade de
    ocorrencia, nao via CPC).

### 1.2 Quatro regioes (K e limiares calibrados)

| Regiao | Trecho | Rodovia (km) | K (CPC) |
| --- | --- | --- | --- |
| 1 | Mogi-Bertioga | SP-098 (62,9-98,1) | 1000 |
| 2 | Caraguatatuba-Ubatuba | SP-055 (53,6-112,55) | 400 |
| 3 | Sao Sebastiao | SP-055 (112,55-191,4) | 200 |
| 4 | Santos-Bertioga | SP-055 (191,4-248,1) | 1000 |

Implementado em `core/regions.py` (limiares `cpc_breaks` geologicos e
`hid24h_breaks` hidrologicos por regiao).

### 1.3 Matriz RA x ICC -> RD

Reproduzida exatamente em `core/risk.py` (`RD_MATRIX`). Classes 0-4 para
RA e RD, tanto geologico quanto hidrologico.

### 1.4 Unidades de Analise (UAs)

- **809 Unidades de Analise** = UTBs (1:25.000 / 1:10.000) + Setores de
  Risco (1:1.000), com RA homogeneizado em 5 classes (RAGEO/RAHID 0-4).
- Base empirica: **27 anos (1993-2020)**, 9.285 eventos geodinamicos,
  161 estacoes pluviometricas (DAEE / CEMADEN / ANA).
- Tabelas oficiais de distribuicao de RA: 3.3.3.1-3 (geologico) e
  3.3.3.1-4 (hidrologico), reproduzidas em `core/ra_official.py`.

---

## 2. Sistema original: SAMAEG (Produto 06 / Anexo C)

Nome: **Sistema Automatizado de Analise, Monitoramento e Alerta de
Risco (SAMAEG)**. Interface web: **SGI-Riscos-DER**.
Acesso original: `http://db.optimusgis.com.br:2180/SGI-Riscos-DER/`.

- **Motor de analise/alerta:** TerraMA2 / INPE (scripts Python).
- **Interface:** ArcGIS Web (JavaScript / HTML5 / Dojo), servidor
  **IIS / Windows**.
- **Fontes de chuva (DOIS modelos paralelos):**
  - **Hidroestimador** (satelite GOES, intervalo de 10 min).
  - **Pluviometros DAEE** (API `sibh.daee.sp.gov.br`, horaria,
    interpolacao Vizinho Natural 0,027 graus, buffer 30 km).
  - Ambos somados a previsao **WRF / INPE** (72 h, 5 km).
- **Composicao das janelas:**
  - Geologico: `96 h = 72 h observado + 24 h previsto`.
  - Hidrologico: `24 h = 18 h observado + 6 h previsto`.
- **Niveis de Operacao (PPDC):** Monitoramento, Observacao, Atencao,
  Alerta, Alerta Maximo - **mapeados pela faixa de ICC**.
- **Acoes por nivel** (Quadro 4.2.2-2): COI / CCO / UBA do DER/SP +
  CEPDEC / REPDEC / COMPDEC / Prefeituras / PM Rodoviaria / Bombeiros /
  SAMU.
- Atualizacao a cada 10 min; alerta por e-mail + tela; apenas Atencao+
  dispara mensagem; animacao temporal de 96 h; recomendacoes em
  `config.JSON`.

---

## 3. Comparacao: SAMAEG (2021) x PLI-HazardTrack (2026)

### 3.1 Mantido fielmente

| Item | Status | Onde |
| --- | --- | --- |
| Matriz RA x ICC -> RD | Identico | `core/risk.py` |
| Equacoes de envoltoria, K, limiares por regiao | Identico | `core/regions.py` |
| Composicao obs + previsao (72+24 / 18+6) | Identico | `core/risk.py` |
| Tabelas oficiais de RA (3.3.3.1-3/-4) | Identico | `core/ra_official.py` |
| Acoes operacionais PPDC | Reproduzido | `core/actions.py` |
| Refresh de 10 min + alerta por e-mail | Mantido | `core/notifier.py`, `app.py` |
| Nome SAMAEG | Preservado | (interno) |

### 3.2 Diferencas principais

| Dimensao | Original (SAMAEG) | Atual (PLI-HazardTrack) |
| --- | --- | --- |
| Plataforma | TerraMA2 + ArcGIS, IIS/Windows | Flask + Leaflet, Docker/Linux, Render |
| Chuva observada | Hidroestimador (GOES) + DAEE | MERGE/CPTEC/INPE (GRIB2 via eccodes) |
| Previsao | WRF/INPE | WRF prec horario (`forecast_wrf_prec_hourly.py`) |
| Unidade operacional | 809 UAs oficiais (UTB/SR) | `ua_polygons.geojson` + split geo/hidro |
| Disparo de acoes | Por ICC | Por RD (pior caso) em `core/actions.py` |
| Animacao 96 h | Sim | Nao implementado |
| Canais de alerta | E-mail + sistemas IG/DER | E-mail + webhook (Slack/Telegram) |
| Autenticacao | Gestao propria + admin TerraMA2 | Postgres SRA (read-only, bcrypt), `/ops` |
| Dados ausentes | Avisos "No data"/"Empty result" | Politica explicita NO_DATA, sem mock |

---

## 4. GAPS - pendencias a resolver / implementar

> Itens marcados como `[ ]` ainda NAO estao resolvidos. Esta secao deve
> ser atualizada conforme os gaps forem fechados.

### Prioridade ALTA

- [ ] **G1 - Shapefile oficial das 809 UAs (UTB / Setores de Risco).**
  Atualmente o sistema usa UAs geradas por buffer unificado da malha DER
  (`data/ua_polygons/ua_polygons.geojson`) em vez dos poligonos oficiais (Contratos DER 20.088-8 e 20.292-7, IG
  2020). Impacto: granularidade e precisao do RA por unidade.
  Acao: obter o shapefile oficial do DER/IG e substituir as zonas.

- [ ] **G2 - Fonte de chuva observada equivalente ao original.**
  O original usava Hidroestimador (GOES, 10 min) + DAEE. O atual usa
  apenas MERGE/CPTEC/INPE (validado em producao: 96/96 GRIB2 horarios
  lidos no backtest de 19/02/2023 - Sao Sebastiao). Avaliar integrar
  Hidroestimador para paridade metodologica e maior frequencia.
  **Achado (jun/2026):** nao existe API publica de pluviometro de solo
  do DAEE em tempo real. O portal `ph.daee.sp.gov.br` /
  `ph.spaguas.sp.gov.br` so serve dados **diarios historicos** (ver G6).
  Para chuva de solo em tempo real, a fonte correta seria **Saisp
  (CTH/DAEE)** ou **CEMADEN** - hoje NENHUMA das duas esta implementada.

- [ ] **G3 - Alinhamento ICC vs RD no disparo de Nivel de Operacao.**
  O Quadro 4.2.2-2 define o Nivel de Operacao a partir da **faixa de
  ICC**; o `core/actions.py` atual mapeia acoes pelo **RD**. Decidir e
  documentar a regra correta (ICC) ou justificar a divergencia.

### Prioridade MEDIA

- [ ] **G4 - Previsao WRF/INPE oficial.**
  Confirmar se `forecast_wrf_prec_hourly.py` consome WRF/INPE real
  (72 h, 5 km) ou um proxy. Sem previsao confiavel, a operacao tende
  ao modo reativo (so monitoramento).

- [x] **G5 - Animacao temporal de 96 h.** RESOLVIDO (jun/2026).
  Reimplementada a "Linha do Tempo" (Anexo C, secao 3.4.2): animacao
  hora-a-hora dos poligonos de alerta coloridos por RD nas ultimas 96 h.
  - Backend: `merge_inpe.fetch_hourly_series` expoe a serie horaria por
    ponto; `aggregator.State.build_timeline` reconstroi o RD de cada zona
    com janela movel observada (Ac96h/Ac24h) por hora, com cache curto;
    endpoint `GET /api/timeline` (on-demand, nao pesa no ciclo de 10 min).
  - Frontend: controle com Reproduzir/Pausar, Anterior/Proximo, slider e
    seletor de passo (1/2/3/6 h), recolorindo os trechos no mapa Leaflet.
  - Base: chuva OBSERVADA do MERGE/INPE (a timeline nao usa previsao).

- [ ] **G6 - Integracao DAEE como validacao cruzada (historico).**
  `core/daee_rain.py` existe mas nao esta no pipeline principal e aponta
  para um endpoint **presumido** (`sibh.daee.sp.gov.br/api/`) que nao foi
  confirmado ativo. **Achado (jun/2026):** o portal oficial
  `ph.daee.sp.gov.br` (= `ph.spaguas.sp.gov.br`, novo "SP Aguas") e um
  **banco de dados historico**: pluviometria so em resolucao **diaria**,
  via `POST /Pluviometricos/Posto` (posto identificado por **GUID**),
  sem feed horario/telemetrico (o "Medidor Eletronico" existe apenas
  para Fluviometricos/Piezometricos). Backend `fch.spaguas.sp.gov.br`
  exige login. **Conclusao:** o `ph.daee` serve para **backtest /
  calibracao** (series diarias por posto da area: E2-043 Rio d'Ouro,
  Caraguatatuba, Ubatuba, Maresias, Bertioga), **nao** para tempo real.

### Prioridade BAIXA

- [ ] **G7 - RA para rodovias secundarias.**
  O relatorio nao mapeou RA para SP-131, SPA 004/131, SP-099, SP-150,
  SP-102, BR-101 e outras (lista em `DADOS_OFICIAIS_STATUS.md`). Estas
  retornam SEM_DADO. Acao: aguardar dados oficiais; manter NO_DATA.

- [ ] **G8 - Modelo DAEE separado de alertas.**
  O original tinha camadas distintas "RISCO GEOLOGICO/HIDROLOGICO INPE"
  e "RISCO GEOLOGICO DAEE". Avaliar se faz sentido manter dois modelos
  paralelos visiveis no mapa atual.

---

## 5. Referencias cruzadas no codigo

| Conceito | Modulo |
| --- | --- |
| Calculo de RD (RA x ICC), composicao de janelas | `core/risk.py` |
| Limiares CPC / ICC por regiao, poligonos | `core/regions.py` |
| RA oficial por trecho (tabelas 3.3.3.1-3/-4) | `core/ra_official.py` |
| Agregacao chuva + risco (pipeline) | `core/aggregator.py` |
| Fonte MERGE/INPE (chuva observada) | `core/merge_inpe.py` |
| Previsao WRF horaria | `core/forecast_wrf_prec_hourly.py` |
| Pluviometros DAEE (nao integrado) | `core/daee_rain.py` |
| Acoes PPDC por nivel | `core/actions.py` |
| Notificacao (e-mail / webhook) | `core/notifier.py` |
| Painel operacional / auth SRA | `core/ops.py`, `core/sra_auth.py` |
| Segmentacao de UAs / zonas | `core/ua_segments.py`, `core/zones.py` |

Status detalhado dos dados oficiais: ver `DADOS_OFICIAIS_STATUS.md`.
