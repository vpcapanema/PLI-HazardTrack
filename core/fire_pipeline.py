"""
Runner automatico do modulo de risco de fogo (queimadas).

Diferente de `core/fire_risk.py` (que so LE produtos prontos no ciclo HTTP),
este modulo ORQUESTRA a atualizacao periodica dos produtos:

1. Faz polling barato no diretorio oficial do INPE (apenas a listagem HTML)
   para descobrir o ultimo arquivo de RF observado publicado.
2. Se houver arquivo novo (ou se os produtos locais estiverem defasados),
   roda o pipeline batch `05 -> 06 -> 07` via subprocess isolado.
3. `core/fire_risk.py` recarrega o cache automaticamente por mtime.

O subprocess isola o trabalho pesado (download NetCDF/GeoTIFF + rasterio +
geopandas) do processo Flask: uma falha/OOM no pipeline nao derruba o web
worker. Um lock em arquivo evita execucoes concorrentes entre os workers do
gunicorn.

Variaveis de ambiente:
- QUEIMADAS_AUTO        liga/desliga o runner (default "1")
- QUEIMADAS_POLL_MIN    intervalo de polling em minutos (default "30")
- QUEIMADAS_RUN_TIMEOUT_S  timeout de cada etapa em segundos (default "1800")
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

log = logging.getLogger("samaeg.fire")

ROOT = Path(__file__).resolve().parent.parent
PIPE_DIR = ROOT / "ferramentas" / "queimadas"
META_DIR = ROOT / "data" / "queimadas" / "metadata"
_PUBLIC_DIR = ROOT / "static" / "data" / "queimadas"
STATS_JSON = _PUBLIC_DIR / "risco_trechos_der_stats.json"
LATEST_GEOJSON = _PUBLIC_DIR / "risco_trechos_der_latest.geojson"

MARKER_PATH = META_DIR / "auto_runner.json"
LOCK_PATH = META_DIR / ".auto_runner.lock"
LOCK_STALE_S = 3600

OBS_INDEX = (
    "https://dataserver-coids.inpe.br/queimadas/queimadas/"
    "riscofogo_meteorologia/observado/risco_fogo/"
)

_STEPS = (
    "05_compute_rf_grid.py",
    "06_aggregate_to_der_segments.py",
    "07_export_public_layers.py",
)

# Serializa chamadas dentro do mesmo processo (o lock em arquivo cobre o
# caso multi-worker do gunicorn).
_RUN_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_timeout_s() -> int:
    try:
        return int(os.environ.get("QUEIMADAS_RUN_TIMEOUT_S", "1800") or 1800)
    except ValueError:
        return 1800


def latest_observed_filename(timeout: int = 20) -> Optional[str]:
    """Listagem barata do diretorio INPE: ultimo arquivo observado."""
    try:
        html = requests.get(OBS_INDEX, timeout=timeout).text
    except requests.RequestException as exc:
        log.warning("[fire] falha ao consultar INPE: %s", exc)
        return None
    files = sorted(set(re.findall(
        r'href="(INPE_FireRiskModel_2\.2_FireRisk_\d{8}\.nc)"',
        html,
    )))
    return files[-1] if files else None


def _read_marker() -> Dict[str, Any]:
    try:
        return json.loads(MARKER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_marker(payload: Dict[str, Any]) -> None:
    try:
        META_DIR.mkdir(parents=True, exist_ok=True)
        MARKER_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("[fire] nao foi possivel gravar marker: %s", exc)


def _stats_reference_date() -> Optional[str]:
    try:
        data = json.loads(STATS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("data_referencia")


def _products_exist() -> bool:
    return LATEST_GEOJSON.exists() and STATS_JSON.exists()


def _file_reference_date(filename: Optional[str]) -> Optional[str]:
    """Data YYYY-MM-DD embutida no nome do NetCDF observado INPE."""
    if not filename:
        return None
    m = re.search(r"FireRisk_(\d{4})(\d{2})(\d{2})\.nc", filename)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _is_synced(latest: Optional[str]) -> bool:
    """True somente se o pipeline PROCESSOU o ultimo arquivo INPE."""
    if not latest or not _products_exist():
        return False
    marker = _read_marker()
    if marker.get("observed_file") != latest:
        return False
    if not marker.get("ran_at"):
        return False
    ref = _stats_reference_date()
    file_ref = _file_reference_date(latest)
    if ref and file_ref and ref < file_ref:
        return False
    return True


def _needs_update(latest: Optional[str]) -> bool:
    if not latest:
        return not _products_exist()
    return not _is_synced(latest)


def _auto_allowed() -> bool:
    from core import alert_controls
    if os.environ.get("QUEIMADAS_AUTO", "1") == "0":
        return False
    return alert_controls.is_fire_enabled()


def get_runner_status(poll_inpe: bool = True) -> Dict[str, Any]:
    """Estado do runner para painel admin.

    poll_inpe=False evita a chamada de rede a INPE (usado em /api/health,
    que precisa ser rapido e nao pode depender de rede externa).
    """
    marker = _read_marker()
    try:
        poll_min = int(os.environ.get("QUEIMADAS_POLL_MIN", "30") or 30)
    except ValueError:
        poll_min = 30
    if poll_inpe:
        latest = latest_observed_filename(timeout=8)
    else:
        latest = marker.get("observed_file")
    return {
        "monitoring_enabled": _auto_allowed(),
        "poll_min": poll_min,
        "inpe_checked_live": poll_inpe,
        "inpe_latest_file": latest,
        "inpe_latest_date": _file_reference_date(latest),
        "observed_file": marker.get("observed_file"),
        "data_referencia": _stats_reference_date(),
        "last_run": marker.get("ran_at"),
        "last_reason": marker.get("reason"),
        "synced": _is_synced(latest),
        "pending_update": _needs_update(latest) if poll_inpe else None,
        "lock_active": LOCK_PATH.exists(),
    }


def _data_is_fresh() -> bool:
    """True se produto local reflete o ultimo arquivo observado do INPE."""
    latest = latest_observed_filename(timeout=12)
    return _is_synced(latest)


def _acquire_lock() -> bool:
    """Lock cross-process via arquivo (O_EXCL). Retorna True se adquiriu."""
    META_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()}:{int(time.time())}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Lock existente: considerar obsoleto se for muito antigo.
        try:
            raw = LOCK_PATH.read_text(encoding="utf-8")
            ts = int(raw.split(":")[-1])
        except (OSError, ValueError):
            ts = 0
        if time.time() - ts > LOCK_STALE_S:
            log.warning("[fire] lock obsoleto encontrado; assumindo controle")
            _release_lock()
            return _acquire_lock()
        return False


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def _run_step(name: str) -> None:
    script = PIPE_DIR / name
    if not script.exists():
        raise FileNotFoundError(f"script ausente: {script}")
    log.info("[fire] etapa %s ...", name)
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=_run_timeout_s(),
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        raise RuntimeError(
            f"{name} falhou (rc={proc.returncode}): " + " | ".join(tail)
        )


def run_once(force: bool = False, reason: str = "manual") -> Dict[str, Any]:
    """Roda o pipeline 05->07 se houver produto novo do INPE.

    Retorna um dict de status (status: skip|ok|busy|error|no_source).
    """
    if not force and not _auto_allowed():
        return {"status": "disabled", "reason": reason}
    if not _RUN_LOCK.acquire(blocking=False):
        return {"status": "busy", "reason": reason}
    try:
        latest = latest_observed_filename()
        if not force and latest and _is_synced(latest):
            return {"status": "skip", "latest": latest, "reason": reason}
        if not latest and not force:
            return {"status": "no_source", "reason": reason}

        if not _acquire_lock():
            return {"status": "busy", "reason": reason, "lock": "file"}
        started = time.time()
        try:
            log.info(
                "[fire] iniciando pipeline (motivo=%s, alvo=%s)",
                reason, latest or "forcado",
            )
            for step in _STEPS:
                _run_step(step)
        finally:
            _release_lock()

        elapsed = round(time.time() - started, 1)
        marker_payload = {
            "observed_file": latest,
            "data_referencia": _stats_reference_date(),
            "ran_at": _now_iso(),
            "elapsed_s": elapsed,
            "reason": reason,
        }
        _write_marker(marker_payload)
        log.info("[fire] pipeline concluido em %ss (%s)", elapsed, latest)
        return {"status": "ok", **marker_payload}
    except Exception as exc:  # noqa: BLE001 - logamos e seguimos
        log.exception("[fire] pipeline falhou: %s", exc)
        return {"status": "error", "error": str(exc), "reason": reason}
    finally:
        _RUN_LOCK.release()


def poll_and_maybe_run() -> Dict[str, Any]:
    """Job periodico: poll INPE (resolucao diaria) e processa se necessario."""
    if not _auto_allowed():
        return {"status": "disabled"}
    return run_once(force=False, reason="poll")


def bootstrap_initial() -> Dict[str, Any]:
    """No boot, sincroniza produto local com o ultimo arquivo observado INPE."""
    if not _auto_allowed():
        return {"status": "disabled"}
    latest = latest_observed_filename()
    if not _needs_update(latest):
        log.info("[fire] produto sincronizado com INPE (%s)", latest)
        return {"status": "fresh", "latest": latest}
    log.info(
        "[fire] produto defasado/ausente (INPE=%s); rodando pipeline",
        latest,
    )
    return run_once(force=False, reason="boot")
