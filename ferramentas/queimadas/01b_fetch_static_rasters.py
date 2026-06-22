"""
Baixa rasters estaticos publicos do modulo de queimadas.

Saidas:
- data/queimadas/base/dem_copernicus_glo90_tiles/*.tif
- data/queimadas/metadata/static_downloads.json

MapBiomas por UF NAO tem link direto publico pronto. O recorte de Sao Paulo
deve ser exportado no Google Earth Engine com
`ferramentas/queimadas/01c_export_mapbiomas_sp_gee.js` e salvo como:

    data/queimadas/base/vegetacao_inpe.tif
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = ROOT / "data" / "queimadas" / "base"
META_DIR = ROOT / "data" / "queimadas" / "metadata"
LIMITE_GPKG = BASE_DIR / "limite_sp.gpkg"

COP_DEM_RES_ARCSEC = "30"  # GLO-90 bucket uses resolution token 30.
COP_DEM_BUCKET = "https://copernicus-dem-90m.s3.amazonaws.com"
COP_DEM_DIR = BASE_DIR / "dem_copernicus_glo90_tiles"
ALTITUDE_PLACEHOLDER = BASE_DIR / "altitude_sp.tif"

STATIC_META = META_DIR / "static_downloads.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = {}
    mode = "wb"
    existing = out.stat().st_size if out.exists() else 0
    if existing:
        headers["Range"] = f"bytes={existing}-"
        mode = "ab"

    with requests.get(
        url,
        stream=True,
        timeout=(10, 120),
        headers=headers,
    ) as response:
        if response.status_code == 416:
            pass
        else:
            response.raise_for_status()
            with out.open(mode) as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

    return {
        "path": str(out.relative_to(ROOT)),
        "bytes": out.stat().st_size,
        "sha256": _sha256(out),
        "url": url,
    }


def _hem_lat(value: int) -> str:
    return f"N{value:02d}_00" if value >= 0 else f"S{abs(value):02d}_00"


def _hem_lon(value: int) -> str:
    return f"E{value:03d}_00" if value >= 0 else f"W{abs(value):03d}_00"


def _cop_dem_url(lat: int, lon: int) -> tuple[str, str]:
    tile = (
        f"Copernicus_DSM_COG_{COP_DEM_RES_ARCSEC}_"
        f"{_hem_lat(lat)}_{_hem_lon(lon)}_DEM"
    )
    return tile, f"{COP_DEM_BUCKET}/{tile}/{tile}.tif"


def _sp_tile_ranges() -> tuple[range, range, list[float]]:
    if not LIMITE_GPKG.exists():
        raise FileNotFoundError(
            f"Limite nao encontrado: {LIMITE_GPKG}. Rode 01_prepare_base_layers.py"
        )
    gdf = gpd.read_file(LIMITE_GPKG, layer="limite_sp").to_crs("EPSG:4326")
    minx, miny, maxx, maxy = [float(x) for x in gdf.total_bounds]
    lat_range = range(math.floor(miny), math.ceil(maxy))
    lon_range = range(math.floor(minx), math.ceil(maxx))
    return lat_range, lon_range, [minx, miny, maxx, maxy]


def download_copernicus_dem() -> dict:
    lat_range, lon_range, bbox = _sp_tile_ranges()
    COP_DEM_DIR.mkdir(parents=True, exist_ok=True)
    tiles = []
    for lat in lat_range:
        for lon in lon_range:
            tile, url = _cop_dem_url(lat, lon)
            out = COP_DEM_DIR / f"{tile}.tif"
            print(f"Baixando DEM tile: {tile}")
            try:
                info = _download(url, out)
                info["tile"] = tile
                info["lat"] = lat
                info["lon"] = lon
                tiles.append(info)
            except requests.HTTPError as exc:
                print(f"  ignorado ({exc})")
    return {
        "source": "Copernicus DEM GLO-90 Public",
        "target_mosaic": str(ALTITUDE_PLACEHOLDER.relative_to(ROOT)),
        "bbox_sp": bbox,
        "tiles_count": len(tiles),
        "tiles": tiles,
    }


def main() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "modulo": "queimadas",
        "status": "dem_baixado_mapbiomas_pendente_gee",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "mapbiomas": {
            "status": "pendente_export_gee",
            "target": "data/queimadas/base/vegetacao_inpe.tif",
            "script": "ferramentas/queimadas/01c_export_mapbiomas_sp_gee.js",
            "asset": (
                "projects/mapbiomas-public/assets/brazil/lulc/"
                "collection10_1/mapbiomas_brazil_collection10_1_coverage_v1"
            ),
        },
        "dem": download_copernicus_dem(),
    }
    STATIC_META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Metadata: {STATIC_META}")


if __name__ == "__main__":
    main()
