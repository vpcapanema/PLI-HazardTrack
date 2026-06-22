"""
Tabelas oficiais do Relatorio 2053-R04-21 - PRODUTO 7 - Plano de
Contingencia (DER-SP / Consorcio 4X044, 2021), transcritas LITERALMENTE
do PDF "4 PRODUTO 7 Plano de Contingencia.pdf".

Estas estruturas sao a fonte de verdade para reconstruir as Unidades de
Analise (UAs) e atribuir os Riscos Analisados (RAGEO/RAHID), substituindo
qualquer inferencia por extracao visual.

REFERENCIAS NO PDF:
  Tabela 2-1 (p.5)    : extensoes cadastrais oficiais por UBA/rodovia
  Tabela 3.3-1 (p.36) : 809 UAs por (Regiao x Municipio x Escala)
  Tabela 3.3.1-2 (p.45): RAGEO global por (Regiao x Escala x Classe)
  Tabela 3.3.2-2 (p.47): RAHID global por (Regiao x Escala x Classe)
  Tabela 3.3.3.1-1 (p.71): trechos criticos GEO (km cadastrais)
  Tabela 3.3.3.1-2 (p.71): trechos criticos HID (km cadastrais)
  Tabela 3.3.3.1-3 (p.74): contagem RA por trecho critico GEO
  Tabela 3.3.3.1-4 (p.75): contagem RA por trecho critico HID

ESCALAS:
  1:25.000 -> UTB - cobertura regular, ~550 m/UA
  1:10.000 -> UTB - cobertura regular, ~270 m/UA
  1:1.000  -> SR  - Setor de Risco SOBREPOSTO nos trechos criticos
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# TAB 3.3-1 : 809 UAs por (Regiao x Municipio x Escala)
# Estrutura: {(regiao_id, municipio): {escala: (qtd, extensao_km_pdf)}}
# ---------------------------------------------------------------------------
TAB_3_3_1 = {
    (1, "Mogi das Cruzes"): {"25K": (41, 14.28), "10K": (0, 0.0),
                             "1K":  (0,  0.0)},
    (1, "Biritiba Mirim"):  {"25K": (22,  8.51), "10K": (0, 0.0),
                             "1K":  (5,  0.66)},
    (1, "Bertioga"):        {"25K": (0,   0.0),  "10K": (11, 5.68),
                             "1K":  (32, 5.54)},
    (2, "Caraguatatuba"):   {"25K": (0,   0.0),  "10K": (68, 22.32),
                             "1K":  (30, 7.19)},
    (2, "Ubatuba"):         {"25K": (0,   0.0),  "10K": (30, 16.40),
                             "1K":  (60, 12.85)},
    (3, "São Sebastião"):   {"25K": (0,   0.0),  "10K": (103, 34.60),
                             "1K":  (252, 43.56)},
    (4, "Bertioga"):        {"25K": (0,   0.0),  "10K": (87, 36.59),
                             "1K":  (16, 5.92)},
    (4, "Santos"):          {"25K": (0,   0.0),  "10K": (36, 11.56),
                             "1K":  (16, 3.21)},
}

# ---------------------------------------------------------------------------
# TAB 3.3.1-2 : RAGEO global por (Regiao x Escala x Classe)
# Estrutura: {(regiao_id, escala): {RA: qtd}}
# ---------------------------------------------------------------------------
TAB_3_3_1_2_RAGEO = {
    # Subtotal escala 1:25.000 (so R1) = 63 UAs
    (1, "25K"): {0: 19, 1: 11, 2: 10, 3:  4, 4: 19},   # 63
    # Subtotal escala 1:10.000 = 335 UAs (R1=11, R2=98, R3=103, R4=123)
    (1, "10K"): {0:  0, 1: 11, 2:  0, 3:  0, 4:  0},   # 11
    (2, "10K"): {0:  0, 1: 97, 2:  1, 3:  0, 4:  0},   # 98
    (3, "10K"): {0:  0, 1: 103, 2:  0, 3:  0, 4:  0},  # 103
    (4, "10K"): {0:  0, 1: 123, 2:  0, 3:  0, 4:  0},  # 123
    # Subtotal escala 1:1.000 = 411 UAs (R1=37, R2=90, R3=252, R4=32)
    (1, "1K"):  {0:  0, 1:  0, 2: 16, 3: 14, 4:  7},   # 37
    (2, "1K"):  {0:  8, 1: 10, 2: 11, 3: 28, 4: 33},   # 90
    (3, "1K"):  {0:  7, 1: 33, 2: 63, 3: 69, 4: 80},   # 252
    (4, "1K"):  {0:  5, 1:  8, 2:  5, 3: 12, 4:  2},   # 32
}

# ---------------------------------------------------------------------------
# TAB 3.3.2-2 : RAHID global por (Regiao x Escala x Classe)
# ---------------------------------------------------------------------------
TAB_3_3_2_2_RAHID = {
    # 1:25.000 (so R1) = 63 UAs
    (1, "25K"): {0: 44, 1: 19, 2:  0, 3:  0, 4:  0},   # 63
    # 1:10.000 = 335 UAs
    (1, "10K"): {0:  0, 1: 11, 2:  0, 3:  0, 4:  0},   # 11
    (2, "10K"): {0:  0, 1: 89, 2:  9, 3:  0, 4:  0},   # 98
    (3, "10K"): {0:  0, 1: 99, 2:  4, 3:  0, 4:  0},   # 103
    (4, "10K"): {0:  0, 1: 117, 2:  6, 3:  0, 4:  0},  # 123
    # 1:1.000 = 411 UAs
    (1, "1K"):  {0: 37, 1:  0, 2:  0, 3:  0, 4:  0},   # 37
    (2, "1K"):  {0: 84, 1:  0, 2:  0, 3:  6, 4:  0},   # 90
    (3, "1K"):  {0: 248, 1:  0, 2:  0, 3:  4, 4:  0},  # 252
    (4, "1K"):  {0: 28, 1:  0, 2:  0, 3:  4, 4:  0},   # 32
}

# ---------------------------------------------------------------------------
# TAB 3.3.3.1-1 : Trechos criticos GEO (km cadastrais oficiais)
# Lista de dicts com regiao_id, uba_codigo, km_ini, km_fim, extensao_km
# Estes sao os trechos onde se CONCENTRAM as classes RA2/RA3/RA4 dos SRs.
# ---------------------------------------------------------------------------
TRECHOS_CRITICOS_GEO = [
    {"regiao_id": 3, "uba_codigo": "05.04", "km_ini": 128.000,
     "km_fim": 153.000, "extensao_km": 25.000, "rodovia": "SP-055"},
    {"regiao_id": 3, "uba_codigo": "05.04", "km_ini": 156.000,
     "km_fim": 162.000, "extensao_km":  6.000, "rodovia": "SP-055"},
    {"regiao_id": 4, "uba_codigo": "05.04", "km_ini": 235.000,
     "km_fim": 238.000, "extensao_km":  3.000, "rodovia": "SP-055"},
    {"regiao_id": 2, "uba_codigo": "06.04", "km_ini":  53.600,
     "km_fim": 102.000, "extensao_km": 48.400, "rodovia": "SP-055"},
    {"regiao_id": 3, "uba_codigo": "06.04", "km_ini": 114.000,
     "km_fim": 127.800, "extensao_km": 13.800, "rodovia": "SP-055"},
    {"regiao_id": 1, "uba_codigo": "10.04", "km_ini":  77.000,
     "km_fim":  98.000, "extensao_km": 21.000, "rodovia": "SP-098"},
]

# ---------------------------------------------------------------------------
# TAB 3.3.3.1-2 : Trechos criticos HID
# ---------------------------------------------------------------------------
TRECHOS_CRITICOS_HID = [
    {"regiao_id": 3, "uba_codigo": "05.04", "km_ini": 178.100,
     "km_fim": 191.400, "extensao_km": 13.300, "rodovia": "SP-055"},
    {"regiao_id": 4, "uba_codigo": "05.04", "km_ini": 191.400,
     "km_fim": 223.600, "extensao_km": 32.200, "rodovia": "SP-055"},
    # Pontos discretos (~1 km cada): centrados nos km indicados
    {"regiao_id": 2, "uba_codigo": "06.04", "km_ini":  92.500,
     "km_fim":  93.500, "extensao_km":  1.000, "rodovia": "SP-055"},
    {"regiao_id": 2, "uba_codigo": "06.04", "km_ini":  96.500,
     "km_fim":  97.500, "extensao_km":  1.000, "rodovia": "SP-055"},
    {"regiao_id": 2, "uba_codigo": "06.04", "km_ini": 111.500,
     "km_fim": 112.500, "extensao_km":  1.000, "rodovia": "SP-055"},
    # R1 nao tem trecho critico hidrologico (PDF p.71)
]

# ---------------------------------------------------------------------------
# TAB 3.3.3.1-3 : Contagem RAGEO por trecho critico
# Chave: (regiao_id, km_ini, km_fim) -> {RA: qtd}
# Esta tabela e usada apenas como REFERENCIA/VALIDACAO; a fonte primaria
# de quantidade por classe e a TAB_3_3_1_2_RAGEO.
# ---------------------------------------------------------------------------
TAB_3_3_3_1_3 = {
    (3, 128.0, 153.0): {0:  4, 1: 32, 2: 29, 3: 29, 4: 41},  # 135
    (3, 156.0, 162.0): {0:  1, 1:  7, 2:  9, 3: 14, 4: 17},  # 48
    (4, 235.0, 238.0): {0:  0, 1:  6, 2:  1, 3:  2, 4:  2},  # 11
    (2,  53.6, 102.0): {0:  7, 1: 95, 2: 12, 3: 28, 4: 33},  # 175
    (3, 114.0, 127.8): {0:  0, 1: 27, 2:  7, 3: 14, 4: 16},  # 64
    (1,  77.0,  98.0): {0:  1, 1: 53, 2:  5, 3:  6, 4: 16},  # 81
}

# ---------------------------------------------------------------------------
# TAB 3.3.3.1-4 : Contagem RAHID por trecho critico
# ---------------------------------------------------------------------------
TAB_3_3_3_1_4 = {
    (3, 178.1, 191.4): {0:  2, 1: 30, 2:  0, 3:  0, 4:  0},  # 32
    (4, 191.4, 223.6): {0:  4, 1: 67, 2:  1, 3:  3, 4:  0},  # 75
    (2,  92.5,  93.5): {0:  7, 1:  0, 2:  0, 3:  0, 4:  0},  # 7
    (2,  96.5,  97.5): {0:  0, 1:  3, 2:  0, 3:  0, 4:  0},  # 3
    (2, 111.5, 112.5): {0:  3, 1:  5, 2:  0, 3:  0, 4:  0},  # 8
}

# ---------------------------------------------------------------------------
# TAB 3.2.2-2 e 3.2.3-1 (p.34): limites ICC por regiao
#   GEO: CPC (Coeficiente de Precipitacao Critica), adimensional
#   HID: chuva acumulada em 24h (mm)
# ---------------------------------------------------------------------------
ICC_GEO_LIMITES = {
    # regiao_id -> [limites entre as faixas 0->1, 1->2, 2->3, 3->4]
    1: [1.0,  3.0,  6.0, 15.0],   # SP-098 Mogi-Bertioga
    2: [1.0,  6.0, 12.0, 24.0],   # SP-055 Caraguatatuba-Ubatuba
    3: [1.0,  8.0, 16.0, 24.0],   # SP-055 Sao Sebastiao
    4: [1.0,  4.0,  8.0, 16.0],   # SP-055 Santos-Bertioga
}
ICC_HID_LIMITES = {
    # regiao_id -> [limites em mm/24h]
    1: [110.0, 160.0, 200.0, 280.0],
    2: [70.0,  80.0, 120.0, 143.0],
    3: [60.0,  85.0, 110.0, 126.0],
    4: [150.0, 200.0, 230.0, 300.0],
}


def _validar_consistencia():
    """Verifica consistencia interna das tabelas."""
    # Soma TAB_3_3_1 por escala = totais esperados
    totais = {"25K": 0, "10K": 0, "1K": 0}
    for por_esc in TAB_3_3_1.values():
        for esc, (qtd, _) in por_esc.items():
            totais[esc] += qtd
    assert totais["25K"] == 63, totais
    assert totais["10K"] == 335, totais
    assert totais["1K"] == 411, totais
    assert sum(totais.values()) == 809

    # TAB_3_3_1_2_RAGEO subtotais devem bater com totais por escala
    for esc, esperado in [("25K", 63), ("10K", 335), ("1K", 411)]:
        soma = sum(
            qtd for (rid, e), classes in TAB_3_3_1_2_RAGEO.items()
            if e == esc
            for qtd in classes.values()
        )
        assert soma == esperado, (esc, soma, esperado)

    # TAB_3_3_2_2_RAHID idem
    for esc, esperado in [("25K", 63), ("10K", 335), ("1K", 411)]:
        soma = sum(
            qtd for (rid, e), classes in TAB_3_3_2_2_RAHID.items()
            if e == esc
            for qtd in classes.values()
        )
        assert soma == esperado, (esc, soma, esperado)

    print("[OK] Consistencia das tabelas oficiais validada.")
    print("     63 UTBs 1:25K + 335 UTBs 1:10K + 411 SRs 1:1K = 809")
    print(f"     {len(TRECHOS_CRITICOS_GEO)} trechos criticos GEO")
    print(f"     {len(TRECHOS_CRITICOS_HID)} trechos criticos HID")


if __name__ == "__main__":
    _validar_consistencia()
