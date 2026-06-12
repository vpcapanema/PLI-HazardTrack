# Geracao das 809 Unidades de Analise (UAs)

Scripts para construir os poligonos individuais das UAs e atribuir
Risco Analisado (RA) GEO/HID a partir do Relatorio 2053-R04-21
(Produto 7 — Plano de Contingencia).

## Onde entra no sistema

| Artefato gerado | Caminho | Consumido por |
|-----------------|---------|---------------|
| Poligonos UA (809) | `data/ua_polygons/ua_polygons.geojson` | etapa intermediaria |
| Malha operacional | `data/ua_zones/ua_zones.geojson` | `core/zones.py` → `core/aggregator.py` → mapa |

## Scripts (ordem de uso)

### 1. `build_ua_polygons.py` (atual, canonico)

Gera **809 poligonos** sem mesclar trechos adjacentes.

- **Eixo:** `data/der_sistema_rodoviario/MALHA_RODOVIARIA.shp`
- **Buffer:** 500 m/lado (faixa 1 km, secao 2 do Produto 7)
- **Cortes municipais:** Tabela 2-1 (km exatos)
- **Cortes de escala:** Figuras 3.3-2..5 (cor na rodovia)
- **Contagem:** Tabela 3.3-1 (111+188+355+155 = 809)
- **Divisas internas:** interpoladas onde a figura nao as desenha (~91%)

```cmd
python ferramentas/geracao-uas/build_ua_polygons.py
```

### 2. `assign_ra_to_uas.py`

Atribui `ra_geo`, `ra_hid` e `ra` a cada poligono.

1. Amostragem nas figuras 3.3.3-x (cor → classe RA0..RA4)
2. Regularizacao Tobler (lacunas e ruido; transicoes reais preservadas)
3. Alocacao por ranking com orcamento das Tabelas 3.3.1-2 / 3.3.2-2
4. Validacao diagnostica vs trechos criticos em `core/ra_official.py`

```cmd
python ferramentas/geracao-uas/assign_ra_to_uas.py
```

### Auxiliares

| Arquivo | Funcao |
|---------|--------|
| `ua_figure_utils.py` | Georef UTM, classificacao de cor RA, leitura de mapas do PDF |
| `ua_ra_budgets.py` | Orcamentos oficiais por (regiao, escala) |
| `validate_ua_zones.py` | Compara distribuicao gerada vs tabelas 3.3.3.1-3/-4 |
| `build_ua_segments.py` | Segmentos DER com RA por trecho critico (alternativa pre-UAs) |
| `ua_segments_loader.py` | Leitor espacial do GeoJSON de segmentos (legacy) |
| `_diag_polys.py` | Sobrepoe poligonos nas figuras 3.3-x para inspecao visual |

### Depreciados (nao usar em producao)

| Arquivo | Motivo |
|---------|--------|
| `digitize_ua_figures.py` | Mesclava trechos com mesmo RA |
| `digitize_ua_polygons.py` | Segmentacao por imagem; contagem incorreta |

## Figuras de diagnostico

Pasta `figuras-diagnostico/`: PNGs gerados por `_diag_polys.py`,
`_render_figs.py` (em `exploracao-georef/`) e iteracoes de overlay.
Servem apenas para validacao visual — nao entram no pipeline.

## PDF de entrada

`find_pdf()` em `ua_figure_utils.py` localiza automaticamente:

`data/Tema30_Resiliencia/Relatorio_Plano_Contingencia BIRD_2021/4 PRODUTO 7 Plano de Contingência.pdf`

Copias em `ferramentas/relatorios-plano-contingencia/pdfs-originais/`.
