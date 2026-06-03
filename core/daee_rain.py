"""
Ingestao de dados pluviometricos do DAEE-SP via API publica.

Fonte: http://sibh.daee.sp.gov.br/api/eventos_ultimas_horas
Documentacao: Produto 6 (Sistema), item 4.5.4.1.2

A API retorna registros horarios de pluviometros automaticos do estado de SP.
O sistema original (TerraMA²) usava esta fonte como alternativa ao
Hidroestimador, com interpolacao por Vizinho Natural (0,027° célula).

Politica de uso:
- Fonte COMPLEMENTAR ao MERGE/INPE (nao substitui).
- Usada para validacao cruzada ou como fallback quando MERGE indisponivel.
- A amostragem espacial é grosseira (161 estacoes na area de estudo),
  mas temporalmente mais precisa (1h vs 3h latencia do MERGE).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
import logging
import os

import requests

log = logging.getLogger("daee")

DAEE_API_URL = os.environ.get(
    "SAMAEG_DAEE_URL",
    "http://sibh.daee.sp.gov.br/api/eventos_ultimas_horas"
)
DAEE_TIMEOUT = float(os.environ.get("SAMAEG_DAEE_TIMEOUT", "15"))
# Limiar de horas sem dados para descartar uma estacao
DAEE_MAX_AGE_HOURS = int(os.environ.get("SAMAEG_DAEE_MAX_AGE", "3"))


@dataclass
class DaeeStation:
    """Dados de uma estacao pluviometrica do DAEE."""
    codigo: str
    nome: str
    lat: float
    lon: float
    municipio: Optional[str]
    chuva_mm: float       # chuva acumulada no periodo solicitado
    horas: int            # periodo de acumulacao (horas)
    datahora: Optional[datetime]


@dataclass
class DaeeResult:
    """Resultado agregado da consulta DAEE para N pontos."""
    stations: List[DaeeStation]
    ac24h_mm: float       # media ponderada inversa-distancia nos pontos
    ac96h_mm: float       # extrapolado: ac24h * 4 (aproximacao)
    intensity_mmh: float  # ac24h / 24
    source: str
    files_ok: int
    missing_24h: int
    missing_96h: int


def fetch_raw(horas: int = 1, timeout: float = DAEE_TIMEOUT) -> List[Dict]:
    """
    Busca dados brutos da API do DAEE.

    Args:
        horas: quantas horas de acumulado (1, 6, 12, 24, etc.)
        timeout: segundos para a requisicao

    Returns:
        Lista de dicts com os registros. Em caso de falha, lista vazia.
    """
    url = f"{DAEE_API_URL}?horas={horas}"
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "dados" in data:
            return data["dados"]
        log.warning("Formato inesperado da API DAEE: %s", type(data))
        return []
    except requests.RequestException as e:
        log.warning("Falha ao consultar DAEE: %s", e)
        return []
    except Exception as e:
        log.warning("Erro inesperado DAEE: %s", e)
        return []


def _parse_station(raw: Dict) -> Optional[DaeeStation]:
    """Converte registro bruto da API em DaeeStation."""
    try:
        chuva = float(raw.get("chuva_mm", raw.get("chuva", 0.0)))
        lat = float(raw.get("latitude", raw.get("lat", 0.0)))
        lon = float(raw.get("longitude", raw.get("lon", 0.0)))
        if lat == 0.0 and lon == 0.0:
            return None
        # Datahora pode vir em varios formatos
        dh_str = raw.get("datahora") or raw.get("data_hora")
        datahora = None
        if dh_str:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                        "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    datahora = datetime.strptime(dh_str, fmt)
                    datahora = datahora.replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    pass
        return DaeeStation(
            codigo=str(raw.get("codigo", raw.get("id", ""))),
            nome=str(raw.get("nome", "")),
            lat=lat, lon=lon,
            municipio=raw.get("municipio"),
            chuva_mm=chuva,
            horas=int(raw.get("horas", 1)),
            datahora=datahora,
        )
    except (ValueError, TypeError) as e:
        log.debug("Registro DAEE ignorado (parse error): %s", e)
        return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia em km entre dois pontos."""
    import math
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def interpolate_for_points(
    stations: List[DaeeStation],
    points: List[Tuple[float, float]],
    horas: int = 1
) -> List[float]:
    """
    Interpolacao por inverso da distancia (IDW) para N pontos.

    Usada como substituto simplificado do Vizinho Natural do TerraMA².
    Potencia p=2 (inverso do quadrado da distancia).
    """
    out = []
    for plat, plon in points:
        num = 0.0
        den = 0.0
        for s in stations:
            d = _haversine(plat, plon, s.lat, s.lon)
            if d < 0.1:  # dentro de 100m: usa valor direto
                num = s.chuva_mm
                den = 1.0
                break
            w = 1.0 / (d ** 2)
            num += s.chuva_mm * w
            den += w
        if den > 0:
            out.append(num / den)
        else:
            out.append(0.0)
    return out


def fetch_daee_batch(
    coords: List[Tuple[float, float]],
    horas: int = 24
) -> Optional[List[DaeeResult]]:
    """
    Busca chuva do DAEE para uma lista de coordenadas.

    Args:
        coords: [(lat, lon), ...]
        horas: periodo de acumulacao (recomendado: 24 para hidrologico)

    Returns:
        Lista de DaeeResult (um por ponto), ou None em caso de falha total.
    """
    raw = fetch_raw(horas=horas)
    if not raw:
        return None

    stations = [s for s in (_parse_station(r) for r in raw) if s is not None]
    if not stations:
        log.warning("Nenhuma estacao DAEE valida apos parse")
        return None

    log.info("DAEE: %d estacoes carregadas (periodo=%dh)", len(stations), horas)

    # Interpolar para cada ponto
    chuva_interp = interpolate_for_points(stations, coords, horas=horas)

    # Para cada ponto, criar um DaeeResult compativel com a interface do aggregator
    results = []
    for chuva in chuva_interp:
        # Extrapola ac96h = ac24h * 4 (aproximacao linear)
        # e intensidade = ac24h / 24
        ac24h = chuva
        ac96h = ac24h * 4.0 if horas == 24 else ac24h
        intensity = ac24h / 24.0 if horas == 24 else ac24h / horas
        results.append(DaeeResult(
            stations=stations,
            ac24h_mm=round(ac24h, 1),
            ac96h_mm=round(ac96h, 1),
            intensity_mmh=round(intensity, 1),
            source="DAEE",
            files_ok=len(stations),
            missing_24h=0,
            missing_96h=0,
        ))

    return results
