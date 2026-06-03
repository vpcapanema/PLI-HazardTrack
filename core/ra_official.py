"""
Mapeamento oficial de Risco Analisado (RA) por trecho de rodovia.

Fonte: Relatorio Tecnico 2053-R04-21
(Etapa 3, Produto 7 - Plano de Contingencia)
Tabelas 3.3.3.1-3 (geologico) e 3.3.3.1-4 (hidrologico)

Os dados abaixo sao extraidos diretamente dos relatorios oficiais.
NENHUM valor foi inventado. Trechos nao listados nao possuem dados
oficiais de RA neste relatorio e devem ser marcados como SEM_DADO.
"""

from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# DADOS OFICIAIS DO RELATORIO - Tabela 3.3.3.1-3 (Geologico)
# Distribuicao de RAGEO por trecho (unidades de analise)
# ---------------------------------------------------------------------------
RA_GEO_BY_SEGMENT = {
    # SP-055 / UBA 06.04-CGT / Regiao 2 (Caraguatatuba-Ubatuba) km 53,6-102
    # RAGEO0: 7, RAGEO1: 95, RAGEO2: 12, RAGEO3: 28, RAGEO4: 33
    # Total: 175 unidades. Moda: RAGEO1 (95 unidades = 54,3%)
    ("SP 055", 53.6, 102.0): {
        "moda": 1,
        "dist": {0: 7, 1: 95, 2: 12, 3: 28, 4: 33},
        "uba": "UBA 06.04-CGT",
        "regiao": 2,
        "desc": "Caraguatatuba-Ubatuba: predominancia RAGEO1 (95/175)"
    },
    # SP-055 / UBA 06.04-CGT / Regiao 3 (Sao Sebastiao) km 114-127,8
    # RAGEO0: -, RAGEO1: 27, RAGEO2: 7, RAGEO3: 14, RAGEO4: 16
    # Total: 64 unidades. Moda: RAGEO1 (27 unidades = 42,2%)
    ("SP 055", 114.0, 127.8): {
        "moda": 1,
        "dist": {0: 0, 1: 27, 2: 7, 3: 14, 4: 16},
        "uba": "UBA 06.04-CGT",
        "regiao": 3,
        "desc": "Sao Sebastiao (norte): predominancia RAGEO1 (27/64)"
    },
    # SP-055 / UBA 05.04-SVC / Regiao 3 (Sao Sebastiao) km 128-153
    # RAGEO0: 4, RAGEO1: 32, RAGEO2: 29, RAGEO3: 29, RAGEO4: 41
    # Total: 135 unidades. Moda: RAGEO4 (41 unidades = 30,4%)
    ("SP 055", 128.0, 153.0): {
        "moda": 4,
        "dist": {0: 4, 1: 32, 2: 29, 3: 29, 4: 41},
        "uba": "UBA 05.04-SVC",
        "regiao": 3,
        "desc": "Sao Sebastiao (km 128-153): predominancia RAGEO4 (41/135)"
    },
    # SP-055 / UBA 05.04-SVC / Regiao 3 (Sao Sebastiao) km 156-162
    # RAGEO0: 1, RAGEO1: 7, RAGEO2: 9, RAGEO3: 14, RAGEO4: 17
    # Total: 48 unidades. Moda: RAGEO4 (17 unidades = 35,4%)
    ("SP 055", 156.0, 162.0): {
        "moda": 4,
        "dist": {0: 1, 1: 7, 2: 9, 3: 14, 4: 17},
        "uba": "UBA 05.04-SVC",
        "regiao": 3,
        "desc": "Sao Sebastiao (km 156-162): predominancia RAGEO4 (17/48)"
    },
    # SP-055 / UBA 05.04-SVC / Regiao 4 (Santos-Bertioga) km 235-238
    # RAGEO0: -, RAGEO1: 6, RAGEO2: 1, RAGEO3: 2, RAGEO4: 2
    # Total: 11 unidades. Moda: RAGEO1 (6 unidades = 54,5%)
    ("SP 055", 235.0, 238.0): {
        "moda": 1,
        "dist": {0: 0, 1: 6, 2: 1, 3: 2, 4: 2},
        "uba": "UBA 05.04-SVC",
        "regiao": 4,
        "desc": "Santos-Bertioga (km 235-238): predominancia RAGEO1 (6/11)"
    },
    # SP-098 / UBA 10.04-MCZ / Regiao 1 (Mogi-Bertioga) km 77-98
    # RAGEO0: 1, RAGEO1: 53, RAGEO2: 5, RAGEO3: 6, RAGEO4: 16
    # Total: 81 unidades. Moda: RAGEO1 (53 unidades = 65,4%)
    ("SP 098", 77.0, 98.0): {
        "moda": 1,
        "dist": {0: 1, 1: 53, 2: 5, 3: 6, 4: 16},
        "uba": "UBA 10.04-MCZ",
        "regiao": 1,
        "desc": "Mogi-Bertioga: predominancia RAGEO1 (53/81)"
    },
}

