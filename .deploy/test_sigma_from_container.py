"""Testa conexao SIGMA a partir do container (usa variaveis de ambiente)."""
from __future__ import annotations

import os
import sys

import psycopg


def main() -> int:
    host = os.environ.get("SIGMA_POSTGRES_HOST", "pli-hazardtrack-db")
    port = os.environ.get("SIGMA_POSTGRES_PORT", "5432")
    db = os.environ.get("SIGMA_POSTGRES_DATABASE", "pli_hazzardtracker_db")
    user = os.environ.get("SIGMA_POSTGRES_USER", "sigma_user")
    password = os.environ.get("SIGMA_POSTGRES_PASSWORD", "")
    if not password:
        print("ERRO: SIGMA_POSTGRES_PASSWORD nao definida")
        return 1
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=db,
            user=user,
            password=password,
            connect_timeout=8,
        )
        conn.close()
        print(f"OK {host}:{port}/{db}")
        return 0
    except Exception as exc:
        print(f"ERRO {host}:{port}/{db}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
