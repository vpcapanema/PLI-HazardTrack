# AGENTS.md - PLI-HazardTrack

## Sistema
Sistema Automatizado de Monitoramento, Analise e Alerta Geodinamico
para rodovias da Regiao do Litoral Norte de Sao Paulo (DER-SP).

## Build e Test
- Interpretador: `.venv/Scripts/python.exe` (Python 3.12). Atalho: `.\run.ps1`.
- `.\run.ps1 -m unittest discover -s tests -p "test_*.py"` - roda todos os testes
- `.\run.ps1 -m flake8 .` - lint (Flake8 do venv)
- Limite de linha: 79 caracteres (Flake8)

## Arquitetura
- `app.py` - Flask backend + scheduler
- `core/risk.py` - Calculo de Risco Dinamico (RD = RA x ICC)
- `core/zones.py` - Carrega 809 UAs de
  `data/ua_zones/ua_geo.geojson` + `ua_hidro.geojson` com os ATRIBUTOS
  NATIVOS de `uas_area_estudo` (ua_id, sigla_rodovia, regiao_id,
  RAGEO/RAHID, km_inicial/km_final, residencia_dr, regional, uba_*,
  icc_*_thresholds, trecho_critico_*). NAO renomeia, NAO normaliza.
- `core/ua_public_feed.py` - Feed publico `/api/public/ua-layers`
  (FeatureCollection com os mesmos atributos nativos + campos
  calculados rd/nivel/ac96h_mm/...).
- `core/aggregator.py` - Agrega dados de chuva + risco; propaga
  atributos nativos da UA em cada ponto do snapshot.
- `core/merge_inpe.py` - Download/decode MERGE/INPE (ThreadPool + ProcessPool)
- `core/merge_ingest.py` - Ingest continuo em background + cache RAM incremental
- `core/forecast_wrf_prec_hourly.py` - Previsao WRF (composicao PDF)
- `core/regions.py` - Poligonos das 4 regioes monitoradas. Le exclusivamente
  `data/regioes/regioes_estudo.geojson` (poligonos com TODOS os atributos
  nativos da camada-mae `regioes_estudo` do GPKG: regiao_id, regiao_nome,
  sigla_rodovia, km_inicial/km_final, extensao_oficial_km, municipios,
  ubas, residencias_dr, regionais, jurisdicoes, conservado_por,
  subtrechos_der, area_km2, perimetro_km, buffer_lateral_m, e tambem
  k_geo/cpc_breaks/hid24h_breaks injetados a partir das Tabelas
  3.1.1-2 e 3.1.2-1 do PRODUTO 6) + `data/regioes/regioes_eixos.geojson`
  (eixo da rodovia por regiao, dissolvido de `auxilio_regioes_estudo`,
  usado por `find_nearest_region_for_point`). O snapshot expoe esses
  atributos nativos em `snap.regions[*]` (mais aliases legados
  `id`/`nome`/`rodovia`), e o frontend popula a camada "Regioes
  monitoradas" no mapa direto deles.
- `static/app.js` - Frontend (mapa, paineis, popups). Le os ATRIBUTOS
  NATIVOS direto da camada (`p.ua_id`, `p.sigla_rodovia`, `p.RAGEO`,
  `p.RAHID`, `p.km_inicial`, `p.km_final`, `p.residencia_dr`,
  `p.regional`, `p.uba_codigo`, `p.regiao_nome`, ...).
- `static/query-filter.js` - Mesma convencao de nomes para o filtro
  por atributo (campos do tipo `RAGEO`, `regiao_id`, `sigla_rodovia`,
  `trecho_critico_*`, etc.).
- `ferramentas/relatorios-plano-contingencia/ra_official.py` - Tabelas RA trechos criticos

## Pipeline MERGE (chuva)
- Thread `merge-ingest` atualiza cache a cada `SAMAEG_INGEST_INTERVAL_S` (120s)
- Cache em DOIS niveis (`core/merge_cache.py`):
  * RAM (samples por hora) consumido pelo `aggregator`
  * Disco (`data/_cache/merge/`) sobrevive a reinicios:
    - `grib/AAAA-MM-DD/HH.grib2`: GRIB bruto (re-decode se mudar a malha
      de UAs)
    - `samples/<coords_hash>/AAAA-MM-DD/HH.json`: valores ja interpolados
      nos centroides (hit = zero download + zero decode)
