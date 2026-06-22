"""Ingestao de focos de queimada do Programa Queimadas/INPE.

Estado atual: registra contrato operacional. Quando o endpoint definitivo for
confirmado, este script deve baixar pontos recentes, filtrar SP e salvar
GeoJSON/CSV em `data/queimadas/raw/focos_inpe/`.
"""

from __future__ import annotations

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
    ref_date = parse_date_arg("Baixa focos INPE para queimadas.")
    out_dir = (
        RAW_DIR / "focos_inpe" / ref_date.strftime("%Y")
        / ref_date.strftime("%m") / ref_date.strftime("%d")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "modulo": "queimadas",
        "step": "04_fetch_focos_inpe",
        "data_referencia": ref_date.isoformat(),
        "gerado_em": now_iso(),
        "source": "Programa Queimadas/INPE",
        "target_dir": str(out_dir),
        "status": "no_data",
        "message": (
            "Endpoint de focos INPE ainda nao configurado. O RF sera "
            "calculado sem correcao por focos ate haver dados reais."
        ),
        "files": [],
    }
    write_json(pipeline_status_path("focos_inpe", ref_date), status)
    print(status["message"])


if __name__ == "__main__":
    main()
