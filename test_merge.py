"""Teste de leitura real do MERGE/INPE."""
from datetime import datetime, timedelta, timezone
from core.merge_inpe import download_hourly, _open_grib, _sample_at

# Pega arquivo de 6h atras (com folga para latencia de publicacao)
target = (datetime.now(timezone.utc) - timedelta(hours=6)).replace(minute=0, second=0, microsecond=0)
print(f"Baixando MERGE para {target.isoformat()}")

path = download_hourly(target)
if not path:
    print("FALHOU: arquivo nao baixou. Tentando dia anterior...")
    target = target - timedelta(days=1)
    path = download_hourly(target)

if path:
    print(f"OK: baixado em {path} ({path.stat().st_size} bytes)")
    print("Abrindo GRIB2 com cfgrib...")
    ds = _open_grib(path)
    print(f"Variaveis disponiveis: {list(ds.data_vars)}")
    print(f"Coords: {list(ds.coords)}")
    print(f"Lat range: {ds.latitude.min().values:.2f} -> {ds.latitude.max().values:.2f}")
    print(f"Lon range: {ds.longitude.min().values:.2f} -> {ds.longitude.max().values:.2f}")

    # Amostra em Sao Sebastiao (lat=-23.78, lon=-45.51)
    lat, lon = -23.78, -45.51
    val = _sample_at(ds, lat, lon)
    print(f"\nChuva em Sao Sebastiao ({lat}, {lon}) na hora {target.hour}h UTC: {val:.2f} mm")
    ds.close()
else:
    print("Sem dados disponiveis no INPE para este horario.")
