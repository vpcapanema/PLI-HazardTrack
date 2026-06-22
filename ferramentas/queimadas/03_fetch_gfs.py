"""Ingestao GFS para temperatura, umidade e previsao D+1..D+5.

Estado atual: registra o contrato operacional e `no_data` ate a rotina GRIB2
ser conectada ao NOMADS/AWS. O modulo nao calcula previsao sem GFS real.
"""

from __future__ import annotations

import os

from common import (
    RAW_DIR,
    ensure_dirs,
    now_iso,
    parse_date_arg,
    pipeline_status_path,
    write_json,
)


def main() -> None:
    ensure_dirs()
    ref_date = parse_date_arg("Baixa GFS para risco de queimadas.")
    cycle = os.environ.get("QUEIMADAS_GFS_CYCLE", "00")
    out_dir = (
        RAW_DIR / "gfs" / ref_date.strftime("%Y")
        / ref_date.strftime("%m") / ref_date.strftime("%d")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "modulo": "queimadas",
        "step": "03_fetch_gfs",
        "data_referencia": ref_date.isoformat(),
        "gerado_em": now_iso(),
        "source": "GFS/NOAA",
        "cycle": cycle,
        "target_dir": str(out_dir),
        "status": "no_data",
        "message": (
            "Rotina GFS ainda nao conectada. Implementar download GRIB2 "
            "NOMADS/AWS para Tmax, URmin e precipitacao D+1..D+5."
        ),
        "files": [],
    }
    write_json(pipeline_status_path("gfs", ref_date), status)
    print(status["message"])


if __name__ == "__main__":
    main()
