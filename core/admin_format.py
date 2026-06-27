"""Formatacao padrao do painel administrativo (pt-BR)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")
_EMPTY = "—"


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_datetime_br(value: Any) -> str:
    """Data/hora em dd/mm/aaaa HH:mm:ss (America/Sao_Paulo)."""
    dt = _parse_dt(value)
    if dt is None:
        return _EMPTY if value in (None, "") else str(value)
    return dt.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")


def format_date_br(value: Any) -> str:
    """Data em dd/mm/aaaa."""
    if value is None or value == "":
        return _EMPTY
    text = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    dt = _parse_dt(value)
    if dt is None:
        return text
    return dt.astimezone(BR_TZ).strftime("%d/%m/%Y")


def sanitize_source_path(path: Any) -> str:
    """Remove caminho absoluto de dev (Windows/Linux) do metadata."""
    if not path:
        return _EMPTY
    text = str(path).replace("\\", "/")
    for marker in ("/data/queimadas/", "data/queimadas/"):
        idx = text.find(marker)
        if idx >= 0:
            return text[idx:].lstrip("/")
    return text.split("/")[-1] if "/" in text else text
