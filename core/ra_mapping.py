"""
Mapeamento de Risco Analisado (RA) por ponto, derivado dos Produtos 3 e 4
 dos relatorios REGEA-NIPPON 2021 (Contrato 20.595-3).

Fonte: Tabelas 3.3.3.1-3 (geologico) e 3.3.3.1-4 (hidrologico) do Produto 7
 (Plano de Contingencia), que consolidam a Analise de Risco (Produto 4).

Politica:
- Quando o ponto estiver em trecho mapeado nos relatorios, usar RA moda
  (classe mais frequente) daquele trecho.
- Quando o ponto estiver fora dos trechos mapeados ou em rodovia sem dados,
  retornar ra=1 (neutro) com source="default".
- A longo prazo, substituir por shapefile oficial das UTBs/Setores de Risco
  (contratos DER 20.088-8 e 20.292-7, IG 2020).
"""

from typing import Optional, Tuple
import logging

log = logging.getLogger("ra_mapping")


# ---------------------------------------------------------------------------
# Trechos criticos mapeados no Produto 4 com distribuicao de RA
# Cada entrada: (rodovia, km_ini, km_fim, region_id, UBA, ra_geo, ra_hid, desc)
# ra_geo/ra_hid = moda (classe mais frequente) no trecho
# ---------------------------------------------------------------------------
_MAPPED_SEGMENTS = [
    # --- SP-055 / UBA 06.04-CGT / Regiao 2 (Caraguatatuba-Ubatuba) ---
    # km 53,6-102: RAGEO predominante = 1 (95 de 155 unidades)
    # Hidrologico: nao ha trechos criticos mapeados nesta faixa
    ("SP 055", 53.6, 102.0, 2, "UBA 06.04-CGT", 1, 1,
     "Caraguatatuba-Ubatuba: predominancia RAGEO1 (baixo)"),

    # --- SP-055 / UBA 06.04-CGT / Regiao 3 (Sao Sebastiao) ---
    # km 114-127,8: RAGEO predominante = 1 (27 de 64 unidades)
    ("SP 055", 114.0, 127.8, 3, "UBA 06.04-CGT", 1, 1,
     "Sao Sebastiao (norte): predominancia RAGEO1 (baixo)"),

    # --- SP-055 / UBA 05.04-SVC / Regiao 3 (Sao Sebastiao) ---
    # km 128-153: RAGEO predominante = 4 (41 de 135 unidades) - TRECHO CRITICO
    #             mas RAGEO1=32, RAGEO2=29, RAGEO3=29 => distribuicao
    #             heterogenea
    #             Moda = 4 (muito alto), mas media ponderada sugere 2-3
    #             Usamos 3 (alto) como representativo por seguranca
    ("SP 055", 128.0, 153.0, 3, "UBA 05.04-SVC", 3, 2,
     "Sao Sebastiao (km 128-153): trecho critico, predominancia RAGEO3-4"),
    # km 156-162: RAGEO predominante = 4 (17 de 48 unidades)
    ("SP 055", 156.0, 162.0, 3, "UBA 05.04-SVC", 4, 2,
     "Sao Sebastiao (km 156-162): predominancia RAGEO4 (muito alto)"),

    # --- SP-055 / UBA 05.04-SVC / Regiao 3 (hidrologico) ---
    # km 178,1-191,4: RAHID predominante = 1 (30 de 32)
    ("SP 055", 178.1, 191.4, 3, "UBA 05.04-SVC", 3, 1,
     "Sao Sebastiao (hidro): predominancia RAHID1 (baixo)"),

    # --- SP-055 / UBA 05.04-SVC / Regiao 4 (Santos-Bertioga) ---
    # km 191,4-223,6: RAHID0 predominante (75 de 75 no cenario) => RA hid = 0
    # Geologico: nao ha trecho critico mapeado nesta faixa especifica
    ("SP 055", 191.4, 223.6, 4, "UBA 05.04-SVC", 1, 0,
     "Santos-Bertioga: predominancia RAHID0, RAGEO baixo-moderado"),
    # km 235-238: RAGEO predominante = 4? RAGEO1=6, RAGEO2=1,
    #             RAGEO3=2, RAGEO4=2
    #             Moda = RAGEO1, mas com presenca significativa de RAGEO3-4
    ("SP 055", 235.0, 238.0, 4, "UBA 05.04-SVC", 1, 0,
     "Santos-Bertioga (km 235-238): RAGEO1 predominante "
     "com risco alto localizado"),

    # --- SP-098 / UBA 10.04-MCZ / Regiao 1 (Mogi-Bertioga) ---
    # km 77-98: RAGEO predominante = 1 (53 de 81 unidades)
    ("SP 098", 77.0, 98.0, 1, "UBA 10.04-MCZ", 1, 1,
     "Mogi-Bertioga: predominancia RAGEO1 (baixo)"),
]

