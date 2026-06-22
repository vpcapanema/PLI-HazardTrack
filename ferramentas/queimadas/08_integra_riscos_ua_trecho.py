"""Integra o risco por UA (movimento de massa / inundacao) na malha base.

A malha de trechos DER (`data/queimadas/base/trechos_der_sp.gpkg`, layer
`trechos`) eh ~30-130x mais grossa que as Unidades de Analise (UAs) do
PRODUTO 7. Em vez de COLAPSAR as UAs (o que destruiria a granularidade das
SRs 1:1.000), este script transforma a malha em um HUB integrador:

- Cada UA eh atribuida a UM trecho (centroide oficial da UA -> trecho mais
  proximo na MESMA rodovia, dentro de uma tolerancia).
- Para cada trecho gravamos:
    * resumo (pior caso): `ra_geo_max`, `ra_hid_max`, `trecho_critico_geo`,
      `trecho_critico_hid`, `n_uas`;
    * a LISTA das UAs vinculadas (`ua_ids`) e o detalhe por UA com seus RAs
      e thresholds (`uas_risco`, JSON), preservando todo o detalhe fino.
- Um crosswalk relacional `ua_trecho_crosswalk` (1 linha por UA) eh gravado
  na mesma gpkg base para joins externos.

Como o RA eh ESTATICO, gravamos na malha base: o pipeline diario de
queimadas (06 -> 07) le essa base via `load_trechos()` e propaga os campos
para `malha_rodoviaria_estadual_monitorada` e exports publicos
automaticamente, sem alteracao no pipeline.

O Risco Dinamico (RD = RA x ICC) NAO eh gravado aqui: ele depende da chuva
e continua sendo calculado ao vivo pelo backend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from common import BASE_DIR, ROOT, TRECHOS_GPKG

UAS_GPKG = ROOT / "data" / "pli-hazardtrack.gpkg"
UAS_LAYER = "uas_area_estudo"
TRECHOS_LAYER = "trechos"
CROSSWALK_LAYER = "ua_trecho_crosswalk"

# CRS metrico para distancias (SIRGAS 2000 / UTM 23S - Litoral Norte SP).
METRIC_CRS = "EPSG:31983"
# Tolerancia de atribuicao centroide-da-UA -> eixo do trecho (metros).
MAX_DIST_M = 1500.0

# Colunas adicionadas por este script (removidas antes de recomputar).
NEW_COLS = [
    "n_uas", "ra_geo_max", "ra_hid_max",
    "trecho_critico_geo", "trecho_critico_hid",
    "ua_ids", "uas_risco",
]


def _norm_sigla(value: str) -> str:
    """Normaliza 'SP 098' / 'SP-098' -> 'SP-098'."""
    return str(value).strip().upper().replace(" ", "-")


def _as_int(value):
    try:
        if pd.isna(value):
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_bool(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "1.0", "t", "yes"}


def _load_uas() -> gpd.GeoDataFrame:
    if not UAS_GPKG.exists():
        raise FileNotFoundError(f"Camada-mae de UAs ausente: {UAS_GPKG}")
    uas = gpd.read_file(UAS_GPKG, layer=UAS_LAYER).to_crs("EPSG:4326")
    uas["sigla_norm"] = uas["sigla_rodovia"].map(_norm_sigla)
    uas["RAGEO"] = uas["RAGEO"].map(_as_int)
    uas["RAHID"] = uas["RAHID"].map(_as_int)
    uas["trecho_critico_geo"] = uas["trecho_critico_geo"].map(_as_bool)
    uas["trecho_critico_hid"] = uas["trecho_critico_hid"].map(_as_bool)
    return uas


def _ua_points(uas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Pontos a partir dos centroides oficiais (centroide_lon/lat)."""
    pts = gpd.GeoDataFrame(
        uas.drop(columns="geometry"),
        geometry=gpd.points_from_xy(
            uas["centroide_lon"].astype(float),
            uas["centroide_lat"].astype(float),
        ),
        crs="EPSG:4326",
    )
    return pts.to_crs(METRIC_CRS)


