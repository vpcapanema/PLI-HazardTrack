"""
Definicao das 4 regioes climaticas-geologico-geomorfologicas DER-SP.

Fonte de geometria (perimetro): camada `regioes_estudo` do GeoPackage
oficial `data/pli-hazardtrack.gpkg` (gerada por buffer lateral de
1000 m do eixo cadastral dos subtrechos DER), exportada como GeoJSON
em `data/regioes/regioes_estudo.geojson` pelo script
`ferramentas/geracao-geopackage/05_export_regioes_geojson.py`.

O eixo (polilinha) por regiao vem de `auxilio_regioes_estudo`
dissolvido por `regiao_id`, exportado para
`data/regioes/regioes_eixos.geojson`.

Os parametros climaticos (`k_geo`, `cpc_breaks`, `hid24h_breaks`)
sao injetados no GeoJSON-poligono durante o export a partir das
Tabelas 3.1.1-2 e 3.1.2-1 do PRODUTO 6 (REGEA-NIPPON, 2021).

Cada regiao tem:
- K_geo: constante da envoltoria geologica (I = K x Ac96h^-0.9)
- limiares CPC: faixas para classificar ICC geologico
- limiares 24h: limites de chuva acumulada para classificar ICC hidrologico
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Optional, cast
from pathlib import Path
import json
import logging

log = logging.getLogger("regions")

# GeoJSONs canonicos exportados do GeoPackage `pli-hazardtrack.gpkg`
# pelo script `ferramentas/geracao-geopackage/05_export_regioes_geojson.py`.
# O acervo legado extraido por segmentacao de cor da Fig 3.2.1-1 do
# PRODUTO 7 esta em `data/_obsoleto_regioes_pli/` apenas para auditoria.
_POLY_CANDIDATES = [
    "data/regioes/regioes_estudo.geojson",
]
_EIXO_CANDIDATES = [
    "data/regioes/regioes_eixos.geojson",
]
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Atributos NATIVOS de `regioes_estudo` propagados pelo backend para o
# frontend (popups, sidebar). Lista de referencia consumida por
# `aggregator._region_snapshot_entry`.
NATIVE_REGION_KEYS = (
    "regiao_id", "regiao_nome", "sigla_rodovia",
    "km_inicial", "km_final", "extensao_oficial_km",
    "n_subtrechos_der", "municipios", "ubas", "ubas_codigo",
    "residencias_dr", "regionais", "jurisdicoes",
    "conservado_por", "subtrechos_der",
    "area_km2", "perimetro_km", "buffer_lateral_m",
    "tampas_round", "n_caps_round_adicionadas",
    "k_geo", "cpc_breaks", "hid24h_breaks",
)

# Poligonos retangulares aproximados (fallback historico). Sao usados
# apenas se nenhum GeoJSON oficial estiver presente no disco.
APPROXIMATE_REGIONS = [
    {
        "id": 1,
        "nome": "Mogi-Bertioga",
        "rodovia": "SP-098",
        "k_geo": 1000,
        "cpc_breaks": [1, 3, 6, 15],
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
            (-23.62, -45.95),
            (-23.62, -45.30),
            (-23.95, -45.30),
            (-23.95, -45.95),
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
    # Anel exterior (lat, lon) do poligono de monitoramento.
    polygon: List[Tuple[float, float]] = field(default_factory=list)
    # Polilinha eixo (lat, lon) - usada por find_nearest_region_for_point.
    eixo: List[Tuple[float, float]] = field(default_factory=list)
    # Atributos NATIVOS de `regioes_estudo` (sem renomear). Propagados
    # pelo backend para o frontend para popups/tooltips ricos. Vazio
    # quando a regiao vem do fallback retangular.
    native: Dict[str, Any] = field(default_factory=dict)

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

    def distance_to_eixo_km(self, lat: float, lon: float) -> float:
        """Distancia minima (km) ao eixo (polilinha) da rodovia.

        Aproximacao planar local: 1 grau lat ~ 111.32 km; 1 grau lon
        em uma latitude ~ 111.32*cos(lat) km. Suficiente para um raio
        de ate ~50 km no litoral SP (erro << 1%).
        """
        if not self.eixo:
            return float("inf")
        import math
        lat_rad = math.radians(lat)
        cos_lat = math.cos(lat_rad)
        km_per_lat = 111.32
        km_per_lon = 111.32 * cos_lat

        def to_local(la, lo):
            return ((lo - lon) * km_per_lon, (la - lat) * km_per_lat)

        best = float("inf")
        prev = to_local(*self.eixo[0])
        for la, lo in self.eixo[1:]:
            curr = to_local(la, lo)
            # distancia do ponto (0,0) ao segmento prev-curr
            x1, y1 = prev
            x2, y2 = curr
            dx, dy = x2 - x1, y2 - y1
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq < 1e-12:
                d = math.hypot(x1, y1)
            else:
                t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg_len_sq))
                px, py = x1 + t * dx, y1 + t * dy
                d = math.hypot(px, py)
            if d < best:
                best = d
            prev = curr
        return best


def _coerce_break_list(v, default: List[float]) -> List[float]:
    if v is None:
        return default
    if isinstance(v, list):
        return [float(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return default
        # GeoJSON exportado pelo script 05 grava cpc_breaks/hid24h_breaks
        # como string "1;3;6;15" (geopandas nao serializa listas).
        if ";" in s:
            try:
                return [float(x) for x in s.split(";") if x.strip()]
            except Exception:
                return default
        # Compat: aceita tambem "[1,3,6,15]" do schema antigo.
        try:
            return [float(x) for x in json.loads(s)]
        except Exception:
            return default
    return default


def _flatten_linestring_coords(geom: dict) -> List[Tuple[float, float]]:
    """Aplana coordenadas de LineString/MultiLineString em (lat, lon)."""
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    out: List[Tuple[float, float]] = []
    if gtype == "LineString":
        for c in coords:
            out.append((float(c[1]), float(c[0])))
    elif gtype == "MultiLineString":
        for ls in coords:
            for c in ls:
                out.append((float(c[1]), float(c[0])))
    return out


def _load_eixos_from_geojson(path: Path) -> Dict[int, List[Tuple[float, float]]]:
    """Le GeoJSON com o eixo (LineString/MultiLineString) por regiao."""
    eixos: Dict[int, List[Tuple[float, float]]] = {}
    if not path.exists():
        return eixos
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return eixos
    for feat in data.get("features", []):
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry") or {}
        rid_raw = props.get("regiao_id", props.get("id", props.get("regiao")))
        if rid_raw is None:
            continue
        try:
            rid = int(rid_raw)
        except Exception:
            continue
        coords = _flatten_linestring_coords(geom)
        if coords:
            eixos[rid] = coords
    return eixos


def _resolve_eixos_path(poly_path: Path) -> Path:
    """Localiza o GeoJSON de eixos correspondente ao GeoJSON de poligonos."""
    sibling_new = poly_path.parent / "regioes_eixos.geojson"
    if sibling_new.exists():
        return sibling_new
    sibling_old = poly_path.parent / "regioes_linestring.geojson"
    if sibling_old.exists():
        return sibling_old
    for rel in _EIXO_CANDIDATES:
        cand = _PROJECT_ROOT / rel
        if cand.exists():
            return cand
    return sibling_new  # nao existente, retornado para log/inspecao


def _polygon_ring(geom: dict) -> List[Tuple[float, float]]:
    """Extrai o anel exterior do poligono em (lat, lon).

    Para MultiPolygon, escolhe o poligono com maior numero de pontos
    no anel exterior (compatibilidade com geometrias dissolvidas).
    """
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        outer = coords[0]
    elif gtype == "MultiPolygon":
        biggest = max(coords, key=lambda p: len(p[0]))
        outer = biggest[0]
    else:
        return []
    # Descarta Z se presente.
    return [(float(c[1]), float(c[0])) for c in outer]


def _build_region_from_feature(
    props: Dict[str, Any],
    geom: dict,
    eixos: Dict[int, List[Tuple[float, float]]],
) -> Optional[Region]:
    """Constroi uma Region a partir de uma Feature do schema novo
    (`regioes_estudo`) ou do schema antigo (`regioes_pli/regioes.geojson`).

    Schema novo (preferido): `regiao_id`, `regiao_nome`, `sigla_rodovia`,
    `k_geo`, `cpc_breaks` (string "a;b;c;d"), `hid24h_breaks`, mais
    todos os atributos nativos administrativos.

    Schema antigo: `id`, `nome`, `rodovia`, `k_geo`, `cpc_breaks` (lista
    JSON), `hid24h_breaks`. Mantido como fallback.
    """
    rid_raw = props.get("regiao_id", props.get("id", props.get("regiao")))
    if rid_raw is None:
        return None
    try:
        rid = int(rid_raw)
    except Exception:
        return None
    nome = str(props.get("regiao_nome", props.get("nome", "?")))
    rodovia = str(props.get("sigla_rodovia", props.get("rodovia", "?")))
    polygon = _polygon_ring(geom)
    if not polygon:
        return None

    # Atributos nativos completos do schema novo (apenas o que vier).
    native: Dict[str, Any] = {}
    for k in NATIVE_REGION_KEYS:
        if k in props:
            v = props[k]
            if k in ("cpc_breaks", "hid24h_breaks"):
                native[k] = _coerce_break_list(v, [])
            else:
                native[k] = v
    # Garante que as chaves chave estejam presentes em `native`
    native.setdefault("regiao_id", rid)
    native.setdefault("regiao_nome", nome)
    native.setdefault("sigla_rodovia", rodovia)

    return Region(
        id=rid,
        nome=nome,
        rodovia=rodovia,
        k_geo=float(props.get("k_geo", 1000)),
        cpc_breaks=_coerce_break_list(
            props.get("cpc_breaks"), [1, 3, 6, 15]),
        hid24h_breaks=_coerce_break_list(
            props.get("hid24h_breaks"), [110, 160, 200, 280]),
        polygon=polygon,
        eixo=eixos.get(rid, []),
        native=native,
    )


def _load_geojson_regions(path: Path) -> List[Region]:
    """Le um GeoJSON FeatureCollection em EPSG:4326 e devolve Region[]."""
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    eixos = _load_eixos_from_geojson(_resolve_eixos_path(path))
    out: List[Region] = []
    for feat in features:
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry") or {}
        r = _build_region_from_feature(props, geom, eixos)
        if r is not None:
            out.append(r)
    return out


def _load_shapefile_regions(path: Path) -> List[Region]:
    """Fallback opcional para shapefile via geopandas (se instalado)."""
    import geopandas as gpd  # type: ignore
    gdf = gpd.read_file(path)
    try:
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")
    except Exception:
        pass
    eixos = _load_eixos_from_geojson(_resolve_eixos_path(path))
    out: List[Region] = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        # Converte geometria shapely em dict GeoJSON minimo
        if geom.geom_type == "Polygon":
            gjson = {
                "type": "Polygon",
                "coordinates": [list(geom.exterior.coords)],
            }
        elif geom.geom_type == "MultiPolygon":
            gjson = {
                "type": "MultiPolygon",
                "coordinates": [
                    [list(p.exterior.coords)] for p in geom.geoms
                ],
            }
        else:
            continue
        props = {k: row[k] for k in row.index if k != "geometry"}
        r = _build_region_from_feature(props, gjson, eixos)
        if r is not None:
            out.append(r)
    return out


def load_regions(shapefile_path: Optional[Path] = None) -> List[Region]:
    """Carrega as 4 regioes monitoradas.

    Ordem de tentativas:
      1. `shapefile_path` explicito (se passado e existir)
      2. data/regioes/regioes_estudo.geojson  (FONTE OFICIAL - GPKG)
      3. fallback: poligonos retangulares aproximados embutidos
    """
    candidates: List[Path] = []
    if shapefile_path is not None:
        candidates.append(Path(shapefile_path))
    for rel in _POLY_CANDIDATES:
        candidates.append(_PROJECT_ROOT / rel)

    for path in candidates:
        if not path.exists():
            continue
        try:
            if path.suffix.lower() == ".geojson":
                regions = _load_geojson_regions(path)
            elif path.suffix.lower() == ".shp":
                regions = _load_shapefile_regions(path)
            else:
                continue
            if regions:
                log.info("Regioes carregadas de %s (%d feicoes)",
                         path.name, len(regions))
                return regions
        except Exception as e:
            log.warning("Falha ao ler %s, seguindo: %s", path, e)

    log.warning(
        "Nenhum GeoJSON oficial encontrado; usando poligonos retangulares "
        "aproximados (fallback)"
    )
    return [
        Region(
            id=cast(int, r["id"]),
            nome=cast(str, r["nome"]),
            rodovia=cast(str, r["rodovia"]),
            k_geo=cast(float, r["k_geo"]),
            cpc_breaks=cast(List[float], r["cpc_breaks"]),
            hid24h_breaks=cast(List[float], r["hid24h_breaks"]),
            polygon=cast(List[Tuple[float, float]], r["polygon"]),
        ) for r in APPROXIMATE_REGIONS
    ]


def find_nearest_region_for_point(
    lat: float,
    lon: float,
    regions: List[Region],
    max_dist_km: float = 30.0,
) -> Optional[Region]:
    """Retorna a regiao cuja polilinha-eixo esta mais proxima do ponto,
    dentro de `max_dist_km`.

    Esta e a atribuicao semanticamente correta: as 4 regioes oficiais
    sao trechos de rodovia (km inicial -> km final), nao polygons de
    area. Cada UA pertence ao trecho de rodovia mais proximo.
    """
    best_r, best_d = None, float("inf")
    for r in regions:
        d = r.distance_to_eixo_km(lat, lon)
        if d < best_d:
            best_d = d
            best_r = r
    if best_r is None or best_d > max_dist_km:
        return None
    return best_r


def find_region_for_point(
    lat: float, lon: float, regions: List[Region]
) -> Optional[Region]:
    """Retorna a regiao que contem o ponto.

    Estrategia:
      1. point-in-polygon no buffer lateral (fast path - cobre maioria)
      2. fallback: regiao com eixo mais proximo (max 30 km)
    """
    for r in regions:
        if r.contains(lat, lon):
            return r
    return find_nearest_region_for_point(lat, lon, regions, 30.0)
