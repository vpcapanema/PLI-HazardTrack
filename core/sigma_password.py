"""Verificacao de senhas compativel com SIGMA-PLI."""
from __future__ import annotations

import hashlib
import secrets

import argon2

_argon2_hasher = argon2.PasswordHasher(
    memory_cost=32768,
    time_cost=2,
    parallelism=2,
)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    if not hashed_password:
        return False

    if hashed_password.startswith("sha256:"):
        return _verify_sha256_with_salt(plain_password, hashed_password)

    if hashed_password.startswith("$argon2"):
        try:
            _argon2_hasher.verify(hashed_password, plain_password)
            return True
        except Exception:
            return False

    if hashed_password.startswith("$2"):
        try:
            import bcrypt

            password_bytes = plain_password.encode("utf-8")[:72]
            hash_bytes = hashed_password.encode("utf-8")
            return bcrypt.checkpw(password_bytes, hash_bytes)
        except Exception:
            return False

    if len(hashed_password) == 64:
        computed = hashlib.sha256(plain_password.encode()).hexdigest()
        return secrets.compare_digest(computed, hashed_password)

    return False


def _verify_sha256_with_salt(password: str, stored_hash: str) -> bool:
    try:
        parts = stored_hash.split(":")
        if len(parts) != 3:
            return False
        _, salt, hash_value = parts
        computed = hashlib.sha256((password + salt).encode()).hexdigest()
        return secrets.compare_digest(computed, hash_value)
    except Exception:
        return False