def _assign_ua_to_trecho(
    ua_pts: gpd.GeoDataFrame, trechos_m: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Para cada UA, o trecho mais proximo na MESMA rodovia (<= MAX_DIST_M)."""
    matches = []
    for sig in sorted(ua_pts["sigla_norm"].dropna().unique()):
        left = ua_pts[ua_pts["sigla_norm"] == sig]
        right = trechos_m[trechos_m["sigla_norm"] == sig][
            ["trecho_id", "geometry"]
        ]
        if left.empty or right.empty:
            continue
        joined = gpd.sjoin_nearest(
            left, right, how="left",
            max_distance=MAX_DIST_M, distance_col="dist_m",
        )
        matches.append(joined)
    if not matches:
        return pd.DataFrame(columns=["ua_id", "trecho_id", "dist_m"])
    out = pd.concat(matches, ignore_index=True)
    # sjoin_nearest pode duplicar em empates: mantem o mais proximo por UA.
    out = out.sort_values("dist_m").drop_duplicates("ua_id", keep="first")
    return out


def _ua_record(row: pd.Series) -> dict:
    return {
        "ua_id": row["ua_id"],
        "RAGEO": _as_int(row["RAGEO"]),
        "RAHID": _as_int(row["RAHID"]),
        "km_inicial": _as_float(row.get("km_inicial")),
        "km_final": _as_float(row.get("km_final")),
        "tipo": row.get("tipo"),
        "escala": row.get("escala"),
        "icc_geo_thresholds": row.get("icc_geo_thresholds"),
        "icc_hid_thresholds": row.get("icc_hid_thresholds"),
        "trecho_critico_geo": bool(row.get("trecho_critico_geo")),
        "trecho_critico_hid": bool(row.get("trecho_critico_hid")),
    }


def _as_float(value):
    try:
        if pd.isna(value):
            return None
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _max_ignore_none(values):
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def _aggregate(uas: gpd.GeoDataFrame, assign: pd.DataFrame) -> pd.DataFrame:
    """Resumo + listas por trecho_id."""
    merged = uas.drop(columns="geometry").merge(
        assign[["ua_id", "trecho_id", "dist_m"]], on="ua_id", how="inner",
    )
    merged = merged[merged["trecho_id"].notna()]
    rows = []
    for trecho_id, grp in merged.groupby("trecho_id"):
        grp = grp.sort_values("km_inicial")
        detail = [_ua_record(r) for _, r in grp.iterrows()]
        rows.append({
            "trecho_id": trecho_id,
            "n_uas": int(len(grp)),
            "ra_geo_max": _max_ignore_none(grp["RAGEO"].tolist()),
            "ra_hid_max": _max_ignore_none(grp["RAHID"].tolist()),
            "trecho_critico_geo": bool(grp["trecho_critico_geo"].any()),
            "trecho_critico_hid": bool(grp["trecho_critico_hid"].any()),
            "ua_ids": json.dumps(
                grp["ua_id"].tolist(), ensure_ascii=False,
            ),
            "uas_risco": json.dumps(detail, ensure_ascii=False),
        })
    return pd.DataFrame(rows)


def _build_crosswalk(
    uas: gpd.GeoDataFrame, assign: pd.DataFrame,
) -> gpd.GeoDataFrame:
    cols = [
        "ua_id", "sigla_rodovia", "regiao_id", "municipio",
        "km_inicial", "km_final", "RAGEO", "RAHID",
        "trecho_critico_geo", "trecho_critico_hid", "geometry",
    ]
    base = uas[cols].merge(
        assign[["ua_id", "trecho_id", "dist_m"]], on="ua_id", how="left",
    )
    base["dist_m"] = base["dist_m"].round(1)
    return gpd.GeoDataFrame(base, geometry="geometry", crs=uas.crs)


def main() -> None:
    print("Lendo malha base e UAs...")
    trechos = gpd.read_file(TRECHOS_GPKG, layer=TRECHOS_LAYER)
    trechos = trechos.drop(
        columns=[c for c in NEW_COLS if c in trechos.columns],
    )
    trechos["sigla_norm"] = trechos["rodovia"].map(_norm_sigla)

    uas = _load_uas()
    ua_pts = _ua_points(uas)
    trechos_m = trechos.to_crs(METRIC_CRS)

    print("Atribuindo UAs aos trechos (mesma rodovia, nearest)...")
    assign = _assign_ua_to_trecho(ua_pts, trechos_m)
    n_assigned = int(assign["trecho_id"].notna().sum())
    n_orphan = int(len(uas) - n_assigned)
    print(f"  UAs atribuidas: {n_assigned} | sem trecho proximo: {n_orphan}")

    summary = _aggregate(uas, assign)
    print(f"  trechos com >=1 UA: {len(summary)}")

    out = trechos.merge(summary, on="trecho_id", how="left")
    out["n_uas"] = out["n_uas"].fillna(0).astype(int)
    for col in ("trecho_critico_geo", "trecho_critico_hid"):
        out[col] = out[col].fillna(False).astype(bool)
    for col in ("ra_geo_max", "ra_hid_max"):
        out[col] = out[col].astype("Int64")
    out["ua_ids"] = out["ua_ids"].fillna("[]")
    out["uas_risco"] = out["uas_risco"].fillna("[]")
    out = out.drop(columns=["sigla_norm"])

    crosswalk = _build_crosswalk(uas, assign)

    print("Gravando malha base enriquecida + crosswalk...")
    tmp = BASE_DIR / "trechos_der_sp.gpkg.tmp"
    if tmp.exists():
        tmp.unlink()
    out.to_file(tmp, layer=TRECHOS_LAYER, driver="GPKG")
    crosswalk.to_file(tmp, layer=CROSSWALK_LAYER, driver="GPKG", mode="a")
    os.replace(tmp, TRECHOS_GPKG)

    cobertura = int((out["n_uas"] > 0).sum())
    print(
        f"OK: {len(out)} trechos | {cobertura} com monitoramento de UA | "
        f"ra_geo_max!=NA: {int(out['ra_geo_max'].notna().sum())} | "
        f"crosswalk: {len(crosswalk)} UAs -> {CROSSWALK_LAYER}"
    )


if __name__ == "__main__":
    main()