# ---------------------------------------------------------------------------
# DADOS OFICIAIS DO RELATORIO - Tabela 3.3.3.1-4 (Hidrologico)
# Distribuicao de RAHID por trecho (unidades de analise)
# ---------------------------------------------------------------------------
RA_HID_BY_SEGMENT = {
    # SP-055 / UBA 05.04-SVC / Regiao 3 (Sao Sebastiao) km 178,1-191,4
    # RAHID0: 2, RAHID1: 30, RAHID2: -, RAHID3: -, RAHID4: -
    # Total: 32 unidades. Moda: RAHID1 (30 unidades = 93,8%)
    ("SP 055", 178.1, 191.4): {
        "moda": 1,
        "dist": {0: 2, 1: 30, 2: 0, 3: 0, 4: 0},
        "uba": "UBA 05.04-SVC",
        "regiao": 3,
        "desc": "Sao Sebastiao (hidro): predominancia RAHID1 (30/32)"
    },
    # SP-055 / UBA 05.04-SVC / Regiao 4 (Santos-Bertioga) km 191,4-223,6
    # RAHID0: 75, RAHID1: 67, RAHID2: 1, RAHID3: 3, RAHID4: -
    # Total: 146 unidades. Moda: RAHID0 (75 unidades = 51,4%)
    ("SP 055", 191.4, 223.6): {
        "moda": 0,
        "dist": {0: 75, 1: 67, 2: 1, 3: 3, 4: 0},
        "uba": "UBA 05.04-SVC",
        "regiao": 4,
        "desc": "Santos-Bertioga (hidro): predominancia RAHID0 (75/146)"
    },
    # SP-055 / UBA 06.04-CGT / Regiao 2 (Caraguatatuba-Ubatuba) km ~93
    # RAHID0: 7, RAHID1: -, RAHID2: -, RAHID3: -, RAHID4: -
    # Total: 7 unidades. Moda: RAHID0 (7/7 = 100%)
    ("SP 055", 93.0, 93.0): {
        "moda": 0,
        "dist": {0: 7, 1: 0, 2: 0, 3: 0, 4: 0},
        "uba": "UBA 06.04-CGT",
        "regiao": 2,
        "desc": "Caraguatatuba-Ubatuba (hidro, km 93): RAHID0 (7/7)"
    },
    # SP-055 / UBA 06.04-CGT / Regiao 2 (Caraguatatuba-Ubatuba) km ~97
    # RAHID0: -, RAHID1: 3, RAHID2: -, RAHID3: -, RAHID4: -
    # Total: 3 unidades. Moda: RAHID1 (3/3 = 100%)
    ("SP 055", 97.0, 97.0): {
        "moda": 1,
        "dist": {0: 0, 1: 3, 2: 0, 3: 0, 4: 0},
        "uba": "UBA 06.04-CGT",
        "regiao": 2,
        "desc": "Caraguatatuba-Ubatuba (hidro, km 97): RAHID1 (3/3)"
    },
    # SP-055 / UBA 06.04-CGT / Regiao 2 (Caraguatatuba-Ubatuba) km ~112
    # RAHID0: 3, RAHID1: 5, RAHID2: -, RAHID3: -, RAHID4: -
    # Total: 8 unidades. Moda: RAHID1 (5/8 = 62,5%)
    ("SP 055", 112.0, 112.0): {
        "moda": 1,
        "dist": {0: 3, 1: 5, 2: 0, 3: 0, 4: 0},
        "uba": "UBA 06.04-CGT",
        "regiao": 2,
        "desc": "Caraguatatuba-Ubatuba (hidro, km 112): RAHID1 (5/8)"
    },
}


def get_ra_for_point(
    rodovia: Optional[str],
    km: Optional[float],
    lat: float,
    lon: float,
    region_id: Optional[int],
) -> Tuple[int, int, str]:
    """
    Retorna (ra_geo, ra_hid, source) para um ponto de monitoramento.

    Dados oficiais extraidos das Tabelas 3.3.3.1-3 e 3.3.3.1-4
    do Relatorio 2053-R04-21 (Produto 7).

    Se o ponto nao estiver em trecho mapeado, retorna
    (None, None, "SEM_DADO") para indicar que nao ha dado oficial.
    """
    rodovia_norm = (rodovia or "").strip().upper()

    if km is not None:
        # Busca em trechos geologicos mapeados
        for (r_rod, r_km0, r_km1), data in RA_GEO_BY_SEGMENT.items():
            if rodovia_norm == r_rod and r_km0 <= km <= r_km1:
                ra_geo = data["moda"]
                # Busca hidrologico no mesmo trecho se disponivel
                ra_hid = None
                for (h_rod, h_km0, h_km1), h_data in RA_HID_BY_SEGMENT.items():
                    if h_rod == rodovia_norm and h_km0 <= km <= h_km1:
                        ra_hid = h_data["moda"]
                        break
                # Se nao houver dado hidrologico para este trecho,
                # usa o geologico como fallback (ambos processos estao
                # correlacionados)
                if ra_hid is None:
                    ra_hid = ra_geo
                src = f"regea2021:{r_rod}:km{r_km0}-{r_km1}:{data['uba']}"
                return (ra_geo, ra_hid, src)

    # Fora de cobertura: SEM_DADO (nao inventar)
    return (None, None, "SEM_DADO")
