"""Correcao de texto UTF-8 corrompido (mojibake) em dados legados."""

from typing import Any


def fix_text(value: Any) -> Any:
    """Repara strings com double-encoding latin-1/utf-8."""
    if not isinstance(value, str):
        return value
    if not value:
        return value
    if "Ã" in value or "â€" in value or "\ufffd" in value:
        try:
            repaired = value.encode("latin-1").decode("utf-8")
            if repaired:
                return repaired
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    return value
