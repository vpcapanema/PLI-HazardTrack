"""Referencia global ao APScheduler (pausa/retoma via admin)."""
from __future__ import annotations

from typing import Any, Optional

_scheduler: Optional[Any] = None


def set_scheduler(sched: Any) -> None:
    global _scheduler  # noqa: PLW0603
    _scheduler = sched


def get_scheduler() -> Optional[Any]:
    return _scheduler
