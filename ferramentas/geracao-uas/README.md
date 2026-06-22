# [OBSOLETO] geracao-uas/

Este diretorio continha o pipeline antigo de geracao das UAs a partir do
PDF do Produto 7 (extracao por cor das figuras 3.3.3-x + buffering 500 m
no eixo da malha rodoviaria DER).

Esse pipeline foi DESCONTINUADO. A camada operacional `uas_area_estudo`
agora e gerada **diretamente do GeoPackage** com base nos km cadastrais
oficiais e nas tabelas do Produto 7 (sem amostragem por imagem).

## Pipeline atual

1. `ferramentas/geracao-geopackage/03_uas_area_estudo.py` constroi as 809
   UAs em `data/pli-hazardtrack.gpkg` (camada `uas_area_estudo`), com
   UTBs continuas e SRs dentro dos trechos criticos.
2. `ferramentas/geracao-geopackage/04_export_ua_geojsons.py` exporta a
   camada em dois GeoJSONs mono-canal consumidos pelo backend:
   - `data/ua_zones/ua_geo.geojson` (RAGEO, ICC GEO)
   - `data/ua_zones/ua_hidro.geojson` (RAHID, ICC HID)
3. `core/zones.py` le esses GeoJSONs com os ATRIBUTOS NATIVOS da camada
   (ua_id, sigla_rodovia, regiao_id, RAGEO, etc.) - sem renomear.

## O que ficou arquivado aqui

Os scripts foram preservados como `_obsoleto_*.py.bak` apenas para
referencia historica e arqueologia do processo de extracao por imagem.
Nao usar mais.

| Arquivo | O que fazia |
|---------|-------------|
| `_obsoleto_build_ua_polygons.py.bak` | Buffer 500 m + cortes municipais/escala |
| `_obsoleto_assign_ra_to_uas.py.bak` | Amostragem RA0..4 nas figuras do PDF |
| `_obsoleto_export_ua_split.py.bak` | Divisao em ua_geo / ua_hidro (formato antigo) |
| `_obsoleto_validate_ua_zones.py.bak` | Comparacao com Tabelas 3.3.3.1-3/-4 |
| `_obsoleto_build_ua_segments.py.bak` | Linhas DER pre-UAs (legado) |
| `_obsoleto_ua_segments_loader.py.bak` | Leitor das linhas DER (legado) |
| `_obsoleto_ua_figure_utils.py.bak` | Georef UTM + amostragem de pixel |
| `_obsoleto_ua_ra_budgets.py.bak` | Orcamentos RA por (regiao, escala) |
| `_obsoleto__diag_polys.py.bak` | Overlay diagnostico nas figuras |