- Boot hidrata o cache RAM a partir do disco antes de baixar (cold start
  cai de ~96 downloads para apenas as horas frescas/ausentes)
- Politica de refetch baseada na IDADE do dado (`should_refetch` em
  `merge_cache.py`):
  * idade < `SAMAEG_REFETCH_FRESH_H` (4h): sempre re-baixa
    (CPTEC pode republicar)
  * idade >= `SAMAEG_REFETCH_STALE_H` (24h): nunca re-baixa (dado final)
  * faixa intermediaria: no maximo 1x/dia
- **VM**: volume Docker `pli_hazardtrack_merge_cache` em
  `/app/data/_cache/merge` (`SAMAEG_MERGE_CACHE_DIR`). Volume legado
  `/app/cache` nao era usado. Seed do dev: `.\sync-merge-cache-vm.ps1`.
- Download HTTP: `SAMAEG_WORKERS` (12) com sessao keep-alive + cache disco
- Decode eccodes: `SAMAEG_DECODE_WORKERS` (6) em `ProcessPoolExecutor`
  singleton mantido vivo entre waves/ciclos (elimina overhead de spawn
  ~300ms/worker no Windows)
- `aggregator` le apenas `ingest.get_rain_batch()` (sem download no ciclo de RD)

## Regras de Risco (Metodologia DER-SP)
- RD = max(RDGEO, RDHID)
- RDGEO = RAGEO x ICCGEO (chuva intensidade)
- RDHID = RAHID x ICCHID (chuva 24h)
- Niveis: 0=Monitoramento, 1=Observacao, 2=Atencao, 3=Alerta, 4=Alerta Maximo

## Dados Oficiais Implementados
1. **RA por trecho**: Tabelas 3.3.3.1-3 e 3.3.3.1-4 do Relatorio 2053-R04-21
 (`ferramentas/relatorios-plano-contingencia/ra_official.py`)
 - 6 trechos geologicos mapeados (SP-055, SP-098)
 - 5 trechos hidrologicos mapeados
 - Pontos sem dado retornam RA=None (SEM_DADO)

2. **Shapefile DER/SP**: Malha rodoviaria oficial do portal dadosabertos.sp.gov.br
 - 161 trechos de 15 rodovias
 - CRS: EPSG:4326 (WGS84)

