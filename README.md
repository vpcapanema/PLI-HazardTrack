# SAMAEG-PLI v0.1

Sistema Automatizado de Monitoramento, Analise e Alerta Geodinamico
para a malha rodoviaria do PLI / Resiliencia Climatica - DER-SP.

Implementa o conceito do Produto 06 do Relatorio REGEA-NIPPON 2021,
com dados reais de chuva (MERGE/CPTEC/INPE) e o modelo oficial de
Risco Dinamico (RD = RA x ICC) das 4 regioes climaticas-geologico-
geomorfologicas do litoral norte e baixada santista de SP.

## Como rodar

```cmd
cd samaeg_pli
pip install -r requirements.txt
python app.py
```

Abre em http://localhost:5050

## Arquitetura

```
samaeg_pli/
  app.py                       Flask + scheduler (refresh a cada 10 min)
  core/
    regions.py                 4 regioes DER-SP + classificacao por geofence
    monitoring_points.py       Pontos amostrais ao longo de SP-055 e SP-098
    merge_inpe.py              Ingestao de chuva MERGE/CPTEC/INPE (GRIB2)
    risk.py                    Calculo CPC, ICC, RD conforme metodologia DER-SP
    aggregator.py              Orquestrador thread-safe do estado global
  templates/
    index.html                 Interface
  static/
    style.css                  Design PLI (verde + azul + escala de risco)
    app.js                     Auto-refresh 30s, mapa Leaflet, KPIs
  cache/                       GRIB2 baixados do INPE (cache local)
```

## Fluxo de calculo (por ponto, a cada ciclo)

1. `regions.find_region_for_point(lat, lon)` -> identifica regiao 1..4 (ou None)
2. `merge_inpe.fetch(lat, lon)` -> baixa GRIB2 das ultimas 96h e amostra:
   - intensity_mmh (ultima hora)
   - ac24h_mm
   - ac96h_mm
3. `risk.calculate_cpc()` -> CPC = I / (K_regiao * Ac96h^-0.9)
4. `risk.classify_icc_geo()` -> ICC0..4 conforme cpc_breaks da regiao
5. `risk.classify_icc_hid()` -> ICC0..4 conforme hid24h_breaks
6. `risk.combine_ra_icc()` -> RD = matriz oficial RA x ICC
7. RD final = max(RD_geo, RD_hid)

## Estado de cada componente

| Componente | Estado | Notas |
|---|---|---|
| Equacoes ICC/CPC/RD | Implementadas | Tabelas oficiais REGEA 2021 |
| Polígonos das 4 regioes | Aproximacao retangular | Substituir por shapefile oficial em data/regioes_pli/ |
| Pontos de monitoramento | 24 amostras geradas | Refinar com KMs reais do DER |
| Risco Analisado (RA) | Default = 1 ate 4 (manual) | Substituir por shapefile RA do IG-SP |
| Chuva MERGE/INPE | Funcional (cfgrib opcional) | Fallback para mock se cfgrib indisponivel |
| Auto-refresh | 10 min server / 30 s client | Configuravel |

## Dependencias criticas

- `cfgrib` + `eccodes`: leitura GRIB2 do INPE.  
  Em Windows, eccodes pode exigir Visual C++ Redistributable.
  Se falhar a instalacao, o sistema cai automaticamente em modo MOCK
  (chuva sintetica deterministica) para que o resto funcione.

## Endpoints

- `GET /` - interface
- `GET /api/snapshot` - estado atual completo (JSON)
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
