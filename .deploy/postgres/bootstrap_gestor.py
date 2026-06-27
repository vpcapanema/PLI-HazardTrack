#!/usr/bin/env python3
"""Cria gestor inicial se usuarios.usuario estiver vazio (instalacao nova)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import argon2
import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.sigma_auth import GESTOR_PROFILE, sigma_database_dsn  # noqa: E402


def main() -> int:
    dsn = sigma_database_dsn()
    if not dsn:
        print("skip: SIGMA DB nao configurado")
        return 0

    user = os.environ.get("ADMIN_USER", "").strip()
    pwd = os.environ.get("ADMIN_PASS", "").strip()
    if not user or not pwd:
        print("skip: ADMIN_USER/ADMIN_PASS ausentes (sem seed local)")
        return 0

    hasher = argon2.PasswordHasher(memory_cost=32768, time_cost=2, parallelism=2)
    pwd_hash = hasher.hash(pwd)

    with psycopg.connect(dsn, connect_timeout=8) as conn:
        row = conn.execute(
            """
            SELECT count(*)::int
            FROM usuarios.usuario
            WHERE UPPER(tipo_usuario) = %s AND ativo = true
            """,
            (GESTOR_PROFILE,),
        ).fetchone()
        if row and row[0] > 0:
            print(f"ok: {row[0]} gestor(es) ja existem")
            return 0

        conn.execute(
            """
            INSERT INTO usuarios.usuario (
                username, email_institucional, password_hash,
                tipo_usuario, ativo
            ) VALUES (%s, %s, %s, %s, true)
            """,
            (user, None, pwd_hash, GESTOR_PROFILE),
        )
        conn.commit()
        print(f"ok: gestor inicial criado ({user})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
