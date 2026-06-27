"""
Controles runtime dos dois sistemas de alerta (ligar/desligar).

Persistidos em disco para sobreviver a restarts leves e serem editaveis
pelo painel /admin. Default: ambos ligados (monitoramento continuo).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger("alert_controls")

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(
    os.environ.get(
        "PLI_RUNTIME_DIR",
        str(ROOT / "data" / "_runtime"),
    ),
)
CONTROLS_PATH = RUNTIME_DIR / "alert_controls.json"

_DEFAULTS: Dict[str, bool] = {
    "geo_monitoring": True,
    "fire_monitoring": True,
}

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _read_raw() -> Dict[str, Any]:
    try:
        data = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _write_raw(payload: Dict[str, Any]) -> None:
    _ensure_dir()
    tmp = CONTROLS_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(CONTROLS_PATH)


def get_state() -> Dict[str, Any]:
    """Estado completo para API admin."""
    with _lock:
        raw = _read_raw()
    geo = bool(raw.get("geo_monitoring", _DEFAULTS["geo_monitoring"]))
    fire = bool(raw.get("fire_monitoring", _DEFAULTS["fire_monitoring"]))
    return {
        "geo_monitoring": geo,
        "fire_monitoring": fire,
        "updated_at": raw.get("updated_at"),
        "updated_by": raw.get("updated_by"),
        "defaults": dict(_DEFAULTS),
    }


def is_geo_enabled() -> bool:
    return get_state()["geo_monitoring"]


def is_fire_enabled() -> bool:
    return get_state()["fire_monitoring"]


def set_system(
    system: str,
    enabled: bool,
    *,
    actor: str = "admin",
) -> Dict[str, Any]:
    """Liga/desliga um sistema. system: geo_monitoring | fire_monitoring."""
    if system not in _DEFAULTS:
        raise ValueError(f"sistema desconhecido: {system}")
    with _lock:
        raw = _read_raw()
        raw[system] = bool(enabled)
        raw["updated_at"] = _now_iso()
        raw["updated_by"] = actor
        _write_raw(raw)
    log.info("alert control %s=%s (by %s)", system, enabled, actor)
    return get_state()


def apply_to_scheduler(scheduler) -> None:
    """Pausa/retoma jobs conforme flags atuais."""
    if scheduler is None:
        return
    try:
        from core import scheduler_registry
        scheduler_registry.set_scheduler(scheduler)
    except ImportError:
        pass

    geo = is_geo_enabled()
    fire = is_fire_enabled()
    for job_id, on in (
        ("merge_refresh", geo),
        ("fire_refresh", fire),
    ):
        try:
            job = scheduler.get_job(job_id)
            if not job:
                continue
            if on:
                job.resume()
            else:
                job.pause()
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler job %s: %s", job_id, exc)

    if not geo:
        try:
            from core.merge_ingest import ingest
            ingest.pause()
        except Exception:
            pass
    else:
        try:
            from core.merge_ingest import ingest
            ingest.resume()
        except Exception:
            pass
