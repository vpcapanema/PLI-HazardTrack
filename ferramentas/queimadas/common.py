"""Utilitarios compartilhados do pipeline de queimadas."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, Optional

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "queimadas"
BASE_DIR = DATA_DIR / "base"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
META_DIR = DATA_DIR / "metadata"
PUBLIC_DIR = ROOT / "static" / "data" / "queimadas"

TRECHOS_GPKG = BASE_DIR / "trechos_der_sp.gpkg"
LIMITE_GPKG = BASE_DIR / "limite_sp.gpkg"
VEGETACAO_TIF = BASE_DIR / "vegetacao_inpe.tif"
ALTITUDE_TIF = BASE_DIR / "altitude_sp.tif"
RISK_GPKG = PROCESSED_DIR / "risco_trechos_der.gpkg"
MONITORED_ROAD_LAYER = "malha_rodoviaria_estadual_monitorada"
LATEST_GEOJSON = PUBLIC_DIR / "risco_trechos_der_latest.geojson"
LATEST_JSON = PUBLIC_DIR / "risco_trechos_der_latest.json"
LATEST_STATS = PUBLIC_DIR / "risco_trechos_der_stats.json"

METHODOLOGY = "INPE-RF-v11"
SEM_DADO = "SEM_DADO"


def ensure_dirs() -> None:
    for path in (
        BASE_DIR, RAW_DIR, INTERIM_DIR, PROCESSED_DIR, META_DIR, PUBLIC_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_date_arg(description: str) -> date:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Data de referencia YYYY-MM-DD (default: hoje local).",
    )
    parser.add_argument(
        "--backfill",
        type=int,
        default=None,
        help="Reservado para scripts de ingest historica.",
    )
    args = parser.parse_args()
    if str(args.date).lower() == "today":
        return date.today()
    return date.fromisoformat(args.date)


def sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def read_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_trechos() -> gpd.GeoDataFrame:
    if not TRECHOS_GPKG.exists():
        raise FileNotFoundError(
            f"Malha base ausente: {TRECHOS_GPKG}. "
            "Rode ferramentas/queimadas/01_prepare_base_layers.py"
        )
    return gpd.read_file(TRECHOS_GPKG, layer="trechos").to_crs("EPSG:4326")


def rf_class(value: Optional[float]) -> str:
    if value is None:
        return SEM_DADO
    if value < 0.15:
        return "minimo"
    if value <= 0.40:
        return "baixo"
    if value <= 0.70:
        return "medio"
    if value <= 0.95:
        return "alto"
    return "critico"


def sem_dado_fields(ref_date: date, horizonte: str = "observado") -> Dict[str, Any]:
    return {
        "data_referencia": ref_date.isoformat(),
        "horizonte": horizonte,
        "data_alvo": ref_date.isoformat(),
        "rf_valor": None,
        "rf_classe": SEM_DADO,
        "rf_p90": None,
        "rf_media": None,
        "metodologia": METHODOLOGY,
        "fonte_precipitacao": None,
        "fonte_meteo": None,
        "focos_correcao": False,
        "data_status": "no_data",
        "gerado_em": now_iso(),
    }


def pipeline_status_path(name: str, ref_date: date) -> Path:
    return META_DIR / f"{name}_{ref_date.strftime('%Y%m%d')}.json"
