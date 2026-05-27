"""Teste de leitura real do MERGE/INPE em streaming (sem disco)."""
from datetime import datetime, timedelta, timezone
from core.merge_inpe import fetch_real_batch, fetch_mock

# Pontos de exemplo (Sao Sebastiao e Caraguatatuba)
points = [(-23.78, -45.51), (-23.62, -45.43)]

print("Buscando MERGE/INPE em streaming (96h, paralelo)...")
res = fetch_real_batch(points)

if res:
    for s in res:
        print(f"  ({s.lat}, {s.lon}) -> 1h={s.intensity_mmh}mm, "
              f"24h={s.ac24h_mm}mm, 96h={s.ac96h_mm}mm "
              f"@ {s.timestamp_utc} [{s.source}]")
else:
    print("eccodes indisponivel ou sem arquivos. Mock:")
    for lat, lon in points:
        m = fetch_mock(lat, lon)
        print(f"  ({m.lat}, {m.lon}) -> {m.ac24h_mm}mm/24h, {m.ac96h_mm}mm/96h [{m.source}]")
