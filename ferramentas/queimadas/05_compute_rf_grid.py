"""Baixa a grade oficial de Risco de Fogo (RF) do INPE.

O INPE ja publica RF observado e previsto em arquivos raster abertos. Este
script materializa esses produtos em `data/queimadas/interim/rf_inpe/` e
cria um indice consumido por `06_aggregate_to_der_segments.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

from common import ensure_dirs, now_iso, parse_date_arg, pipeline_status_path
from common import INTERIM_DIR, write_json, sha256

OBS_INDEX = (
    "https://dataserver-coids.inpe.br/queimadas/queimadas/"
    "riscofogo_meteorologia/observado/risco_fogo/"
)
PREV_BASE = (
    "https://dataserver-coids.inpe.br/queimadas/queimadas/"
    "riscofogo_meteorologia/previsto/risco_fogo/"
)


def main() -> None:
    ensure_dirs()
    ref_date = parse_date_arg("Baixa RF oficial INPE para queimadas.")
    out_dir = INTERIM_DIR / "rf_inpe" / ref_date.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    html = requests.get(OBS_INDEX, timeout=30).text
    observed_files = sorted(set(re.findall(
        r'href="(INPE_FireRiskModel_2\.2_FireRisk_\d{8}\.nc)"',
        html,
    )))
    if not observed_files:
        raise RuntimeError("Nenhum RF observado encontrado no diretorio INPE")

    products = []

    def _download(url: str, out: Path, horizonte: str) -> None:
        if not out.exists():
            with requests.get(url, stream=True, timeout=(10, 180)) as resp:
                resp.raise_for_status()
                with out.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
        products.append({
            "horizonte": horizonte,
            "path": str(out),
            "url": url,
            "bytes": out.stat().st_size,
            "sha256": sha256(out),
        })

    latest_obs = observed_files[-1]
    _download(OBS_INDEX + latest_obs, out_dir / latest_obs, "observado")

    # INPE publica T0..T3 no diretorio previsto. T0 e mantido para auditoria;
    # o produto publico usa observado + D+1..D+3.
    for step in range(4):
        name = f"RF.PREV.T{step}.tif"
        horizonte = "D+0" if step == 0 else f"D+{step}"
        _download(PREV_BASE + name, out_dir / name, horizonte)

    payload = {
        "modulo": "queimadas",
        "step": "05_compute_rf_grid",
        "data_referencia": ref_date.isoformat(),
        "gerado_em": now_iso(),
        "metodologia": "INPE-RF-v11",
        "status": "ok",
        "source": "INPE Programa Queimadas - RF oficial",
        "observed_source_file": latest_obs,
        "message": "Produtos RF oficiais INPE baixados.",
        "grid_products": products,
    }
    grid_status = out_dir / "rf_index.json"
    write_json(grid_status, payload)
    write_json(pipeline_status_path("rf_grid", ref_date), payload)
    print(payload["message"])


if __name__ == "__main__":
    main()
