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
from typing import Optional
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
    ra: int             # 0..4 (Risco Analisado, default 1 ate haver shapefile)
    rd_geo: int         # 0..4
    rd_hid: int         # 0..4
    rd: int             # max(rd_geo, rd_hid)
    nivel: str          # "Monitoramento" .. "Alerta Maximo"


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


def calculate_cpc(intensity_mmh: float, ac96h_mm: float, k_geo: float) -> Optional[float]:
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


def classify_icc_geo(cpc: float, breaks: list) -> int:
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


def evaluate_point(lat: float, lon: float, region: Optional[Region],
                   ac96h: float, intensity: float, ac24h: float,
                   ra: int = 1) -> RiskResult:
    """
    Calcula risco dinamico para um ponto (lat, lon).

    Args:
        region: regiao DER-SP ou None se fora da cobertura
        ac96h: chuva acumulada nas ultimas 96 horas (mm)
        intensity: chuva na ultima hora (mm/h)
        ac24h: chuva acumulada nas ultimas 24 horas (mm)
        ra: Risco Analisado (1..4). Default = 1 (baixo) ate ter shapefile RA real.

    Returns:
        RiskResult com todas as variaveis calculadas
    """
    if region is None:
        # Fora de cobertura: retorna estado neutro
        return RiskResult(
            lat=lat, lon=lon,
            region_id=None, region_name=None, rodovia=None,
            ac96h_mm=ac96h, intensity_mmh=intensity, ac24h_mm=ac24h,
            cpc=None, icc_geo=0, icc_hid=0,
            ra=ra, rd_geo=0, rd_hid=0, rd=0,
            nivel=NIVEIS[0]
        )

    cpc = calculate_cpc(intensity, ac96h, region.k_geo)
    icc_geo = classify_icc_geo(cpc, region.cpc_breaks)
    icc_hid = classify_icc_hid(ac24h, region.hid24h_breaks)

    rd_geo = combine_ra_icc(ra, icc_geo)
    rd_hid = combine_ra_icc(ra, icc_hid)
    rd = max(rd_geo, rd_hid)

    return RiskResult(
        lat=lat, lon=lon,
        region_id=region.id, region_name=region.nome, rodovia=region.rodovia,
        ac96h_mm=round(ac96h, 1),
        intensity_mmh=round(intensity, 1),
        ac24h_mm=round(ac24h, 1),
        cpc=round(cpc, 2) if cpc is not None else None,
        icc_geo=icc_geo, icc_hid=icc_hid,
        ra=ra, rd_geo=rd_geo, rd_hid=rd_hid, rd=rd,
        nivel=NIVEIS[rd]
    )
