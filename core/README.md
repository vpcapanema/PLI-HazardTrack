# core/ — Backend operacional

Modulos carregados em tempo de execucao por `app.py` e pelo ciclo
MERGE → risco → alerta. **Nao inclui** scripts de geracao de dados nem
tabelas estaticas extraidas dos relatorios (ver `ferramentas/`).

## Modulos ativos

| Modulo | Funcao |
|--------|--------|
| `aggregator.py` | Orquestra ciclo: chuva MERGE, previsao WRF, RD por UA; propaga atributos NATIVOS de `uas_area_estudo` em cada ponto |
| `zones.py` | Carrega `ua_geo.geojson` + `ua_hidro.geojson` (809 UAs) com `ua_id`, `sigla_rodovia`, `regiao_id`, `RAGEO`/`RAHID`, `km_inicial`/`km_final`, `residencia_dr`, `regional`, `uba_*`, `icc_*_thresholds`, `trecho_critico_*` |
| `ua_public_feed.py` | Feed publico `/api/public/ua-layers` (mesmos atributos nativos + calculados rd/nivel/ac96h_mm/...) |
| `regions.py` | Carrega 4 regioes monitoradas de `data/regioes/regioes_estudo.geojson` (atributos nativos: `regiao_id`, `regiao_nome`, `sigla_rodovia`, `km_inicial`/`km_final`, `area_km2`, `municipios`, `residencias_dr`, ...) + eixos de `data/regioes/regioes_eixos.geojson`. Snapshot expoe esses atributos para a camada "Regioes monitoradas" no mapa. |
| `risk.py` | CPC, ICC, matriz RA×ICC → RD |
| `merge_inpe.py` | Ingestao MERGE/INPE (streaming GRIB2) |
| `forecast_wrf_prec_hourly.py` | Previsao WRF para composicao PDF |
| `notifier.py` | Alertas RD≥3 (webhook, etc.) |
| `admin.py` | Area administrativa `/admin` |
| `actions.py` | Protocolos e acoes por nivel de RD |

## O que saiu de `core/`

| Antigo | Status | Motivo |
|--------|--------|--------|
| `ra_official.py` | Movido para `ferramentas/relatorios-plano-contingencia/` | Tabelas transcritas do PDF; usado por scripts e testes, nao pelo runtime |
| `ua_der_enrich.py` | Arquivado (`_obsoleto_*.py.bak`) | Atributos DER agora vem nativos da camada `uas_area_estudo` |
| `der_units.py` | Arquivado (`_obsoleto_*.py.bak`) | Idem: lookup por coordenada substituido por atributos diretos da UA |
| `ua_segments.py` | Arquivado em `ferramentas/geracao-uas/_obsoleto_*.bak` | Fallback por trecho km, substituido por `zones.py` + 809 UAs |
| `daee_rain.py` | `ferramentas/integracao-pendente/` | DAEE nao integrado ao pipeline principal |

## Dados consumidos (em `data/`)

- `pli-hazardtrack.gpkg` (camadas `uas_area_estudo`, `regioes_estudo`, `auxilio_regioes_estudo`, `municipios_area_estudo`) — fonte canonica
- `ua_zones/ua_geo.geojson` + `ua_hidro.geojson` — UAs exportadas de `uas_area_estudo` por `ferramentas/geracao-geopackage/04_export_ua_geojsons.py`
- `regioes/regioes_estudo.geojson` + `regioes/regioes_eixos.geojson` — Regioes monitoradas exportadas de `regioes_estudo` + `auxilio_regioes_estudo` por `ferramentas/geracao-geopackage/05_export_regioes_geojson.py`
- `der_sistema_rodoviario/` — malha DER oficial (camada de apoio)
- `_obsoleto_regioes_pli/` — regioes climatico-geologicas extraidas da Fig 3.2.1-1 (legado, auditoria; substituida pelos buffers de `regioes_estudo`)

Regenerar camadas:
```
python ferramentas/geracao-geopackage/03_uas_area_estudo.py
python ferramentas/geracao-geopackage/04_export_ua_geojsons.py
python ferramentas/geracao-geopackage/05_export_regioes_geojson.py
```
