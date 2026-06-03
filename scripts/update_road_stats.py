"""
Atualiza estatisticas da malha rodoviaria oficial.
"""

import json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

csv_path = ROOT / "data" / "malha_der" / "malha_der_oficial.csv"
stats_path = ROOT / "static" / "data" / "malha_der_stats.json"

if not csv_path.exists():
    print(f"CSV nao encontrado: {csv_path}")
    exit(1)

df = pd.read_csv(csv_path)

stats = {
    "total_features": len(df),
    "rodovias": sorted(df['Rodovia'].unique().tolist()),
    "tipos_rodovia": sorted(df['TipoRodovi'].dropna().unique().tolist()) if 'TipoRodovi' in df.columns else [],
    "municipios": sorted(df['Municipio'].dropna().unique().tolist()) if 'Municipio' in df.columns else [],
    "regional": sorted(df['CodRegiona'].dropna().unique().tolist()) if 'CodRegiona' in df.columns else [],
    "administra": sorted(df['Administra'].dropna().unique().tolist()) if 'Administra' in df.columns else [],
    "tipo_pista": sorted(df['TipoPista'].dropna().unique().tolist()) if 'TipoPista' in df.columns else [],
    "source": "DER-SP - Sistema Rodoviario Estadual (dadosabertos.sp.gov.br)",
    "crs": "EPSG:4326 (WGS84)",
    "data_atualizacao": "2025"
}

with open(stats_path, 'w', encoding='utf-8') as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)

print(f"Estatisticas atualizadas: {stats_path}")
print(f"Total de trechos: {stats['total_features']}")
print(f"Rodovias: {stats['rodovias']}")
