"""
Eleicao de lider para ingest MERGE sob gunicorn multi-worker.

Apenas um processo deve baixar/decodificar GRIBs; os demais workers
hidratam RAM a partir do cache em disco.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import IO, Any, List, Optional

log = logging.getLogger("merge_leader")

# Mantem o fd do lock aberto ate o processo terminar (sem `global`).
_LOCK_HANDLE: List[Optional[IO[Any]]] = [None]


def _try_file_lock(handle: IO[Any]) -> bool:
    """Tenta lock exclusivo nao-bloqueante (Windows ou POSIX)."""
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        fcntl = importlib.import_module("fcntl")
    except ImportError:
        return True
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def try_acquire_merge_leader() -> bool:
    """True se este processo deve rodar ingest + scheduler MERGE."""
    forced = os.environ.get("SAMAEG_INGEST_LEADER", "").strip().lower()
    if forced in ("1", "true", "yes"):
        return True
    if forced in ("0", "false", "no"):
        return False

    from . import merge_cache

    lock_path = Path(
        os.environ.get(
            "SAMAEG_INGEST_LOCK",
            str(merge_cache.CACHE_ROOT / ".ingest.lock"),
        ),
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        handle = open(lock_path, "a+b")
    except OSError as e:
        log.warning("lock ingest indisponivel (%s): %s", lock_path, e)
        return True

    if not _try_file_lock(handle):
        handle.close()
        return False

    _LOCK_HANDLE[0] = handle
    log.info("Lider ingest MERGE (pid=%s, lock=%s)", os.getpid(), lock_path)
    return True
