"""
Smoke test do MERGE/INPE em streaming.

Usa data historica (19/02/2023 - evento de Sao Sebastiao) que sempre tem
dado disponivel no arquivo do INPE, evitando falhas por latencia recente.
"""
from datetime import datetime, timezone
from core.merge_inpe import fetch_real_batch, _eccodes_available


def main():
    if not _eccodes_available():
        raise SystemExit("eccodes nativo nao encontrado. Rode: pip install -U eccodes")

    # 19/02/2023 12:00 UTC - dia do desastre de Sao Sebastiao (litoral norte SP)
    t = datetime(2023, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    points = [
        (-23.745, -45.430),  # Maresias
        (-23.785, -45.510),  # Camburi
        (-23.810, -45.600),  # Juquehy
    ]

    print(f"Backtest MERGE/INPE em {t.isoformat()} para {len(points)} pontos")
    res = fetch_real_batch(points, now_utc=t, hours_back=96)

    if not res:
        raise SystemExit("Nenhum GRIB foi lido. Verifique a rede ate o ftp.cptec.inpe.br")

    info = res[0]
    print(f"  files_ok = {info.files_ok}/96")
    print(f"  faltando = {info.missing_24h}h em 24h, {info.missing_96h}h em 96h")
    for r in res:
        print(f"  ({r.lat}, {r.lon}) -> 1h={r.intensity_mmh}mm, "
              f"24h={r.ac24h_mm}mm, 96h={r.ac96h_mm}mm")


if __name__ == "__main__":
    main()
