"""
Calculo de Risco Dinamico segundo metodologia DER-SP / REGEA-NIPPON 2021.

Fluxo:
    1. Determinar regiao do ponto (regions.py)
    2. Obter chuva: Ac96h (mm) e I (mm/h) a partir do MERGE/INPE (merge.py)
    3. Calcular CPC = I / (K_regiao * Ac96h^-0.9)  -> ICC geologico
    4. Calcular probabilidade hidrologica via tabela 24h -> ICC hidrologico
    5. Combinar com Risco Analisado (RA) -> Risco Dinamico (RD)
    6. Mapear RD -> Nivel Operacional
"""

from dataclasses import dataclass
from typing import Optional, Dict
from .regions import Region


@dataclass
class RiskResult:
    lat: float
    lon: float
    region_id: Optional[int]
    region_name: Optional[str]
    rodovia: Optional[str]
    ac96h_mm: float
    intensity_mmh: float
    ac24h_mm: float
    cpc: Optional[float]
    icc_geo: int        # 0..4
    icc_hid: int        # 0..4
    ra: Optional[int]   # 0..4 ou None (SEM_DADO)
    rd_geo: int         # 0..4 (pior caso do trecho)
    rd_hid: int         # 0..4 (pior caso do trecho)
    rd: int             # max(rd_geo, rd_hid)
    nivel: str          # "Monitoramento" .. "Alerta Maximo"
    # Distribuicao de Unidades de Analise por nivel de RD resultante
    # (None quando o ponto usa RA escalar e nao distribuicao).
    # Ex.: {4: 61, 3: 12, 2: 95} = 61 UAs em Alerta Maximo etc.
    rd_geo_dist: Optional[Dict[int, int]] = None
    rd_hid_dist: Optional[Dict[int, int]] = None
    # Quantas Unidades de Analise estao no nivel de RD de pior caso (rd).
    rd_unidades: Optional[int] = None


# Niveis operacionais (PPDC)
NIVEIS = {
    0: "Monitoramento",
    1: "Observação",
    2: "Atenção",
    3: "Alerta",
    4: "Alerta Máximo"
}

# Matriz RA x ICC -> RD (Tabela 3.2.1-1)
RD_MATRIX = [
    # ICC0 ICC1 ICC2 ICC3 ICC4
    [0, 0, 0, 0, 0],   # RA0
    [0, 1, 2, 3, 4],   # RA1
    [0, 2, 3, 4, 4],   # RA2
    [0, 3, 4, 4, 4],   # RA3
    [0, 4, 4, 4, 4],   # RA4
]


def compose_pdf_windows(
    ac72h_obs: float, ac18h_obs: float,
    ac96h_obs: float, ac24h_obs: float,
    prev24h_mm: Optional[float] = None,
    prev6h_mm: Optional[float] = None,
):
    """
    Composicao das janelas de chuva conforme o Produto 6 (secao 4.5.3):
      - Geologico:  Ac96h   = 72h observadas + 24h previstas
      - Hidrologico: Soma24h = 18h observadas + 6h previstas

    Quando a previsao WRF esta disponivel (prev24h_mm e prev6h_mm != None),
    retorna a composicao do PDF. Sem previsao, degrada de forma transparente
    para observado-apenas (96h e 24h observadas) - sem inventar dado.

    Returns: (ac96h, ac24h, fonte) onde fonte e "WRF" ou "OBS_ONLY".
    """
    if prev24h_mm is not None and prev6h_mm is not None:
        return (round(ac72h_obs + prev24h_mm, 2),
                round(ac18h_obs + prev6h_mm, 2),
                "WRF")
    return (ac96h_obs, ac24h_obs, "OBS_ONLY")


def calculate_cpc(
    intensity_mmh: float, ac96h_mm: float, k_geo: float
) -> Optional[float]:
    """
    CPC = I / I_envoltoria(Ac96h)
    onde I_envoltoria = K * Ac96h^(-0.9)

    Retorna None se Ac96h e intensidade insuficientes (sem chuva relevante).
    """
    if ac96h_mm <= 0.5 or intensity_mmh < 0:
        return 0.0
    envoltoria = k_geo * (ac96h_mm ** -0.9)
    if envoltoria <= 0:
        return None
    return intensity_mmh / envoltoria


def classify_icc_geo(cpc: Optional[float], breaks: list) -> int:
    """Mapeia CPC para faixa ICC_GEO (0..4) usando cpc_breaks da regiao."""
    if cpc is None or cpc < breaks[0]:
        return 0
    for i, b in enumerate(breaks):
        if cpc < b:
            return i
    return 4


def classify_icc_hid(ac24h_mm: float, breaks: list) -> int:
    """Mapeia chuva 24h para faixa ICC_HID (0..4)."""
    if ac24h_mm < breaks[0]:
        return 0
    for i, b in enumerate(breaks):
        if ac24h_mm < b:
            return i
    return 4


def combine_ra_icc(ra: int, icc: int) -> int:
    """Aplica matriz RA x ICC -> RD."""
    ra = max(0, min(4, ra))
    icc = max(0, min(4, icc))
    return RD_MATRIX[ra][icc]


def rd_distribution(
    ra_dist: Optional[Dict[int, int]], icc: int
) -> Dict[int, int]:
    """
    Dada a distribuicao de Unidades de Analise por classe de RA de um trecho
    e o ICC vigente, retorna a distribuicao de UAs por nivel de RD resultante.

    Reproduz exatamente as Tabelas 3.3.3.1-3/-4 do Produto 7: cada classe de
    RA com N unidades grada para RD = RD_MATRIX[RA][ICC], e as contagens sao
    somadas por nivel de RD.
    """
    out: Dict[int, int] = {}
    if not ra_dist:
        return out
    for ra_cls, n in ra_dist.items():
        if not n or n <= 0:
            continue
        rd = combine_ra_icc(int(ra_cls), icc)
        out[rd] = out.get(rd, 0) + int(n)
    return out


