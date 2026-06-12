# Exploracao e diagnostico (georreferenciamento)

Scripts ad-hoc de prova de conceito, calibracao de georef e inspecao
de dados. Criados durante o desenvolvimento das UAs e da integracao
MERGE/INPE. **Nao entram no pipeline operacional.**

## Scripts

| Arquivo | Proposito |
|---------|-----------|
| `_render_figs.py` | Renderiza paginas do PDF Produto 7 em PNG → `../geracao-uas/figuras-diagnostico/` |
| `_probe_geo.py`, `_probe_vectors.py` | Sondagem de coordenadas e vetores nas figuras |
| `_crop_zoom.py`, `_detect_ticks.py`, `_extract_map.py` | Calibracao de grid UTM e recorte de mapas |
| `_poc_sample.py`, `_poc_setup.py` | POC inicial de amostragem RA (Regiao 3) |
| `inspect_merge_grib_field.py` | Inspeciona campos GRIB2 do MERGE/INPE |
| `test_merge.py` | Teste manual de ingestao MERGE |
| `_fix_lint.py`, `_fix_msg.py`, `_remove_mock.py` | Utilitarios pontuais de manutencao de codigo |

## Como usar

Executar a partir da raiz do repo:

```cmd
python ferramentas/exploracao-georef/_render_figs.py 56 58
python ferramentas/exploracao-georef/inspect_merge_grib_field.py
```

Muitos scripts usam caminhos relativos ao repositorio (`parents[2]`) ou
glob recursivo a partir do diretorio de trabalho atual.

## Artefatos relacionados

PNGs e overlays de validacao ficam em
`ferramentas/geracao-uas/figuras-diagnostico/`.
