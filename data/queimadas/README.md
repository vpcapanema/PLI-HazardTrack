# Modulo Queimadas — Especificacao completa

Documento canonico para implementacao, operacao e replicacao do modulo
estadual de **risco de queimadas/incendio** no PLI-HazardTrack.

Leia este arquivo antes de baixar dados, escrever scripts ou integrar ao
backend. Um agente de IA deve conseguir reconstruir o modulo inteiro a
partir deste texto, dos metadados em `metadata/` e dos READMEs em
`ferramentas/queimadas/`.

---

## 1. Apresentacao do modulo

### 1.1 O que e

Modulo **independente** que consome o **Risco de Fogo (RF) oficial do
INPE**, agrega esse risco por **trecho oficial** da malha rodoviaria do
DER-SP e publica camadas estaduais de risco de queimadas no
PLI-HazardTrack.

Nao e um sistema de alertas textuais (como chuvas intensas da Defesa
Civil). E um **indice espacial de risco previsto/observado**, atualizado
diariamente conforme disponibilidade dos produtos INPE, com horizonte
operacional atual `observado`, `D+1`, `D+2` e `D+3`.

### 1.2 O que NAO e

- Nao substitui nem altera o **Risco Dinamico (RD)** do PLI
  (`core/risk.py`: RD = RA x ICC para encostas/inundacao).
- Nao usa as **809 UAs** nem as **4 regioes PLI** como unidade principal.
- Nao compartilha pipeline MERGE/WRF do aggregator principal, embora possa
  reutilizar bibliotecas de download onde fizer sentido.
- Nao recalcula localmente IMERG/GFS/MapBiomas no fluxo operacional atual:
  esses insumos ja entram no RF oficial publicado pelo INPE.
- Nao detecta foco ativo sozinho: focos INPE podem entrar futuramente como
  camada de ocorrencia/auditoria, nao como produto principal atual.

### 1.3 Unidade operacional de saida

| Conceito | Definicao |
| --- | --- |
| Cobertura espacial | Estado de Sao Paulo (recorte oficial) |
| Geometria de referencia | Malha rodoviaria DER-SP (`MALHA_RODOVIARIA`) |
| Unidade de exibicao | **Um registro por trecho cadastral DER** |
| Identificador canonico | `trecho_id` estavel (ver secao 8.3) |

Atributos nativos DER a preservar na saida (nao renomear):

`rodovia`, `tipo`, `orientacao`, `municipio`, `regional`, `residencia`,
`km_ini`, `km_fim`, `extensao`, `jurisdicao`, `administra`, `conservado`,
`tipo_pista`, `denominacao`.

Fonte shapefile oficial ja presente no repositorio:

`data/der_sistema_rodoviario/MALHA_RODOVIARIA.shp` (EPSG:4326 apos
preparacao; ver `ferramentas/preparacao-geodata/build_road_network.py`).

### 1.4 Separacao conceitual: risco x ocorrencia

| Produto | Significado | Horizonte |
| --- | --- | --- |
| **Risco de Fogo (RF)** | Probabilidade/condicao favoravel a ignicao | Observado + D+1..D+3 |
| **Foco ativo INPE** | Queimada ja detectada por satelite | Ultimas horas/dias |
| **Alerta operacional** | Mensagem humana/automatica para acao | Tempo real |

Este modulo entrega **RF por trecho**, a partir do raster oficial do INPE.
Focos ativos e alertas push/webhook sao camadas futuras opcionais.

---

## 2. Metodologia

### 2.1 Metodologia principal: INPE Risco de Fogo (RF)

Referencia oficial:

- Setzer et al., **Metodo do calculo do Risco de Fogo do Programa do
  INPE — Versao 11, junho/2019**