def _as_dist(
    dist: Optional[Dict[int, int]], scalar: Optional[int]
) -> Optional[Dict[int, int]]:
    """Distribuicao por trecho ou RA escalar da UA (1 unidade)."""
    if dist:
        return {int(k): int(v) for k, v in dist.items() if v and v > 0}
    if scalar is not None:
        return {int(scalar): 1}
    return None


def evaluate_point(lat: float, lon: float, region: Optional[Region],
                   ac96h: float, intensity: float, ac24h: float,
                   ra_geo: Optional[int] = None,
                   ra_hid: Optional[int] = None,
                   ra_geo_dist: Optional[Dict[int, int]] = None,
                   ra_hid_dist: Optional[Dict[int, int]] = None) -> RiskResult:
    """
    Calcula risco dinamico para um ponto (lat, lon).

    Args:
        region: regiao DER-SP ou None se fora da cobertura
        ac96h: chuva acumulada nas ultimas 96 horas (mm)
        intensity: chuva na ultima hora (mm/h)
        ac24h: chuva acumulada nas ultimas 24 horas (mm)
        ra_geo: RAGEO da UA (0..4) ou None (SEM_DADO no canal geo)
        ra_hid: RAHID da UA (0..4) ou None (SEM_DADO no canal hid)
        ra_geo_dist: distribuicao {classe: n_unidades} de RA GEO do trecho
            (Tabela 3.3.3.1-3). Quando presente, tem prioridade sobre ra_geo.
        ra_hid_dist: idem para RA HID (Tabela 3.3.3.1-4).

    Politica: RAGEO e RAHID sao independentes (Produto 7). Nao ha fallback
    entre canais nem campo RA generico. Sem dado em ambos -> SEM_DADO.

    Returns:
        RiskResult com todas as variaveis calculadas
    """
    dist_geo = _as_dist(ra_geo_dist, ra_geo)
    dist_hid = _as_dist(ra_hid_dist, ra_hid)

    if region is None:
        # Fora de cobertura: retorna estado neutro
        return RiskResult(
            lat=lat, lon=lon,
            region_id=None, region_name=None, rodovia=None,
            ac96h_mm=ac96h, intensity_mmh=intensity, ac24h_mm=ac24h,
            cpc=None, icc_geo=0, icc_hid=0,
            ra=None, rd_geo=0, rd_hid=0, rd=0,
            nivel="Fora de cobertura"
        )

    cpc = calculate_cpc(intensity, ac96h, region.k_geo)
    icc_geo = classify_icc_geo(cpc, region.cpc_breaks)
    icc_hid = classify_icc_hid(ac24h, region.hid24h_breaks)

    # Se nao houver RA oficial, nao calcula RD (retorna ICC mas RD=0 SEM_DADO)
    if dist_geo is None and dist_hid is None:
        return RiskResult(
            lat=lat, lon=lon,
            region_id=region.id, region_name=region.nome,
            rodovia=region.rodovia,
            ac96h_mm=round(ac96h, 1),
            intensity_mmh=round(intensity, 1),
            ac24h_mm=round(ac24h, 1),
            cpc=round(cpc, 2) if cpc is not None else None,
            icc_geo=icc_geo, icc_hid=icc_hid,
            ra=None, rd_geo=0, rd_hid=0, rd=0,
            nivel="SEM DADO - RA nao mapeado"
        )

    # Distribuicao de UAs por nivel de RD (reproduz Tabelas 3.3.3.1-3/-4)
    rd_geo_dist = rd_distribution(dist_geo, icc_geo)
    rd_hid_dist = rd_distribution(dist_hid, icc_hid)

    # RD do trecho = pior caso (maior nivel de RD com >=1 unidade)
    rd_geo = max(rd_geo_dist.keys()) if rd_geo_dist else 0
    rd_hid = max(rd_hid_dist.keys()) if rd_hid_dist else 0
    rd = max(rd_geo, rd_hid)

    # RA reportado: maior classe de RA presente no trecho (pior caso)
    ra_presente = []
    if dist_geo:
        ra_presente.append(max(dist_geo.keys()))
    if dist_hid:
        ra_presente.append(max(dist_hid.keys()))
    ra_max = max(ra_presente) if ra_presente else None

    # Quantas UAs estao no nivel de RD de pior caso
    unidades_pior = (
        rd_geo_dist.get(rd, 0) if rd_geo >= rd_hid else rd_hid_dist.get(rd, 0)
    )

    return RiskResult(
        lat=lat, lon=lon,
        region_id=region.id, region_name=region.nome, rodovia=region.rodovia,
        ac96h_mm=round(ac96h, 1),
        intensity_mmh=round(intensity, 1),
        ac24h_mm=round(ac24h, 1),
        cpc=round(cpc, 2) if cpc is not None else None,
        icc_geo=icc_geo, icc_hid=icc_hid,
        ra=ra_max, rd_geo=rd_geo, rd_hid=rd_hid, rd=rd,
        nivel=NIVEIS[rd],
        rd_geo_dist=rd_geo_dist or None,
        rd_hid_dist=rd_hid_dist or None,
        rd_unidades=unidades_pior or None,
    )
