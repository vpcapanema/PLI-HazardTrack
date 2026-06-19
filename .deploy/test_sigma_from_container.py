#!/usr/bin/env python3
import os
import sys

os.environ.setdefault("SIGMA_POSTGRES_HOST", "host.docker.internal")
os.environ.setdefault("SIGMA_POSTGRES_PORT", "5433")
os.environ.setdefault("SIGMA_POSTGRES_DATABASE", "sigma_pli_qr53")
os.environ.setdefault("SIGMA_POSTGRES_USER", "sigma_user")
os.environ.setdefault("SIGMA_POSTGRES_PASSWORD", "Malditas131533***")
os.environ.setdefault("SIGMA_POSTGRES_SSLMODE", "disable")

import psycopg

for host in ("host.docker.internal", "172.17.0.1", "56.125.163.194"):
    try:
        conn = psycopg.connect(
            host=host,
            port=5433,
            dbname="sigma_pli_qr53",
            user="sigma_user",
            password="Malditas131533***",
            connect_timeout=5,
        )
        conn.close()
        print("OK", host)
        sys.exit(0)
    except Exception as exc:
        print("FAIL", host, str(exc)[:80])

sys.exit(1)