3. **Previsao**: CPTEC/INPE (http://servicos.cptec.inpe.br/XML/)
 - Substitui Open-Meteo (fonte internacional generica)

4. **GeoPackage oficial**: `data/pli-hazardtrack.gpkg` (EPSG:4326),
 fonte unica das camadas geograficas estruturais do sistema:
 - `municipios_area_estudo` (7 features): poligonos dos 7 municipios
   da area de estudo (Mogi das Cruzes, Santos, Bertioga, Biritiba
   Mirim, Sao Sebastiao, Caraguatatuba, Ubatuba), extraidos do
   shape oficial DRADT 2021.
 - `auxilio_regioes_estudo` (23 LineStrings): 1 feature por subtrecho
   cadastral oficial DER que cai na area de estudo
   (`MALHA_RODOVIARIA.shp`). Tem `regiao_id` (1..4), `extensao_km`
   cadastral (NAO usar comprimento geometrico), `uba_nome`,
   `uba_codigo`, `municipio`, `regional`, `residencia_dr`,
   `jurisdicao`, `conservado_por`, `subtrecho_der`. Soma de
   `extensao_km` por regiao bate ao mm com a Tabela 2-1 do PRODUTO 7
   (R1=35.200, R2=58.950, R3=78.850, R4=56.700; total 229.700 km).
 - `uas_area_estudo` (809 LineStrings): Unidades de Analise reconstruidas
   FIELMENTE conforme metodologia oficial do PRODUTO 7 (Relatorio
   2053-R04-21, paginas 34 e 71). Combinam duas naturezas espaciais:
   * **UTBs (1:25.000 e 1:10.000)** - "Unidades Territoriais Basicas",
     cobertura REGULAR contigua ao longo de cada (Regiao x Municipio),
     ~340-1400 m por UA. Sao 398 UTBs cobrindo trechos NAO-criticos
     da rodovia (sequencialmente desde o km inicial do municipio).
   * **SRs (1:1.000)** - "Setores de Risco", 411 segmentos detalhados
     posicionados DENTRO dos trechos criticos oficiais
     (Tabelas 3.3.3.1-1 GEO e 3.3.3.1-2 HID): R1 km 77-98, R2 km 53.6-102,
     R3 km 114-127.8 + 128-153 + 156-162, R4 km 235-238 (GEO);
     R3 km 178.1-191.4, R4 km 191.4-223.6, R2 km 93/97/112 (HID).
     UTBs e SRs cobrem segmentos COMPLEMENTARES (nao se sobrepoem).
   Atributos: identificacao (`ua_id`, `regiao_id`, `escala` 25K/10K/1K,
   `tipo` UTB/SR, `extensao_km`, `ordem_no_grupo`), linear referencing
   (`km_inicial`, `km_final`, `subtrecho_der`), herdados (`municipio`,
   `regional`, `residencia_dr`, `uba_nome`, `uba_codigo`, `jurisdicao`,
   `conservado_por`), ICC denormalizado (`icc_geo_thresholds` em CPC e
   `icc_hid_thresholds` em mm/24h - Tabelas 3.2.2-2 e 3.2.3-1 do
   PRODUTO 7), geometria auxiliar (`centroide_lon`, `centroide_lat`,
   `buffer_lateral_m`=1000), flags **`trecho_critico_geo` /
   `trecho_critico_hid`** (bool, se centroide cai no trecho oficial)
   e **RAGEO/RAHID atribuidos** (0..4) conforme as Tabelas 3.3.1-2 e
   3.3.2-2 do PRODUTO 7. A distribuicao ESPACIAL das classes dentro de
   cada grupo (Regiao x Escala) eh guiada por extracao de cor (pixel-
   mais-proximo do eixo) sobre as Figuras 3.3.3-x do PRODUTO 7 em
   alta resolucao. Totais oficiais conferidos EXATAMENTE:
   RAGEO {RA0=39, RA1=396, RA2=106, RA3=127, RA4=141};
   RAHID {RA0=441, RA1=335, RA2=19, RA3=14, RA4=0}.
   Totais: 63 UTBs 25K + 335 UTBs 10K + 411 SRs 1K = 809 UAs.
 - `regioes_estudo` (4 Polygons): regioes operacionais geradas por
   dissolucao (`linemerge`) dos subtrechos contiguos da camada
   auxiliar + buffer lateral de 1000 m com `cap_style="flat"` (para
   que emendas R2-R3 e R3-R4 coincidam aresta-a-aresta com distancia
   = 0 m) + `Point.buffer(1000)` nas pontas absolutas
   (R1: inicio+fim na SP-098; R2: inicio km 53.6 em Ubatuba;
   R3: nenhuma; R4: fim km 248.1 em Santos). Atributos incluem
   `km_inicial`/`km_final`/`extensao_oficial_km` cadastrais,
   `municipios`/`ubas`/`residencias_dr` (CSV `;`),
   `area_km2`, `perimetro_km` e flag `tampas_round`.
 - Geracao das camadas estruturais: `ferramentas/geracao-geopackage/`
   (scripts 01 a 05):
   * `01_municipios_area_estudo.py` - 7 municipios
   * `02_regioes_estudo.py` - regioes + auxilio_regioes_estudo
   * `03_uas_area_estudo.py` - 809 UAs (UTBs + SRs - metodologia
     oficial UTBs+SRs descrita acima).
   * `04_export_ua_geojsons.py` - exporta `uas_area_estudo` em DOIS
     GeoJSONs mono-canal consumidos pelo backend:
       `data/ua_zones/ua_geo.geojson`   (RAGEO + ICC GEO)
       `data/ua_zones/ua_hidro.geojson` (RAHID + ICC HID)
     Sem renomear/normalizar: cada feature carrega todos os atributos
     da camada-mae menos os do canal oposto, mais `hazard="geo"|
     "hidro"`. Sistemas externos consomem direto via spatial join
     em `ua_id` (sem arquivos intermediarios).
   * `05_export_regioes_geojson.py` - exporta `regioes_estudo`
     (poligonos) + `auxilio_regioes_estudo` dissolvido por
     `regiao_id` (eixos) em dois GeoJSONs:
       `data/regioes/regioes_estudo.geojson`  (4 Polygons com TODOS
         os atributos nativos + k_geo/cpc_breaks/hid24h_breaks das
         Tabelas 3.1.1-2/3.1.2-1 do PRODUTO 6)
       `data/regioes/regioes_eixos.geojson`   (4 LineStrings - eixo
         da rodovia por regiao, usado por nearest-eixo)
     Sao essas duas saidas que `core/regions.py` carrega no boot.
 - Tabelas oficiais codificadas: `ferramentas/extracao-ra/40_oficial_tabelas.py`
   (Tabelas 3.3-1, 3.3.1-2, 3.3.2-2, 3.3.3.1-1/-2/-3/-4, 3.2.2-2,
   3.2.3-1). Eh a fonte de verdade para qualquer re-atribuicao
   futura de RAGEO/RAHID. Os valores ja estao consolidados na
   coluna `RAGEO`/`RAHID` de `uas_area_estudo`.
 - Scripts auxiliares antigos de extracao por cor / OBIA / preview
   (`01_*.py`..`15_*.py`, `41_*`, `42_*`, `90_*`) foram arquivados
   em `ferramentas/extracao-ra/_obsoleto_*.py.bak` por dependerem
   de camadas intermediarias removidas
   (`ra_geologico_linha`/`continuo`, `ra_hidrologico_linha`/`continuo`).
 - Politica de sobreposicao: R1 (SP-098) e R4 (SP-055) se cruzam em
   Bertioga (~3.77 km^2) por serem rodovias diferentes que se
   encontram no mesmo no urbano - mantido (semantica fisica real).
 - Versao anterior das regioes, extraida da Figura 3.2.1-1 por
   segmentacao de cor, foi ARQUIVADA em `data/_obsoleto_regioes_pli/`
   (apenas auditoria; nao mais consumida pelo backend).

## Politica Critica
- **NUNCA inventar RA**. Sem dado oficial = SEM_DADO.
- **NUNCA usar shapefile aproximado**. Usar apenas dados oficiais.
- **NUNCA usar previsao generica**. Usar fontes calibradas para o Brasil.

## Gaps Conhecidos
- RA nao mapeado para rodovias secundarias (SP 131, SPA, etc.)
- Previsao CPTEC fornece condicoes, nao precipitacao em mm exata
- Modulo DAEE em `ferramentas/integracao-pendente/` (nao integrado ao pipeline)
- Divisas internas das UAs (~91%) sao interpoladas; vetor IG (Anexo B) indisponivel

## Ferramentas auxiliares
Scripts de geracao de UAs e preparacao de dados em `ferramentas/`
(ver README de cada subpasta).

Regenerar as camadas geograficas consumidas pelo backend:

```
python ferramentas/geracao-geopackage/03_uas_area_estudo.py
python ferramentas/geracao-geopackage/04_export_ua_geojsons.py
python ferramentas/geracao-geopackage/05_export_regioes_geojson.py
```

O backend (`core/zones.py` para UAs, `core/regions.py` para regioes)
recarrega automaticamente quando o mtime dos GeoJSONs muda. Nao ha
mais step de "atribuicao de RA por imagem": RAGEO/RAHID ja vem
persistidos na camada `uas_area_estudo` desde a geracao (script 03).

O pipeline antigo de geracao a partir do PDF (extracao de cor nas
figuras 3.3.3-x + buffer no eixo da malha DER) foi arquivado em
`ferramentas/geracao-uas/_obsoleto_*.py.bak` (so para arqueologia).
Modulos `core/ua_der_enrich.py` e `core/der_units.py` foram
arquivados como `_obsoleto_*.py.bak` em `core/` pelo mesmo motivo:
hoje os atributos administrativos DER vem nativos da camada
`uas_area_estudo`. Dados legados em `data/_obsoleto_ua_polygons/`,
`data/_obsoleto_ua_segments/` e `data/_obsoleto_regioes_pli/`.
