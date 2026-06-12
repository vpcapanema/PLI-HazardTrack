# core/ — Backend operacional

Modulos carregados em tempo de execucao por `app.py` e pelo ciclo
MERGE → risco → alerta. **Nao inclui** scripts de geracao de dados nem
tabelas estaticas extraidas dos relatorios (ver `ferramentas/`).

## Modulos ativos

| Modulo | Funcao |
|--------|--------|
| `aggregator.py` | Orquestra ciclo: chuva MERGE, previsao WRF, RD por UA |
| `zones.py` | Carrega `ua_geo.geojson` + `ua_hidro.geojson` (809 UAs) |
| `regions.py` | Poligonos das 4 regioes DER-SP |
| `risk.py` | CPC, ICC, matriz RA×ICC → RD |
| `merge_inpe.py` | Ingestao MERGE/INPE (streaming GRIB2) |
| `forecast_wrf_prec_hourly.py` | Previsao WRF para composicao PDF |
| `notifier.py` | Alertas RD≥3 (webhook, etc.) |
| `ops.py` | Pagina operacional `/ops` |
| `actions.py` | Protocolos e acoes por nivel de RD |
| `sra_auth.py` | Autenticacao SRA (camadas restritas) |

## O que saiu de `core/`

| Antigo | Novo local | Motivo |
|--------|------------|--------|
| `ra_official.py` | `ferramentas/relatorios-plano-contingencia/` | Tabelas 3.3.3.1-3/-4 transcritas do PDF; usado por scripts e testes, nao pelo runtime |
| `ua_segments.py` | `ferramentas/geracao-uas/ua_segments_loader.py` | Fallback por trecho km; substituido por `zones.py` + 809 poligonos |
| `daee_rain.py` | `ferramentas/integracao-pendente/` | Modulo DAEE nao integrado ao pipeline principal |

## Dados consumidos (em `data/`)

- `ua_polygons/ua_polygons.geojson` — fonte canonica (geometria + RA)
- `ua_zones/ua_geo.geojson` + `ua_hidro.geojson` — malha operacional do mapa
- `der_sistema_rodoviario/` — malha DER oficial
- `regioes_pli/` — regioes climatico-geologicas

Regenerar UAs: `ferramentas/geracao-uas/README.md`.
