"""
Datas sugeridas para consulta historica (eventos com alerta elevado).

Fonte: validacao documentada no projeto (README, test_merge backtest)
e literatura REGEA-NIPPON / desastre de Sao Sebastiao (fev/2023).
"""

from __future__ import annotations

from typing import Any, Dict, List

# at_utc: instante de referencia da consulta (hora civil UTC).
# O backend aplica lag de publicacao MERGE via _target_hour_for(as_of).
DEMO_HISTORY_EVENTS: List[Dict[str, Any]] = [
    {
        "id": "ssa-2023-pico",
        "at_utc": "2023-02-19T12:00:00+00:00",
        "label": "19 fev 2023 · pico",
        "region": "Sao Sebastiao / Litoral Norte",
        "max_level": 4,
        "level_label": "Alerta maximo",
        "note": (
            "Ciclone extratropical. Backtest oficial do sistema: "
            "Juquehy RD4, Camburi RD3, Maresias RD1."
        ),
        "source": "README · validacao REGEA-NIPPON",
    },
    {
        "id": "ssa-2023-madrugada",
        "at_utc": "2023-02-19T06:00:00+00:00",
        "label": "19 fev 2023 · madrugada",
        "region": "Sao Sebastiao / Litoral Norte",
        "max_level": 4,
        "level_label": "Alerta maximo",
        "note": (
            "Mesmo evento, fase de acumulo intenso antes do pico diurno."
        ),
        "source": "MERGE/INPE · arquivo historico",
    },
    {
        "id": "ssa-2023-vespera",
        "at_utc": "2023-02-18T18:00:00+00:00",
        "label": "18 fev 2023 · vespera",
        "region": "Sao Sebastiao / Litoral Norte",
        "max_level": 3,
        "level_label": "Alerta",
        "note": (
            "Precede o pico de 19/02; util para ver escalada do RD "
            "hora a hora (Linha do Tempo)."
        ),
        "source": "MERGE/INPE · arquivo historico",
    },
]


def get_history_hints() -> Dict[str, Any]:
    """Lista de datas sugeridas para a UI de consulta historica."""
    return {
        "events": list(DEMO_HISTORY_EVENTS),
        "disclaimer": (
            "Sugestoes com chuva MERGE/INPE disponivel no arquivo do INPE. "
            "RD recalculado na hora (observado, sem WRF)."
        ),
    }
