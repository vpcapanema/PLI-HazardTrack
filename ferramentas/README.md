# Ferramentas auxiliares

Scripts, relatorios e artefatos de apoio **fora do backend operacional**
(`app.py`, `core/`, `static/`, `templates/`). Nenhum destes arquivos e
carregado em tempo de execucao da aplicacao.

Os **dados gerados** que o sistema consome permanecem em `data/`
(`data/pli-hazardtrack.gpkg`, `data/ua_zones/ua_geo.geojson`,
`data/ua_zones/ua_hidro.geojson`, malha DER e regioes).

| Pasta | Conteudo |
| --- | --- |
| [geracao-geopackage/](geracao-geopackage/) | Pipeline **oficial** do GeoPackage `pli-hazardtrack.gpkg` e dos GeoJSONs de UA |
| [extracao-ra/](extracao-ra/) | Extracao dos RA oficiais (Relatorio 2053-R04-21) |
| [relatorios-plano-contingencia/](relatorios-plano-contingencia/) | PDFs, `ra_official.py`, documentacao metodologica |
| [preparacao-geodata/](preparacao-geodata/) | Scripts one-shot para malha DER, regioes, camadas admin |
| [queimadas/](queimadas/) | Pipeline isolado para risco estadual de queimadas por trecho DER-SP |
| [exploracao-georef/](exploracao-georef/) | POCs de georreferenciamento, probes, testes MERGE |
| [integracao-pendente/](integracao-pendente/) | Modulos prontos fora do pipeline (ex.: DAEE) |
| [deploy-legado/](deploy-legado/) | Deploy VM desativado (historico) |
| [geracao-uas/](geracao-uas/) | **ARQUIVADO** - pipeline antigo de poligonos. Scripts mantidos como `_obsoleto_*.py.bak` apenas para referencia |

## Regenerar GeoJSONs consumidos pelo backend (fluxo principal)

O GeoPackage `data/pli-hazardtrack.gpkg` e a unica fonte de verdade.
Os GeoJSONs lidos em runtime sao exports diretos dele:

```cmd
python ferramentas/geracao-geopackage/04_export_ua_geojsons.py
python ferramentas/geracao-geopackage/05_export_regioes_geojson.py
```

`04_export_ua_geojsons.py` produz dois mono-canais a partir de
`uas_area_estudo`. Cada feature carrega **todos** os atributos
nativos da camada-mae (`ua_id`, `regiao_id`, `sigla_rodovia`,
`km_inicial`/`km_final`, `residencia_dr`, `regional`, `uba_*`,
`municipio`, `centroide_*` etc.) menos o atributo de RA do outro canal:

- `data/ua_zones/ua_geo.geojson`   -> `RAGEO`, `icc_geo_thresholds`,
  `trecho_critico_geo`
- `data/ua_zones/ua_hidro.geojson` -> `RAHID`, `icc_hid_thresholds`,
  `trecho_critico_hid`

`05_export_regioes_geojson.py` produz a camada "Regioes monitoradas"
do mapa a partir de `regioes_estudo` (4 Polygons) + dissolucao de
`auxilio_regioes_estudo` por `regiao_id` (eixos):

- `data/regioes/regioes_estudo.geojson` -> 4 features Polygon com
  TODOS os atributos nativos (regiao_id, regiao_nome, sigla_rodovia,
  km_inicial/km_final, extensao_oficial_km, municipios, ubas,
  residencias_dr, regionais, jurisdicoes, conservado_por,
  subtrechos_der, area_km2, perimetro_km, buffer_lateral_m, ...) MAIS
  os parametros climaticos (`k_geo`, `cpc_breaks`, `hid24h_breaks`)
  das Tabelas 3.1.1-2 e 3.1.2-1 do PRODUTO 6 (REGEA-NIPPON, 2021).
- `data/regioes/regioes_eixos.geojson` -> 4 features LineString
  (eixo cadastral da rodovia por regiao), consumido pelo backend
  para `find_nearest_region_for_point`.

Para reconstruir a camada-mae no GPKG (raro), rode os passos 01..03
de `ferramentas/geracao-geopackage/` antes dos passos 04 e 05.
