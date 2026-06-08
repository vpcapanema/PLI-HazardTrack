"""
Atualiza estatisticas da malha rodoviaria oficial.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

csv_path = ROOT / "data" / "malha_der" / "malha_der_oficial.csv"
stats_path = ROOT / "static" / "data" / "malha_der_stats.json"


def _uniq(records, col):
    return sorted({r[col] for r in records if r.get(col)})


def _sum_float(records, col):
    total = 0.0
    for row in records:
        val = row.get(col)
        if not val:
            continue
        try:
            total += float(val)
        except ValueError:
            continue
    return total


if not csv_path.exists():
    print(f"CSV nao encontrado: {csv_path}")
    sys.exit(1)

with open(csv_path, encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

cols = rows[0].keys() if rows else []
rodovias = _uniq(rows, "Rodovia")
ext_km = _sum_float(rows, "Extensao") if "Extensao" in cols else 0.0
tipos_pista = _uniq(rows, "TipoPista") if "TipoPista" in cols else []
regionais = _uniq(rows, "CodRegiona") if "CodRegiona" in cols else []

stats = {
    "total_trechos": len(rows),
    "total_features": len(rows),
    "extensao_total_km": round(ext_km, 1),
    "rodovias_unicas": len(rodovias),
    "rodovias": rodovias,
    "tipos_pista": tipos_pista,
    "tipo_pista": tipos_pista,
    "regionais": regionais,
    "regional": regionais,
    "tipos_rodovia": _uniq(rows, "TipoRodovi") if "TipoRodovi" in cols else [],
    "municipios": _uniq(rows, "Municipio") if "Municipio" in cols else [],
    "administra": _uniq(rows, "Administra") if "Administra" in cols else [],
    "source": "DER-SP - Sistema Rodoviario Estadual (dadosabertos.sp.gov.br)",
    "crs": "EPSG:4326 (WGS84)",
    "data_atualizacao": "2025",
}

with open(stats_path, "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)

print(f"Estatisticas atualizadas: {stats_path}")
print(f"Total de trechos: {stats['total_features']}")
print(f"Rodovias: {stats['rodovias']}")
