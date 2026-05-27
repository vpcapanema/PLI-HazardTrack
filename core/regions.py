"""
Definicao das 4 regioes climaticas-geologico-geomorfologicas DER-SP.
Fonte: Relatorio REGEA-NIPPON 2053-R02-20 (Etapa 1, Tabela 3.1.1-1).

Os polígonos abaixo sao APROXIMACOES preliminares baseadas nas descricoes
do relatorio. Quando o shapefile oficial estiver disponivel em
data/regioes_pli/regioes_pli_dersp.shp, ele tem precedencia.

Cada regiao tem:
- K_geo: constante da envoltoria geologica (I = K x Ac96h^-0.9)
- limiares CPC: faixas para classificar ICC geologico
- limiares 24h: limites de chuva acumulada para classificar ICC hidrologico
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from pathlib import Path
import json

# Polígonos aproximados das 4 regioes (lat, lon) em sentido horario
# Calibrar com shapefile oficial quando disponivel.
APPROXIMATE_REGIONS = [
    {
        "id": 1,
        "nome": "Mogi-Bertioga",
        "rodovia": "SP-098",
        "k_geo": 1000,
        "cpc_breaks": [1, 3, 6, 15],          # ICC0|1|2|3|4
        "hid24h_breaks": [110, 160, 200, 280],
        "polygon": [
            (-23.42, -46.28),
            (-23.42, -45.98),
            (-23.95, -45.98),
            (-23.95, -46.28),
        ]
    },
    {
        "id": 2,
        "nome": "Caraguatatuba-Ubatuba",
        "rodovia": "SP-055",
        "k_geo": 400,
        "cpc_breaks": [1, 6, 12, 24],
        "hid24h_breaks": [70, 80, 120, 143],
        "polygon": [
            (-23.18, -45.30),
            (-23.18, -44.80),
            (-23.78, -44.80),
            (-23.78, -45.30),
        ]
    },
    {
        "id": 3,
        "nome": "São Sebastião",
        "rodovia": "SP-055",
        "k_geo": 200,
        "cpc_breaks": [1, 8, 16, 24],
        "hid24h_breaks": [60, 85, 110, 126],
        "polygon": [
            (-23.62, -45.80),
            (-23.62, -45.30),
            (-23.95, -45.30),
            (-23.95, -45.80),
        ]
    },
    {
        "id": 4,
        "nome": "Santos-Bertioga",
        "rodovia": "SP-055",
        "k_geo": 1000,
        "cpc_breaks": [1, 4, 8, 16],
        "hid24h_breaks": [150, 200, 230, 300],
        "polygon": [
            (-23.78, -46.40),
            (-23.78, -45.95),
            (-24.10, -45.95),
            (-24.10, -46.40),
        ]
    }
]


@dataclass
class Region:
    id: int
    nome: str
    rodovia: str
    k_geo: float
    cpc_breaks: List[float]
    hid24h_breaks: List[float]
    polygon: List[Tuple[float, float]] = field(default_factory=list)

    def contains(self, lat: float, lon: float) -> bool:
        """Point-in-polygon (ray casting) sem dependencia de shapely."""
        if not self.polygon:
            return False
        n = len(self.polygon)
        inside = False
        j = n - 1
        for i in range(n):
            yi, xi = self.polygon[i]
            yj, xj = self.polygon[j]
            if ((yi > lat) != (yj > lat)) and (
                lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi
            ):
                inside = not inside
            j = i
        return inside


def load_regions(shapefile_path: Optional[Path] = None) -> List[Region]:
    """
    Carrega regioes preferencialmente do shapefile oficial.
    Fallback: poligonos aproximados embutidos.
    """
    if shapefile_path and shapefile_path.exists():
        try:
            import geopandas as gpd
            gdf = gpd.read_file(shapefile_path)
            regions = []
            for _, row in gdf.iterrows():
                geom = row.geometry
                # Para Polygon ou MultiPolygon, pega o exterior
                if geom.geom_type == "Polygon":
                    coords = [(y, x) for x, y in geom.exterior.coords]
                else:
                    coords = [(y, x) for x, y in list(geom.geoms)[0].exterior.coords]
                regions.append(Region(
                    id=int(row.get("regiao", row.get("id", 0))),
                    nome=str(row.get("nome", "?")),
                    rodovia=str(row.get("rodovia", "?")),
                    k_geo=float(row.get("k_geo", 1000)),
                    cpc_breaks=json.loads(row["cpc_breaks"]) if "cpc_breaks" in row else [1, 3, 6, 15],
                    hid24h_breaks=json.loads(row["hid24h_breaks"]) if "hid24h_breaks" in row else [110, 160, 200, 280],
                    polygon=coords
                ))
            return regions
        except Exception as e:
            print(f"Falha ao ler shapefile, usando aproximacao: {e}")

    return [Region(**r) for r in APPROXIMATE_REGIONS]


def find_region_for_point(lat: float, lon: float, regions: List[Region]) -> Optional[Region]:
    """Retorna a regiao que contem o ponto, ou None se fora."""
    for r in regions:
        if r.contains(lat, lon):
            return r
    return None