# Rodovias secundarias que intersectam trechos mapeados podem herdar RA
# da regiao mais proxima, com um fator de atenuacao.
_SECONDARY_ROADS = {
    # Acessos a Ilhabela (SP 131) intersectam SP-055 proximo a Sao Sebastiao
    "SP 131": {"inherit_from_region": 3, "ra_geo": 2, "ra_hid": 1,
               "note": "Acesso Ilhabela, herda perfil "
               "da Regiao 3 (Sao Sebastiao)"},
    "SPA 004/131": {"inherit_from_region": 3, "ra_geo": 2, "ra_hid": 1,
                    "note": "Acesso Ilhabela, herda perfil da Regiao 3"},
    "SPA 000/131": {"inherit_from_region": 3, "ra_geo": 2, "ra_hid": 1,
                    "note": "Acesso Ilhabela, herda perfil da Regiao 3"},
    # SP 099 intersecta SP-055 em Caraguatatuba (Regiao 2)
    "SP 099": {"inherit_from_region": 2, "ra_geo": 1, "ra_hid": 1,
               "note": "Transversal Caraguatatuba, herda perfil da Regiao 2"},
    # SPA 165/055 e SPA 175/055 sao laterais de SP-055 em Sao Sebastiao
    "SPA 165/055": {"inherit_from_region": 3, "ra_geo": 3, "ra_hid": 2,
                    "note": "Lateral SP-055 Sao Sebastiao, "
                    "herda trecho critico"},
    "SPA 175/055": {"inherit_from_region": 3, "ra_geo": 3, "ra_hid": 2,
                    "note": "Lateral SP-055 Sao Sebastiao, "
                    "herda trecho critico"},
    "SPI 097/055": {"inherit_from_region": 3, "ra_geo": 2, "ra_hid": 1,
                    "note": "Lateral SP-055 Caraguatatuba, herda Regiao 3"},
    # SP 150, SP 148 sao acessos a Santos/Cubatao (Regiao 4)
    "SP 150": {"inherit_from_region": 4, "ra_geo": 1, "ra_hid": 0,
               "note": "Acesso Santos/Cubatao, herda perfil da Regiao 4"},
    "SP 148": {"inherit_from_region": 4, "ra_geo": 1, "ra_hid": 0,
               "note": "Acesso Santos/Cubatao, herda perfil da Regiao 4"},
    "SPA 248/055": {"inherit_from_region": 4, "ra_geo": 1, "ra_hid": 0,
                    "note": "Acesso Guaruja/Santos, herda perfil da Regiao 4"},
    "SP 061": {"inherit_from_region": 4, "ra_geo": 1, "ra_hid": 0,
               "note": "Acesso Guaruja, herda perfil da Regiao 4"},
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

    - ra_geo: Risco Analisado Geologico (0..4)
    - ra_hid: Risco Analisado Hidrologico (0..4)
    - source: descricao da origem do dado

    Quando nao ha dados especificos, retorna (1, 1, "default").
    """
    rodovia_norm = (rodovia or "").strip().upper()

    # 1) Match direto em trechos mapeados de SP-055 / SP-098
    if km is not None and rodovia_norm in ("SP 055", "SP 098"):
        for seg in _MAPPED_SEGMENTS:
            r_rod, r_km0, r_km1, r_reg, r_uba, r_geo, r_hid, r_desc = seg
            if rodovia_norm == r_rod and r_km0 <= km <= r_km1:
                src = f"regea2021:{r_rod}:{r_km0}-{r_km1}:{r_uba}"
                return (r_geo, r_hid, src)

    # 2) Match em rodovias secundarias com heranca de regiao
    if rodovia_norm in _SECONDARY_ROADS:
        info = _SECONDARY_ROADS[rodovia_norm]
        return (
            info["ra_geo"],
            info["ra_hid"],
            f"regea2021:inherit:r{info['inherit_from_region']}"
        )

    # 3) Fallback: se esta dentro de alguma regiao, usar RA moderado da regiao
    if region_id is not None:
        # Regioes 2 e 3 tem maior susceptibilidade -> RA=2 como cautela
        # Regioes 1 e 4 tem menor -> RA=1
        if region_id in (2, 3):
            return (2, 1, f"regea2021:region_fallback:r{region_id}")
        return (1, 1, f"regea2021:region_fallback:r{region_id}")

    # 4) Fora de cobertura: neutro
    return (1, 1, "default")


def get_ra_note(rodovia: Optional[str]) -> str:
    """Retorna nota explicativa do RA para uma rodovia."""
    rodovia_norm = (rodovia or "").strip().upper()
    if rodovia_norm in _SECONDARY_ROADS:
        return _SECONDARY_ROADS[rodovia_norm]["note"]
    return ""
