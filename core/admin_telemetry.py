"""
Telemetria persistente dos ciclos do pipeline geodinamico (painel /admin).

Cada ciclo do scheduler grava UM registro compacto (JSON por linha) em
``PLI_RUNTIME_DIR/cycle_telemetry.jsonl`` — na VM esse diretorio e o
volume Docker ``pli_hazardtrack_runtime``, entao a serie sobrevive a
reinicios e rebuilds do container. Ring buffer: mantem no maximo
``MAX_ENTRIES`` registros (default 2016 = 14 dias a 10 min).

Espelho em RAM para leitura rapida pelo Analytics; escrita e append-only
com compactacao periodica.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("admin_telemetry")

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(
    os.environ.get("PLI_RUNTIME_DIR", str(ROOT / "data" / "_runtime")),
)
TELEMETRY_PATH = RUNTIME_DIR / "cycle_telemetry.jsonl"
MAX_ENTRIES = int(os.environ.get("PLI_TELEMETRY_MAX", "2016"))

_lock = threading.Lock()
_entries: List[Dict[str, Any]] = []
_loaded = False


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_locked() -> None:
    global _loaded, _entries
    if _loaded:
        return
    _loaded = True
    _entries = []
    try:
        raw = TELEMETRY_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("started_at"):
            _entries.append(obj)
    if len(_entries) > MAX_ENTRIES:
        _entries = _entries[-MAX_ENTRIES:]


def _rewrite_locked() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TELEMETRY_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for e in _entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, TELEMETRY_PATH)


def record(entry: Dict[str, Any]) -> None:
    """Acrescenta um ciclo; compacta o arquivo quando passa do limite."""
    with _lock:
        _load_locked()
        _entries.append(entry)
        try:
            if len(_entries) > int(MAX_ENTRIES * 1.25):
                del _entries[:-MAX_ENTRIES]
                _rewrite_locked()
                return
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            with TELEMETRY_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("telemetria: falha ao gravar (%s)", e)


def load(
    hours: Optional[float] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Registros em ordem cronologica, filtrados por janela/limite."""
    with _lock:
        _load_locked()
        rows = list(_entries[-MAX_ENTRIES:])
    if hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = [
            r for r in rows
            if (_parse_ts(r.get("started_at")) or cutoff) >= cutoff
        ]
    if limit and len(rows) > limit:
        rows = rows[-limit:]
    return rows


def count() -> int:
    with _lock:
        _load_locked()
        return len(_entries)


def reset_for_tests(path: Path) -> None:
    """Redireciona o armazenamento (usado pelos testes)."""
    global RUNTIME_DIR, TELEMETRY_PATH, _entries, _loaded
    with _lock:
        RUNTIME_DIR = path
        TELEMETRY_PATH = path / "cycle_telemetry.jsonl"
        _entries = []
        _loaded = False
