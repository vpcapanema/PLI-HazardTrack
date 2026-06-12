# Ferramentas auxiliares

Scripts, relatorios e artefatos de apoio **fora do backend operacional**
(`app.py`, `core/`, `static/`, `templates/`). Nenhum destes arquivos e
carregado em tempo de execucao da aplicacao.

Os **dados gerados** que o sistema consome permanecem em `data/` (por exemplo
`data/ua_polygons/ua_polygons.geojson`, `data/ua_zones/ua_geo.geojson`,
malha DER, regioes).

| Pasta | Conteudo |
|-------|----------|
| [geracao-uas/](geracao-uas/) | Pipeline das 809 UAs: poligonos, RA, validacao |
| [relatorios-plano-contingencia/](relatorios-plano-contingencia/) | PDFs, `ra_official.py`, documentacao metodologica |
| [preparacao-geodata/](preparacao-geodata/) | Scripts one-shot para malha DER, regioes, camadas admin |
| [exploracao-georef/](exploracao-georef/) | POCs de georreferenciamento, probes, testes MERGE |
| [integracao-pendente/](integracao-pendente/) | Modulos prontos fora do pipeline (ex.: DAEE) |
| [deploy-legado/](deploy-legado/) | Deploy VM desativado (historico) |

## Regenerar UAs (fluxo principal)

```cmd
python ferramentas/geracao-uas/build_ua_polygons.py
python ferramentas/geracao-uas/assign_ra_to_uas.py
```

Saida operacional: `data/ua_polygons/ua_polygons.geojson` (fonte) e
`data/ua_zones/ua_geo.geojson` + `ua_hidro.geojson` (runtime).
