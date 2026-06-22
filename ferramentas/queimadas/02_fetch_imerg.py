"""Ingestao da precipitacao IMERG/GPM para o modulo de queimadas.

Estado atual: cria o contrato de ingest e registra `no_data` quando nao ha
credencial Earthdata/configuracao de download. O calculo RF nunca deve
inventar precipitacao.
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
    ref_date = parse_date_arg("Baixa IMERG/GPM diario para queimadas.")
    out_dir = RAW_DIR / "imerg" / ref_date.strftime("%Y") / ref_date.strftime("%m")
    out_dir.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("EARTHDATA_TOKEN")
    status = {
        "modulo": "queimadas",
        "step": "02_fetch_imerg",
        "data_referencia": ref_date.isoformat(),
        "gerado_em": now_iso(),
        "source": "IMERG/GPM",
        "target_dir": str(out_dir),
        "status": "no_data",
        "message": (
            "Download IMERG requer configuracao Earthdata. Defina "
            "EARTHDATA_TOKEN ou implemente .netrc antes do uso operacional."
        ),
        "earthdata_token_configured": bool(token),
        "files": [],
    }
    write_json(pipeline_status_path("imerg", ref_date), status)
    print(status["message"])


if __name__ == "__main__":
    main()
