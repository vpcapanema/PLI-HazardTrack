"""
Inspeciona cientificamente um GRIB2 do MERGE/INPE usando ecCodes.

Objetivo:
  - descobrir qual variável/“significado” numérico está no GRIB2 (unidade,
    stepType, stepRange etc.)
  - validar se o backend deve tratar o valor como mm/h (intensidade instantânea)
    ou como precipitação acumulada em um intervalo específico.

Uso:
  python scripts/inspect_merge_grib_field.py --dt 2026-06-04T00:00:00Z
  python scripts/inspect_merge_grib_field.py --now-utc

Observação:
  Este script depende de `eccodes` estar instalado no ambiente Python.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Any, Dict, Iterable, List, Optional

import requests


INPE_BASE = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM"
HTTP_TIMEOUT = (10, 60)  # (connect, read)


def _hourly_url(dt_utc: dt.datetime) -> str:
    return (
        f"{INPE_BASE}/HOURLY/{dt_utc.year:04d}/{dt_utc.month:02d}/{dt_utc.day:02d}/"
        f"MERGE_CPTEC_{dt_utc.year:04d}{dt_utc.month:02d}{dt_utc.day:02d}{dt_utc.hour:02d}.grib2"
    )


def _parse_iso(s: str) -> dt.datetime:
    # Aceita "2026-06-04T00:00:00Z" e "2026-06-04T00:00:00+00:00"
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _safe_get(gid: Any, keys: Iterable[str]) -> Dict[str, Any]:
    import eccodes

    out: Dict[str, Any] = {}
    for k in keys:
        try:
            out[k] = eccodes.codes_get(gid, k)
        except Exception:
            # Nem toda chave existe para todo template de GRIB.
            pass
    return out


def _sample_nearest(gid: Any, lat: float, lon: float) -> float:
    import eccodes

    lons_360 = lon + 360.0 if lon < 0 else lon
    nearest = eccodes.codes_grib_find_nearest(gid, lat, lons_360)
    # Em ecCodes Python, o retorno pode ser uma lista/tuple ou um objeto;
    # aqui mantemos compatível com o uso já existente no backend.
    first = nearest[0] if isinstance(nearest, (list, tuple)) else nearest
    value = getattr(first, "value", first)
    return float(value)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dt", dest="dt_iso", type=str, default=None, help="ISO datetime em UTC (ex: 2026-06-04T00:00:00Z)")
    parser.add_argument("--now-utc", action="store_true", help="Usa o horário atual UTC como referência")
    parser.add_argument("--sample-lat", type=float, default=-23.5)
    parser.add_argument("--sample-lon", type=float, default=-46.6)
    args = parser.parse_args(argv)

    if args.now_utc:
        dt_utc = dt.datetime.now(dt.timezone.utc)
        dt_utc = dt_utc.replace(minute=0, second=0, microsecond=0)
    elif args.dt_iso:
        dt_utc = _parse_iso(args.dt_iso)
        dt_utc = dt_utc.replace(minute=0, second=0, microsecond=0)
    else:
        dt_utc = dt.datetime.now(dt.timezone.utc)
        dt_utc = dt_utc.replace(minute=0, second=0, microsecond=0)

    url = _hourly_url(dt_utc)
    print(f"[merge-inspect] dt_utc={dt_utc.isoformat()}")
    print(f"[merge-inspect] url={url}")

    r = requests.get(url, timeout=HTTP_TIMEOUT)
    if r.status_code != 200 or len(r.content) < 1000:
        raise SystemExit(f"Falha ao baixar GRIB: HTTP {r.status_code}, bytes={len(r.content)}")

    import eccodes

    gid = eccodes.codes_new_from_message(r.content)
    if gid is None:
        raise SystemExit("eccodes.codes_new_from_message retornou None")

    try:
        # Chaves que costumam esclarecer unidade e intervalo.
        keys = [
            "shortName",
            "name",
            "units",
            "paramId",
            "indicatorOfParameter",
            "typeOfLevel",
            "level",
            "gridType",
            "packingType",
            "bitsPerValue",
            "stepType",
            "stepRange",
            "forecastTime",
            "endStep",
            "startStep",
            "validityDate",
            "validityTime",
            "dataDate",
            "dataTime",
            "generatingProcessIdentifier",
            "productDefinitionTemplateNumber",
        ]

        meta = _safe_get(gid, keys)
        print("\n[merge-inspect] metadados (subset de chaves):")
        for k in sorted(meta.keys()):
            print(f"  {k}: {meta[k]}")

        v = _sample_nearest(gid, lat=args.sample_lat, lon=args.sample_lon)
        print("\n[merge-inspect] amostra em ponto próximo:")
        print(f"  lat={args.sample_lat} lon={args.sample_lon}")
        print(f"  value_nearest={v}")

        # Dica: se stepType==accum e stepRange ~= 0-1, o valor pode representar mm acumulados
        # naquele intervalo (que pode equivaler a mm/h se o intervalo for 1h). Se stepType for
        # something diferente, a interpretação precisa mudar.
        step_type = meta.get("stepType")
        step_range = meta.get("stepRange")
        units = meta.get("units")
        print("\n[merge-inspect] interpretação preliminar (pela metainfo):")
        print(f"  stepType={step_type} stepRange={step_range} units={units}")

    finally:
        eccodes.codes_release(gid)

    return 0


if __name__ == "__main__":
    sys.exit(main())

