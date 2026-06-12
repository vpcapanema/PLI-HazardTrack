# SAMAEG-PLI / HazardTrack v0.1

Sistema Automatizado de Monitoramento, Analise e Alerta Geodinamico
para a malha rodoviaria do PLI / Resiliencia Climatica - DER-SP.

Implementa o conceito do Produto 06 do Relatorio REGEA-NIPPON 2021,
com dados reais de chuva (MERGE/CPTEC/INPE) consumidos em streaming
e o modelo oficial de Risco Dinamico (RD = RA x ICC) das 4 regioes
climaticas-geologico-geomorfologicas do litoral norte e baixada
santista de SP.

## Como rodar

```cmd
pip install -r requirements.txt
python app.py
```

Abre em http://localhost:5050 (ou na porta definida em PORT).

## Documentacao

- `ferramentas/` — scripts auxiliares por tema (geracao UAs, relatorios, geodata)
- Ver tambem READMEs em cada subpasta de `ferramentas/`

## Arquitetura

```
PLI-HazardTrack/
  app.py                       Flask + scheduler (refresh a cada 10 min)
  core/
    regions.py                 4 regioes DER-SP + classificacao por geofence
    monitoring_points.py       Pontos amostrais ao longo de SP-055 e SP-098
    merge_inpe.py              Ingestao MERGE em STREAMING (eccodes em memoria)
    risk.py                    Calculo CPC, ICC, RD conforme metodologia DER-SP
    aggregator.py              Orquestrador thread-safe do estado global
  templates/
    index.html                 Interface
  static/
    style.css                  Design PLI (verde + azul + escala de risco)
    app.js                     Auto-refresh 30s, mapa Leaflet, KPIs
```

## Fluxo de calculo (por ponto, a cada ciclo)

1. `regions.find_region_for_point(lat, lon)` -> identifica regiao 1..4 (ou None)
2. `merge_inpe.fetch_real_batch(coords)` -> stream paralelo de 96 GRIB2 do INPE
   diretamente para memoria (sem disco), amostra TODOS os pontos por GRIB:
   - intensity_mmh (ultima hora)
   - ac24h_mm
   - ac96h_mm
3. `risk.calculate_cpc()` -> CPC = I / (K_regiao * Ac96h^-0.9)
4. `risk.classify_icc_geo()` -> ICC0..4 conforme cpc_breaks da regiao
5. `risk.classify_icc_hid()` -> ICC0..4 conforme hid24h_breaks
6. `risk.combine_ra_icc()` -> RD = matriz oficial RA x ICC
7. RD final = max(RD_geo, RD_hid)

## Streaming MERGE/INPE

Sem cache em disco. Cada ciclo:
- HTTP GET dos 96 GRIB2 horarios diretamente do servidor INPE
- Decodificacao em memoria (BytesIO + eccodes)
- Amostragem batch via codes_grib_find_nearest_multiple (1 chamada nativa para N pontos)
- ThreadPool com 8 workers em paralelo

Resultado: nada toca o filesystem da app, e o ciclo completo termina em segundos
mesmo para 24+ pontos de monitoramento.

## Estado de cada componente

| Componente | Estado | Notas |
|---|---|---|
| Equacoes ICC/CPC/RD | Implementadas | Tabelas oficiais REGEA 2021 |
| Polígonos das 4 regioes | Aproximacao retangular (gap R3/R4 fechado) | Substituir por shapefile oficial em `data/regioes_pli/` |
| Pontos de monitoramento | 24 amostras geradas | Refinar com KMs reais do DER |
| Risco Analisado (RA) | Default = 1 (RA=1 forcado) | `SAMAEG_USE_MANUAL_RA=1` reativa valores hard-coded |
| Chuva MERGE/INPE | **Streaming real (eccodes 2.x)** | Snapshot vai a `data_status=no_data` se a rede falhar — sem mock no caminho operacional |
| Validacao historica | Backtest 19/02/2023 (Sao Sebastiao) | Juquehy=RD4, Camburi=RD3, Maresias=RD1 |
| Auto-refresh | 10 min server / 30 s client | Configuravel |
| Testes unitarios | `tests/test_risk.py` (20 testes) | `python -m unittest discover tests` |
| Smoke test real | `python test_merge.py` | Baixa 96 GRIB de uma data conhecida e mostra acumulados |

## Endpoints

- `GET /` - interface
- `GET /api/snapshot` - estado atual completo (JSON)
- `GET /api/public/ua-layers` - UAs em GeoJSON (monitoramento tempo real; `?hazard=geo|hidro|all`, `?min_rd=3`)
- `POST /api/refresh` - forca atualizacao manual
- `GET /api/health` - health check

## Niveis Operacionais

| RD | Cor | Nivel |
|---|---|---|
| 0 | verde | Monitoramento |
| 1 | amarelo | Observacao |
| 2 | laranja | Atencao |
| 3 | vermelho | Alerta |
| 4 | roxo | Alerta Maximo |

## Deploy (Docker / Render)

### Imagem Docker (producao)

Requisitos: **Docker Desktop** em execucao.

```cmd
build-docker.bat
```

Ou manualmente:

```cmd
docker build -t pli-hazardtrack:prod -t pli-hazardtrack:latest .
docker run --rm -p 5050:5050 -e PORT=5050 pli-hazardtrack:prod
```

Health check: `GET /api/health`

A imagem inclui `libeccodes`, as 809 UAs (`data/ua_zones/`), malha DER
(`static/data/`) e roda com **gunicorn** na porta `$PORT` (padrao 5050).

### Render

- `render.yaml` configurado (`runtime: docker`, `dockerfilePath: ./Dockerfile`).
- Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`
- Health check: `/api/health`
