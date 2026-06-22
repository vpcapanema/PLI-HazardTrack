"""
Proxy e cache da API de cameras online DER-SP.

Upstream: http://200.144.30.103:8084/api/cameras
Streams HLS: /hls/cam_{id}/stream.m3u8
"""
from __future__ import annotations

import logging
import os
import re
import time
from threading import Lock
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

log = logging.getLogger("der_cameras")

DER_CAMERAS_URL = os.environ.get(
    "DER_CAMERAS_URL", "http://200.144.30.103:8084",
).rstrip("/")
CACHE_TTL_S = int(os.environ.get("DER_CAMERAS_CACHE_TTL", "300"))
HTTP_TIMEOUT = (8, 20)
HLS_CHUNK = 65536
_HLS_PATH_RE = re.compile(r"^cam_\d+/.+$")


class _MemCache:
    """Cache em memoria mutavel (evita `global` no fetch)."""

    __slots__ = ("at", "cameras")

    def __init__(self) -> None:
        self.at = 0.0
        self.cameras: List[Dict[str, Any]] = []


_cache_lock = Lock()
_CACHE = _MemCache()


def normalize_camera(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza registro upstream para o frontend."""
    cid = raw.get("id")
    rod = str(raw.get("rodovia") or "").strip()
    km = str(raw.get("km") or "").strip()
    try:
        status = int(raw.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    label = f"{rod} · {km}".strip(" ·") if (rod or km) else str(
        raw.get("nome") or f"Câmera {cid}",
    )
    return {
        "id": cid,
        "rodovia": rod,
        "km": km,
        "nome": str(raw.get("nome") or "").strip(),
        "local": str(raw.get("local") or "").strip(),
        "lat": float(raw.get("lat") or 0),
        "lng": float(raw.get("lng") or 0),
        "status": status,
        "sentido": str(raw.get("sentido") or "").strip(),
        "label": label,
        "stream_path": f"cam_{cid}/stream.m3u8",
        "maintenance": status == 2,
        "online": status == 1,
    }


def validate_hls_path(subpath: str) -> Optional[str]:
    """Valida subpath do proxy HLS (sem traversal)."""
    if not subpath or ".." in subpath or subpath.startswith("/"):
        return None
    if not _HLS_PATH_RE.match(subpath):
        return None
    return subpath


def fetch_cameras(force: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
    """Lista cameras com cache em memoria (TTL configuravel)."""
    now = time.time()
    with _cache_lock:
        if (
            not force
            and _CACHE.cameras
            and (now - _CACHE.at) < CACHE_TTL_S
        ):
            return list(_CACHE.cameras), True

    url = f"{DER_CAMERAS_URL}/api/cameras"
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        log.warning("DER cameras fetch falhou (%s): %s", url, exc)
        with _cache_lock:
            if _CACHE.cameras:
                return list(_CACHE.cameras), True
        raise

    if not isinstance(data, list):
        raise ValueError("resposta DER cameras nao e array")

    cameras = [
        normalize_camera(item)
        for item in data
        if isinstance(item, dict) and item.get("id") is not None
    ]
    cameras.sort(key=lambda c: (c.get("rodovia") or "", c.get("km") or ""))

    with _cache_lock:
        _CACHE.cameras = cameras
        _CACHE.at = now

    log.info("DER cameras: %d registros (cache TTL=%ds)", len(cameras), CACHE_TTL_S)
    return cameras, False


def hls_upstream_url(subpath: str) -> str:
    return f"{DER_CAMERAS_URL}/hls/{subpath}"


def hls_cache_control(subpath: str) -> str:
    if subpath.endswith(".m3u8"):
        return "max-age=1"
    if subpath.endswith(".ts"):
        return "max-age=2"
    return "max-age=1"


def fetch_hls(
    subpath: str,
) -> Tuple[Optional[bytes], Optional[Iterator[bytes]], str, int]:
    """Busca recurso HLS upstream.

    m3u8: retorna bytes completos (manifest pequeno, parse confiavel).
    ts: retorna iterator em streaming.
    """
    url = hls_upstream_url(subpath)
    is_manifest = subpath.endswith(".m3u8")
    resp = requests.get(
        url,
        timeout=HTTP_TIMEOUT,
        stream=not is_manifest,
    )
    if resp.status_code != 200:
        resp.close()
        return None, None, "text/plain", resp.status_code

    ctype = resp.headers.get("Content-Type") or (
        "application/vnd.apple.mpegurl"
        if is_manifest
        else "video/mp2t"
    )

    if is_manifest:
        body = resp.content
        resp.close()
        return body, None, ctype, 200

    def _iter() -> Iterator[bytes]:
        try:
            for chunk in resp.iter_content(chunk_size=HLS_CHUNK):
                if chunk:
                    yield chunk
        finally:
            resp.close()

    return None, _iter(), ctype, 200


def stream_hls(subpath: str) -> Tuple[Iterator[bytes], str, int]:
    """Abre stream HTTP do upstream HLS. Retorna (iter, content_type, status)."""
    _, body_iter, ctype, status = fetch_hls(subpath)
    if status != 200 or body_iter is None:
        return iter(()), ctype, status
    return body_iter, ctype, status