- URL: [INPE RF v11 PDF](https://dataserver-coids.inpe.br/queimadas/queimadas/Publicacoes-Impacto/documentos/RiscoFogo_Sucinto.pdf)

Principio meteorologico: quanto mais **dias consecutivos sem chuva**
(PSE — periodo de secura), maior o risco de queima da vegetacao.
Temperatura alta e umidade baixa aumentam; tipo de vegetacao modula a
inflamabilidade.

**Importante:** vento e umidade do solo **nao** entram no RF INPE
(vento afeta propagacao, nao ignicao antropica tipica).

### 2.1.0 Implementacao operacional atual

O modulo **nao recalcula** o RF do zero. Ele consome diretamente os
produtos oficiais ja calculados pelo INPE:

- RF observado:
  `https://dataserver-coids.inpe.br/queimadas/queimadas/riscofogo_meteorologia/observado/risco_fogo/`
- RF previsto:
  `https://dataserver-coids.inpe.br/queimadas/queimadas/riscofogo_meteorologia/previsto/risco_fogo/`

O script `05_compute_rf_grid.py` baixa:

- ultimo `INPE_FireRiskModel_2.2_FireRisk_YYYYMMDD.nc`
- `RF.PREV.T0.tif`
- `RF.PREV.T1.tif`
- `RF.PREV.T2.tif`
- `RF.PREV.T3.tif`

Assim, o sistema usa **metodologia INPE real**, sem precisar reimplementar
IMERG/GFS/MapBiomas no primeiro ciclo de producao. A reimplementacao local
das equacoes fica como trilha futura de auditoria/calibracao.

O raster oficial observado inspecionado no ciclo atual possui passo
espacial aproximado de **0,1 grau**, equivalente a cerca de **10 km**.
Portanto, o risco por trecho DER e uma **agregacao/amostragem do RF INPE
de ~10 km sobre a geometria do trecho**, nao uma medida local em escala
de dezenas de metros.

Fluxo implementado atualmente:

1. `05_compute_rf_grid.py` baixa o RF oficial INPE observado e previsto.
2. `06_aggregate_to_der_segments.py` amostra pontos ao longo de cada
   trecho DER-SP e usa o maior RF amostrado como valor conservador.
3. `07_export_public_layers.py` exporta GeoJSON/JSON publicos por
   horizonte (`observado`, `D+1`, `D+2`, `D+3`).
4. `core/fire_risk.py` serve os produtos prontos sem baixar/calcular no
   ciclo HTTP.

#### 2.1.1 Entradas internas do RF INPE

As entradas abaixo sao os insumos da metodologia INPE. No fluxo
operacional atual elas sao mantidas e processadas pelo proprio INPE; o
PLI-HazardTrack consome o raster final de RF.

| Variavel | Fonte operacional | Resolucao espacial | Resolucao temporal |
| --- | --- | --- | --- |
| Precipitacao diaria | IMERG/GPM (NASA) | ~10 km | Diaria; acumulados 1..120 dias |
| Temperatura maxima do ar | GFS (NOAA/NCEP) | ~25 km | Diaria (analise 18 UTC) |
| Umidade relativa minima | GFS | ~25 km | Diaria (analise 18 UTC) |
| Tipo de vegetacao | MapBiomas (+ IGBP fora BR) | 30 m | Anual |
| Altitude | DEM (SRTM/Copernicus) | ~30 m | Estatica |
| Latitude | Derivada da grade | — | Estatica |
| Focos recentes | Programa Queimadas INPE | Pontual | Ultimos 3 dias |

#### 2.1.2 Sequencia de calculo (grade 10 km)

A metodologia INPE segue, em termos conceituais, a ordem abaixo, celula
a celula. Esta sequencia so precisa ser implementada no PLI-HazardTrack
se houver recálculo local futuro:

1. **Precipitacao acumulada** em 11 janelas retroativas: 1, 2, 3, 4, 5,
   6-10, 11-15, 16-30, 31-60, 61-90, 91-120 dias.
2. **Fatores de precipitacao (fp)** por janela: funcao exponencial
   empirica; chuva recente reduz mais o risco que chuva antiga.
3. **Dias de Secura (PSE)**: produto dos fp escalado (equacao 3.3 INPE).
4. **Risco Basico (Rb)**: curva senoidal em funcao do PSE e constante
   **A** da classe de vegetacao (maximo 0,8).
5. **Fator UR**: linear; UR < 40% aumenta risco (eq. 3.5).
6. **Fator temperatura**: linear; T > 30 C aumenta risco (eq. 3.6).
7. **RF observado**: Rb x fator_UR x fator_T (eq. 3.7).
8. **Ajustes**: fator latitudinal FLAT e topografico FELV (eq. 3.8-3.10).
9. **Correcao por foco**: se RF minimo/baixo e foco nos ultimos 3 dias
   sem chuva no periodo, elevar para **Alto** (0,7-0,95).

Constantes **A** por classe de vegetacao (Tabela 3.4 INPE):

| Classe resumida | A |
| --- | --- |
| Ombrófila densa; alagados | 1,5 |
| Florestas deciduas/sazonais | 1,72 |
| Floresta de contato; campinarana | 2,0 |
| Savana arborea; caatinga fechada | 2,4 |
| Savana; caatinga aberta | 3,0 |
| Agricultura e diversos | 4,0 |
| Pastagens e gramíneas | 6,0 |

Classes sem vegetacao combustivel (agua, urbano, neve, solo nu): **A = -x**
(excluir do calculo ou RF = 0).

#### 2.1.3 Classes de saida INPE

| Classe | Faixa RF |
| --- | --- |
| minimo | RF < 0,15 |
| baixo | 0,15 < RF <= 0,40 |
| medio | 0,40 < RF <= 0,70 |
| alto | 0,70 < RF <= 0,95 |
| critico | RF > 0,95 |

Persistir sempre **valor continuo** (`rf_valor`) e **classe**
(`rf_classe`).

#### 2.1.4 RF previsto

Mesma sequencia, usando previsao GFS de precipitacao, Tmax e URmin,
com **condicao inicial** = RF observado do dia corrente.

Horizontes de produto implementados:

- `observado` — dia D (analise)
- `D+1`, `D+2`, `D+3` — previsao numerica oficial INPE

O diretorio INPE previsto publica tambem `RF.PREV.T0.tif`, mantido pelo
pipeline para auditoria, mas o mapa publico usa `observado` como camada
do dia corrente.

Atualizacao recomendada: **1 ciclo fixo por dia** apos a publicacao dos
arquivos INPE.

### 2.2 Metodologia auxiliar: INMET / Nesterov

Referencia:

- [INMET — Risco de incendio](https://portal.inmet.gov.br/servicos/risco-de-incendio)

Indice acumulativo baseado em T, UR (ou ponto de orvalho) e chuva 24h
as **13h BRT**. Classes 1-5 (nenhum a perigosissimo).

**Uso no modulo:** auditoria, comparacao e validacao cruzada — **nao**
substituir o RF espacial INPE como produto principal (estacoes sao
pontuais e esparsas).

Implementacao opcional: `ferramentas/queimadas/08_nesterov_audit.py`.

### 2.3 Resolucao efetiva vs resolucao de exibicao

| Etapa | Resolucao |
| --- | --- |
| RF oficial INPE | ~0,1 grau / ~10 km |
| Agregacao para trecho DER | Geometria vetorial (trecho a trecho) |
| Mapa web | GeoJSON simplificado por trecho |

A malha DER tem resolucao geometrica fina (~dezenas de metros), mas o
**sinal meteorologico/ambiental** subjacente do RF INPE e da ordem de
**10 km**. Assim, varios trechos curtos podem receber o mesmo valor de
RF por estarem dentro do mesmo pixel. Documentar isso na UI
(`metodologia`, `resolucao_fonte`).

---

## 3. Arquitetura no repositorio

### 3.1 Isolamento obrigatorio

```text
PLI-HazardTrack (RD encostas/inundacao)     Modulo Queimadas (RF estadual)
=====================================       ==============================
core/risk.py                                core/fire_risk.py (leitura only)
core/aggregator.py                          ferramentas/queimadas/*.py
core/merge_ingest.py                        data/queimadas/**
data/ua_zones/                              static/data/queimadas/
static/data/malha_der.geojson (compartilhado como geometria DER)
```

Regras:

- **Proibido** calcular RF dentro de `aggregator.py` ou `risk.py`.
- **Proibido** misturar arquivos em `ua_zones/` ou `regioes/`.
- Backend Flask so **le** produtos prontos via `core/fire_risk.py`.
- Pipeline batch roda **fora** do ciclo MERGE de 120 s.

### 3.2 Arvore de pastas

| Pasta | Tipo | Conteudo | Git |
| --- | --- | --- | --- |
| `data/queimadas/base/` | Estatico preparado | Malha DER-SP recortada, limite SP; MapBiomas/DEM futuros | Versionar leve |
| `data/queimadas/raw/imerg/` | Futuro bruto | NetCDF/HDF5 IMERG para recálculo local | Ignorar |
| `data/queimadas/raw/gfs/` | Futuro bruto | GRIB2 GFS para recálculo local | Ignorar |
| `data/queimadas/raw/focos_inpe/` | Futuro bruto | CSV/GeoJSON focos | Ignorar |
| `data/queimadas/raw/inmet/` | Auxiliar bruto | CSV estacoes | Ignorar |
| `data/queimadas/interim/rf_inpe/` | Intermediario atual | NetCDF/GeoTIFF RF oficial INPE | Ignorar |
| `data/queimadas/interim/grade_rf/` | Futuro intermediario | Raster/tabela RF recalculado localmente | Ignorar |
| `data/queimadas/interim/buffers_trechos/` | Intermediario | Buffers por trecho | Ignorar |
| `data/queimadas/processed/` | **Produto canonico** | GPKG/Parquet risco por trecho | Versionar leve |
| `data/queimadas/metadata/` | Rastreabilidade | `fontes.json`, `manifest.json`, logs execucao | Versionar |
| `static/data/queimadas/` | Publicacao web | GeoJSON/JSON latest | Versionar leve |
| `ferramentas/queimadas/` | Scripts batch | Pipeline 01..07 | Versionar |

Metadados complementares: `metadata/fontes.json`, `metadata/manifest.json`.

---

## 4. Fontes de dados — catalogo operacional

Detalhes em `metadata/fontes.json`. Resumo para implementacao:

### 4.1 Estaticos (preparar uma vez; revisar anualmente)

| ID | Arquivo alvo em `base/` | Como obter |
| --- | --- | --- |
| `der_sp_malha_rodoviaria` | `trechos_der_sp.gpkg` | Copiar/normalizar de `data/der_sistema_rodoviario/`; EPSG:4326; gerar `trecho_id` |
| `limite_sp` | `limite_sp.gpkg` | IBGE/DRADT ou `static/data/sp_state.geojson` existente |
| `mapbiomas` | `vegetacao_inpe.tif` ou `.gpkg` | Futuro: MapBiomas Collection via GEE; reclassificar para classes INPE ou combustivel local |
| `dem` | `altitude_sp.tif` | Futuro: SRTM 1 arc-seg ou Copernicus DEM; recortar SP |

### 4.2 Dinamicos (ingest diaria)

| ID | Destino `raw/` | Protocolo | Retencao |
| --- | --- | --- | --- |
| `rf_inpe_observado` | `interim/rf_inpe/YYYYMMDD/` | HTTPS INPE; `INPE_FireRiskModel_2.2_FireRisk_*.nc` | Ultimos ciclos |
| `rf_inpe_previsto` | `interim/rf_inpe/YYYYMMDD/` | HTTPS INPE; `RF.PREV.T0.tif`..`T3.tif` | Ultimos ciclos |
| `imerg_gpm` | `imerg/YYYY/MM/` | Futuro: HTTPS NASA GES DISC ou Earthdata; produto IMERG Daily | >= 120 dias |
| `gfs` | `gfs/YYYY/MM/DD/` | Futuro: NOMADS/AWS GRIB2; variaveis tmp, rh, prate | Ultimos 7 dias |
| `inpe_focos_queimada` | `focos_inpe/YYYY/MM/DD/` | Futuro: Portal/API Programa Queimadas INPE | >= 7 dias |
| `inmet_estacoes` | `inmet/` (opcional) | BDMEP / API INMET | Conforme auditoria |

### 4.3 Alternativa nacional de chuva para recálculo futuro

O PLI ja consome **MERGE/GPM horario** via CPTEC (`core/merge_inpe.py`).
Para aderencia estrita ao INPE RF, preferir **IMERG diario**. MERGE pode
ser usado como fallback documentado apenas se o projeto implementar
recálculo local do RF.

---

## 5. Pipeline batch — scripts e contratos

Scripts em `ferramentas/queimadas/`. Ordem operacional atual:

```cmd
python ferramentas/queimadas/01_prepare_base_layers.py
python ferramentas/queimadas/05_compute_rf_grid.py [--date YYYY-MM-DD]
python ferramentas/queimadas/06_aggregate_to_der_segments.py [--date YYYY-MM-DD]
python ferramentas/queimadas/07_export_public_layers.py [--date YYYY-MM-DD]
```

Scripts `02_`, `03_` e `04_` ficam reservados para recálculo local ou
auditoria futura.

### 5.1 `01_prepare_base_layers.py`

**Entrada:** shapefile DER e limite SP.

**Saida:**

- `data/queimadas/base/trechos_der_sp.gpkg` (layer `trechos`)
- `data/queimadas/base/limite_sp.gpkg`

**Acoes:**

1. Reprojetar tudo para EPSG:4326 (ou EPSG:5880 metrico para buffers;
   converter ao final).
2. Gerar `trecho_id` unico e estavel (sugestao abaixo).
3. Validar contagem de feicoes (~161 trechos / 15 rodovias no recorte
   historico DER-SP; confirmar no shape atual).
4. Escrever `metadata/base_layers.json` com checksums e datas.

### 5.2 `02_fetch_imerg.py`

Reservado para ingest local de IMERG Daily, caso o projeto decida
recalcular o RF localmente. No fluxo operacional atual, este script
apenas registra indisponibilidade/contrato, porque o RF oficial INPE ja
embute chuva acumulada.

Persiste em `raw/imerg/` e mantem indice Parquet/JSON:
`raw/imerg/_index.json` com datas disponiveis.

### 5.3 `03_fetch_gfs.py`

Reservado para ingest local de GFS (Tmax, URmin e precipitacao prevista),
caso o projeto decida recalcular o RF localmente. No fluxo operacional
atual, o RF previsto oficial INPE ja embute esses insumos.

Persiste GRIB bruto + NetCDF/GeoTIFF recortado SP em `raw/gfs/`.

### 5.4 `04_fetch_focos_inpe.py`

Reservado para baixar focos ativos INPE e publicar uma camada de
ocorrencias/auditoria. No fluxo atual, o RF oficial INPE ja considera
focos na propria metodologia; este script ainda nao e necessario para
produzir o RF por trecho.

Persiste GeoJSON diario em `raw/focos_inpe/`.

### 5.5 `05_compute_rf_grid.py`

Baixa o RF oficial INPE observado/previsto e cria um indice local dos
rasters em `data/queimadas/interim/rf_inpe/YYYYMMDD/rf_index.json`.

**Saida:**

- `interim/rf_inpe/YYYYMMDD/INPE_FireRiskModel_2.2_FireRisk_*.nc`
- `interim/rf_inpe/YYYYMMDD/RF.PREV.T0.tif` .. `RF.PREV.T3.tif`
- `interim/rf_inpe/YYYYMMDD/rf_index.json`

Atualizar `metadata/manifest.json` com `ultimo_calculo_grade`.

### 5.6 `06_aggregate_to_der_segments.py`

Cruza os rasters oficiais de RF INPE com trechos DER.

**Regra de agregacao implementada (operacional rodoviaria):**

1. Para cada trecho, amostrar pontos ao longo da geometria.
2. Ler o RF oficial INPE nos pontos amostrados.
3. **`rf_valor` do trecho = maximo** dos valores amostrados
   (conservador).
4. **`rf_classe` = classe do valor maximo**.
5. Registrar tambem `rf_p90` e `rf_media` para diagnostico.

Regra futura opcional: trocar amostragem por intersecao de buffer lateral
com raster, se for necessario maior robustez espacial.

**Saida canonica:**

`data/queimadas/processed/risco_trechos_der.gpkg`

Layer `risco_diario`: uma linha por (`trecho_id`, `data_referencia`,
`horizonte`). Horizontes atuais: `observado`, `D+1`, `D+2`, `D+3`.

### 5.7 `07_export_public_layers.py`

Exporta snapshot leve para o frontend:

- `static/data/queimadas/risco_trechos_der_latest.geojson`
- `static/data/queimadas/risco_trechos_der_latest.json` (metadados +
  tabela sem geometria pesada)
- `static/data/queimadas/risco_trechos_der_stats.json`

GeoJSON deve incluir geometria **simplificada** (tolerancia ~50 m).
O export atual gera uma camada `latest` para `observado` e uma camada por
horizonte (`observado`, `D+1`, `D+2`, `D+3`).

---

## 6. Esquema de dados — entradas e saidas

### 6.1 `trecho_id` (chave primaria)

Gerar de forma deterministica, por exemplo:

```text
trecho_id = SHA1( rodovia + "|" + str(km_ini) + "|" + str(km_fim)
                  + "|" + orientacao )[:16]
```

Nunca usar indice de linha do shapefile (instavel entre versoes).

### 6.2 Tabela `risco_diario` (processed)

| Campo | Tipo | Descricao |
| --- | --- | --- |
| `trecho_id` | string | PK logica |
| `data_referencia` | date | Dia do calculo (D) |
| `horizonte` | enum | `observado`, `D+1`..`D+3` atualmente |
| `data_alvo` | date | Dia ao qual o RF se refere |
| `rf_valor` | float | 0..1+ (continuo INPE) |
| `rf_classe` | enum | minimo..critico |
| `rf_p90` | float | diagnostico |
| `rf_media` | float | diagnostico |
| `metodologia` | string | `INPE-RF-oficial` / `INPE-RF-v11` |
| `fonte_precipitacao` | string | Interna ao RF INPE oficial; `IMERG` apenas em recálculo local |
| `fonte_meteo` | string | Interna ao RF INPE oficial; `GFS` apenas em recálculo local |
| `focos_correcao` | bool | True se correção de focos for aplicada localmente no futuro |
| `gerado_em` | datetime UTC | timestamp pipeline |
| `pipeline_run_id` | string | UUID da execucao |

Atributos DER copiados sem renomear (secao 1.3).

### 6.3 JSON publico (`risco_trechos_der_latest.json`)

```json
{
  "modulo": "queimadas",
  "metodologia": "INPE-RF-v11",
  "data_referencia": "2026-06-22",
  "gerado_em": "2026-06-22T09:00:00Z",
  "horizontes_disponiveis": ["observado", "D+1", "D+2", "D+3"],
  "classes": ["minimo", "baixo", "medio", "alto", "critico"],
  "total_trechos": 161,
  "trechos": [ "..." ]
}
```

### 6.4 GeoJSON publico

FeatureCollection; cada Feature = um trecho; properties incluem campos de
`risco_diario` para `horizonte=observado` por default; demais horizontes
via API ou propriedades aninhadas `previsao[D+1]..`.

---

## 7. Integracao runtime (Flask)

### 7.1 Modulo a criar: `core/fire_risk.py`

Responsabilidades **somente leitura**:

- Carregar `processed/risco_trechos_der.gpkg` ou JSON latest.
- Cache em memoria com reload por mtime (mesmo padrao de `zones.py`).
- Expor funcoes:
  - `get_fire_risk_snapshot(horizonte="observado")`
  - `get_fire_risk_by_trecho(trecho_id, horizonte=...)`
  - `get_fire_risk_geojson(horizonte=...)`

Sem download HTTP no request cycle.

### 7.2 Endpoints REST planejados (`app.py`)

| Metodo | Rota | Descricao |
| --- | --- | --- |
| GET | `/api/public/fire-risk/layers` | GeoJSON trechos + RF |
| GET | `/api/public/fire-risk/snapshot` | JSON resumo estadual |
| GET | `/api/public/fire-risk/trecho/<trecho_id>` | Detalhe do trecho + horizontes disponiveis |

Autenticacao: mesma politica dos feeds publicos UA.

### 7.3 Scheduler (automatizado — implementado)

Runner automatico **dentro do backend**, isolado do ciclo MERGE, em
`core/fire_pipeline.py` e ativado no boot por `app.py` (mesmo
`BackgroundScheduler` do MERGE, job `fire_refresh`):

1. **Polling barato**: a cada `QUEIMADAS_POLL_MIN` (default 30 min) le
   apenas a **listagem HTML** do diretorio observado do INPE e descobre o
   ultimo arquivo `INPE_FireRiskModel_2.2_FireRisk_YYYYMMDD.nc` publicado.
2. **Disparo condicional**: so roda o pipeline pesado `05 -> 06 -> 07`
   (via **subprocess isolado**) quando aparece arquivo novo (ou quando os
   produtos locais estao defasados/ausentes). Um arquivo novo do INPE eh
   processado no proximo ciclo de polling — comportamento "quase tempo
   real" para um produto que o INPE publica diariamente.
3. **Boot catch-up**: no start, se ja existe produto com a data de hoje,
   apenas registra o marker e entra em modo polling; se estiver defasado,
   roda o pipeline em background sem bloquear o boot do gunicorn.
4. **Isolamento e seguranca**: subprocess evita que download/rasterio/
   geopandas derrubem o web worker; `data/queimadas/metadata/auto_runner.json`
   guarda o ultimo arquivo processado; lock em arquivo
   (`.auto_runner.lock`) evita execucoes concorrentes entre workers do
   gunicorn. `core/fire_risk.py` recarrega o cache por mtime apos cada
   atualizacao.

Como o runner escreve direto em `data/queimadas/` e
`static/data/queimadas/` do proprio container, **nao** ha mais
necessidade de `sync-data-vm.bat` para o ciclo diario de queimadas (o
sync manual segue util apenas para a malha base e cargas pontuais).

Variaveis de ambiente:

| Variavel | Default | Uso |
| --- | --- | --- |
| `QUEIMADAS_AUTO` | `1` | Liga/desliga o runner automatico |
| `QUEIMADAS_POLL_MIN` | `30` | Intervalo de polling do INPE (min) |
| `QUEIMADAS_RUN_TIMEOUT_S` | `1800` | Timeout de cada etapa do pipeline |
| `QUEIMADAS_DATA_DIR` | `data/queimadas` | Raiz do modulo |

Variaveis como `QUEIMADAS_BUFFER_M`, `QUEIMADAS_GFS_CYCLE`,
`QUEIMADAS_PREC_SOURCE` e `EARTHDATA_TOKEN` ficam reservadas para
recálculo local futuro.

### 7.4 Frontend (`static/app.js`)

Camada nova **independente**:

- Nome sugerido: `Risco de queimadas (trechos DER-SP)`.
- Estilo por `rf_classe` (paleta INPE: verde → marrom).
- Popup: rodovia, km, rf_valor, classe, horizonte, data_alvo.
- **Nao** misturar simbologia RD (0-4 DER-SP) com RF INPE (5 classes).
- Filtro em `query-filter.js`: campos `rf_classe`, `rodovia`, `regional`.

Toggle de horizonte: observado / D+1 / D+2 / D+3.

---

## 8. Operacao e execucao completa

### 8.1 Bootstrap inicial (uma vez)

```cmd
cd D:\REPOSITORIOS\PLI-HazardTrack

:: 1. Base estatica
python ferramentas/queimadas/01_prepare_base_layers.py

:: 2. Primeiro ciclo completo
python ferramentas/queimadas/05_compute_rf_grid.py
python ferramentas/queimadas/06_aggregate_to_der_segments.py
python ferramentas/queimadas/07_export_public_layers.py
```

### 8.2 Rotina diaria

```cmd
python ferramentas/queimadas/05_compute_rf_grid.py --date today
python ferramentas/queimadas/06_aggregate_to_der_segments.py --date today
python ferramentas/queimadas/07_export_public_layers.py --date today
```

### 8.3 Pos-deploy

1. Definir `QUEIMADAS_ENABLED=1`.
2. Confirmar arquivos em `static/data/queimadas/`.
3. Hit em `/api/public/fire-risk/snapshot`.
4. Validar mapa web.

### 8.4 Tratamento de falhas

| Falha | Comportamento |
| --- | --- |
| RF observado INPE indisponivel | Manter ultimo `latest` valido; se nao existir, `SEM_DADO` |
| RF previsto INPE indisponivel | Publicar apenas horizontes disponiveis |
| Raster sem valor no trecho | `rf_classe=SEM_DADO` apenas naquele trecho/horizonte |
| Pipeline incompleto | Manter ultimo `*_latest.*`; nunca inventar RF |

Politica alinhada ao PLI: **sem dado = SEM_DADO**, nunca mock operacional.

---

## 9. Dependencias Python adicionais

Dependencias do modulo:

| Pacote | Uso |
| --- | --- |
| `rasterio` | Ler GeoTIFF/NetCDF georreferenciado do RF INPE |
| `xarray` | Opcional para reprocessamento NetCDF futuro |
| `cfgrib` / `eccodes` | Opcional para GFS futuro (eccodes ja no projeto) |
| `pyproj` | Projecoes |
| `pandas` | Tabelas long |
| `pyarrow` | Parquet (opcional) |

`rasterio` e dependencia operacional atual.

Credenciais:

- RF INPE oficial: sem credencial.
- NASA Earthdata para IMERG (`.netrc` ou `EARTHDATA_TOKEN`) apenas se
  houver recálculo local futuro.

---

## 10. Testes

Testes atuais e recomendados:

- `tests/test_fire_risk.py` carrega snapshot e GeoJSON publico sem erro.
- Endpoint `/api/public/fire-risk/snapshot` deve retornar 200.
- Endpoint `/api/public/fire-risk/layers?horizonte=D%2B1` deve retornar
  camada D+1 quando o produto existir.
- `trecho_id` deve ser estavel entre execucoes de `01_`.
- Agregacao maxima: trecho com celula critica deve virar classe critica.

Teste de regressao metodologica opcional: comparar amostra de celulas com
portal INPE Queimadas para mesmo dia/bbox.

---

## 11. Checklist para agente de IA (replicacao end-to-end)

Use esta lista como definicao de pronto:

- [ ] Pastas secao 3.2 criadas
- [ ] `01_prepare_base_layers.py` gera `base/trechos_der_sp.gpkg` com
      `trecho_id`
- [x] `05_compute_rf_grid.py` baixa RF oficial INPE observado/previsto
- [x] `06_aggregate_to_der_segments.py` agrega maximo amostrado por trecho
- [x] `07_export_public_layers.py` publica GeoJSON/JSON latest e por horizonte
- [x] `core/fire_risk.py` le produto sem download no ciclo HTTP
- [x] Endpoints `/api/public/fire-risk/*` registrados em `app.py`
- [x] Camada mapa e popup em `static/app.js`
- [x] Testes `tests/test_fire_risk.py` passando
- [x] `metadata/manifest.json` atualizado
- [x] Nenhuma alteracao indevida em `core/risk.py` / `aggregator.py`
- [ ] Cron diario configurado em producao
- [ ] Focos INPE integrados como camada de ocorrencia/auditoria
- [ ] Filtros especificos de queimadas em `static/query-filter.js`

---

## 12. Limites da abordagem atual e melhorias futuras

### 12.1 Limites operacionais

O RF oficial INPE usado pelo modulo tem resolucao aproximada de
**0,1 grau (~10 km)**. Essa resolucao e adequada para:

- triagem estadual;
- priorizacao por regional/rodovia;
- vigilancia preventiva diaria;
- comunicacao de condicao ambiental favoravel a queimadas.

Ela **nao** e suficiente, sozinha, para alerta fino por trecho DER muito
curto. A malha DER preparada possui trechos de poucos metros; o menor
trecho identificado no momento tem **0,028 km (28 m)**. Isso significa
que um unico pixel de RF INPE pode cobrir centenas de trechos curtos.

Interpretacao correta: o sistema informa que um trecho **atravessa uma
area de risco RF INPE**, e nao que o risco foi calculado em escala
fisica daquele trecho.

### 12.2 Melhorias futuras recomendadas

Para transformar a camada em um alerta rodoviario mais fino e
operacionalmente defensavel, combinar o RF INPE com fatores locais:

1. **Focos ativos INPE/SMAC/Waze/cameras**: camada de ocorrencia real,
   atualizada em horas/minutos, separada do risco diario.
2. **MapBiomas por buffer de trecho**: criar indicador estatico de
   combustivel local (`potencial_combustivel`) por faixa de dominio ou
   buffer lateral (ex.: 100 m, 500 m, 1000 m).
3. **Proximidade a vegetacao/UC/area rural**: classificar trechos com
   maior exposicao a material combustivel.
4. **Historico de focos/area queimada**: priorizar trechos com recorrencia
   de eventos.
5. **Agregacao por buffer raster**: substituir amostragem de pontos ao
   longo do eixo por estatisticas zonais (maximo, P90, media) no buffer
   do trecho.
6. **Modelo composto DER-SP**: combinar RF INPE (clima), combustivel local
   (MapBiomas), exposicao rodoviaria e focos recentes em um indice proprio
   de prioridade operacional.

MapBiomas, portanto, nao melhora diretamente o RF INPE oficial ja
calculado; ele melhora a **explicacao e refinamento local** do risco por
trecho, e e obrigatorio apenas se o projeto decidir recalcular o RF
localmente ou criar um indice composto rodoviario.

---

## 13. Referencias

- INPE RF v11:
  [documento oficial](https://dataserver-coids.inpe.br/queimadas/queimadas/Publicacoes-Impacto/documentos/RiscoFogo_Sucinto.pdf)
- Programa Queimadas INPE:
  [portal](http://queimadas.dgi.inpe.br/queimadas/portal)
- IMERG GPM: [dados IMERG](https://gpm.nasa.gov/data/imerg)
- GFS NOAA:
  [Global Forecast](https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast)
- MapBiomas: [mapbiomas.org](https://mapbiomas.org/)
- INMET Risco de Incendio:
  [servico](https://portal.inmet.gov.br/servicos/risco-de-incendio)
- Malha DER-SP (dados abertos SP):
  [dadosabertos.sp.gov.br](https://dadosabertos.sp.gov.br/)
- Defesa Civil SP / Climatempo (referencia operacional, nao fonte):
  [painel previsao](https://admin.defesacivil.sp.gov.br/previsaodotempo/sp)

---

## 14. Status deste documento

| Campo | Valor |
| --- | --- |
| Versao spec | 1.1 |
| Status implementacao | Operacional com RF oficial INPE |
| Metodologia canonica | RF oficial INPE / INPE RF v11 |
| Unidade de saida | Trecho DER-SP |
| Cobertura | Estado de Sao Paulo |
| Resolucao fonte | ~0,1 grau / ~10 km |
| Horizontes atuais | observado, D+1, D+2, D+3 |

Atualize `metadata/manifest.json` quando mudar fonte, horizonte ou regra
de agregacao.
