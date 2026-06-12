"""
Ingestao MERGE/CPTEC/INPE com cache incremental e decode paralelo.

Estrategia:
- Download HTTP paralelo (ThreadPoolExecutor, SAMAEG_WORKERS)
- Decode eccodes em ProcessPoolExecutor (SAMAEG_DECODE_WORKERS)
- Cache RAM gerenciado por core/merge_ingest.py (ingest continuo)
- Ciclos seguintes baixam so horas novas ou recentes (republicacao INPE)

Estrutura no servidor INPE:
    https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/HOURLY/AAAA/MM/DD/...

Sem dado real -> aggregator marca NO_DATA; nunca mock operacional.
"""

from __future__ import annotations

from concurrent.futures import (
    ThreadPoolExecutor,
    ProcessPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import logging
import os
import requests
from requests.adapters import HTTPAdapter
from threading import Lock

log = logging.getLogger("merge_inpe")

INPE_BASE = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM"
PUBLISH_LAG_HOURS = 3
HTTP_TIMEOUT = (10, 60)         # (connect, read)
# Downloads HTTP em paralelo. Ajuste via SAMAEG_WORKERS (padrao 12).
DEFAULT_WORKERS = int(os.environ.get("SAMAEG_WORKERS", "12"))
# Decode eccodes em processos separados (lib nao e thread-safe).
DEFAULT_DECODE_WORKERS = int(
    os.environ.get("SAMAEG_DECODE_WORKERS", "6")
)
# Re-tentativas por GRIB que falhou (alem da 1a tentativa).
MAX_GRIB_RETRIES = int(os.environ.get("SAMAEG_GRIB_RETRIES", "2"))

# Progresso de download em tempo real (lido pela UI no primeiro ciclo).
# Reflete o batch de GRIBs em andamento, arquivo a arquivo.
_PROGRESS_LOCK = Lock()
_PROGRESS: dict = {
    "active": False,
    "total": 0,
    "done": 0,
    "ok": 0,
    "fail": 0,
    "target": None,
    "started_at": None,
    "files": [],
    "_index": {},
    "phase": "idle",
    "stage": None,
    "workers": DEFAULT_WORKERS,
    "decode_workers": DEFAULT_DECODE_WORKERS,
    "hours_back": 96,
    "min_ok_hours": 24,
    "batch_kind": "idle",
}

# Etapas do ciclo com mensagens amistosas, na ordem de execucao. A UI usa
# isto para descrever o que o servidor esta fazendo apos o download.
_STAGE_ORDER = ["download", "aggregate", "forecast", "risk", "publish"]
_STAGE_LABELS = {
    "download": "Chuva MERGE/INPE recebida",
    "aggregate": "Cruzando chuva com as 809 unidades de an\u00e1lise",
    "forecast": "Incorporando previs\u00e3o hor\u00e1ria WRF (CPTEC)",
    "risk": "Calculando risco din\u00e2mico (metodologia DER-SP)",
    "publish": "Atualizando mapa e painel de alertas",
}


def _progress_start_ingest_batch(
    target_hour: datetime,
    hours: list,
    *,
    hours_back: int = 96,
    hours_cached_ok: int = 0,
    min_ok_hours: int = 24,
    batch_kind: str = "full",
    workers: int = DEFAULT_WORKERS,
    decode_workers: int = DEFAULT_DECODE_WORKERS,
) -> None:
    """Inicializa progresso do batch atual (full=96h ou incremental)."""
    files = []
    for h, dt in hours:
        files.append({
            "h": h,
            "ts": dt.isoformat(),
            "name": _hourly_url(dt).rsplit("/", 1)[-1],
            "status": "pending",
            "pct": 0,
            "bytes_done": 0,
            "bytes_total": None,
        })
    files.sort(key=lambda f: f["h"])
    with _PROGRESS_LOCK:
        _PROGRESS.update({
            "active": True,
            "total": len(files),
            "done": 0,
            "ok": 0,
            "fail": 0,
            "target": target_hour.isoformat(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
            "_index": {f["h"]: f for f in files},
            "phase": "ingest",
            "stage": "download",
            "workers": max(1, workers),
            "decode_workers": max(1, decode_workers),
            "hours_back": hours_back,
            "hours_cached_ok": hours_cached_ok,
            "min_ok_hours": min_ok_hours,
            "batch_kind": batch_kind,
            "finish_seq": 0,
        })


def _progress_start_batch(
    target_hour: datetime,
    hours: list,
    workers: int = DEFAULT_WORKERS,
) -> None:
    """Compat: delega para ingest batch (fallback sync)."""
    _progress_start_ingest_batch(
        target_hour, hours, batch_kind="full", workers=workers,
    )


def _progress_begin(h: int) -> None:
    """Marca arquivo como em download (worker iniciou)."""
    with _PROGRESS_LOCK:
        f = (_PROGRESS.get("_index") or {}).get(h)
        if f is not None and f["status"] == "pending":
            f["status"] = "downloading"
            f["pct"] = 0
            f["bytes_done"] = 0
            f["bytes_total"] = None


def _progress_bytes(h: int, done: int, total: Optional[int]) -> None:
    """Atualiza progresso real do HTTP (bytes recebidos)."""
    with _PROGRESS_LOCK:
        f = (_PROGRESS.get("_index") or {}).get(h)
        if f is None or f["status"] != "downloading":
            return
        f["bytes_done"] = done
        if total and total > 0:
            f["bytes_total"] = total
            # Reserva 100% para conclusao (decode); max 99 durante rede.
            f["pct"] = min(99, int(done * 100 / total))
        else:
            f["bytes_total"] = None


def _progress_decode_start(h: int) -> None:
    """HTTP concluido; decode eccodes em processo separado."""
    with _PROGRESS_LOCK:
        f = (_PROGRESS.get("_index") or {}).get(h)
        if f is None:
            return
        f["status"] = "decoding"
        f["pct"] = 0


def _progress_download_done(h: int, nbytes: int) -> None:
    """HTTP concluido; passa para fase decode."""
    with _PROGRESS_LOCK:
        f = (_PROGRESS.get("_index") or {}).get(h)
        if f is None:
            return
        f["bytes_done"] = nbytes
        if not f.get("bytes_total"):
            f["bytes_total"] = nbytes
    _progress_decode_start(h)


def _progress_schedule_retry(h: int) -> None:
    """Recoloca na fila para nova tentativa (nao conta como falha final)."""
    with _PROGRESS_LOCK:
        f = (_PROGRESS.get("_index") or {}).get(h)
        if f is None:
            return
        f["status"] = "pending"
        f["pct"] = 0
        f["bytes_done"] = 0
        f["bytes_total"] = None
        f["retries"] = f.get("retries", 0) + 1
        f.pop("terminal", None)


def _progress_terminal(h: int, ok: bool) -> None:
    """Marca hora como concluida (sucesso ou falha definitiva)."""
    with _PROGRESS_LOCK:
        f = (_PROGRESS.get("_index") or {}).get(h)
        if f is None or f.get("terminal"):
            return
        f["terminal"] = True
        f["status"] = "ok" if ok else "fail"
        f["pct"] = 100 if ok else f.get("pct", 0)
        _PROGRESS["finish_seq"] = _PROGRESS.get("finish_seq", 0) + 1
        f["finish_seq"] = _PROGRESS["finish_seq"]
        _PROGRESS["done"] += 1
        if ok:
            _PROGRESS["ok"] += 1
        else:
            _PROGRESS["fail"] += 1


def _file_progress_fraction(f: dict) -> float:
    """Fracao 0..1 de um GRIB (download parcial + decode)."""
    st = f.get("status", "pending")
    if st == "ok":
        return 1.0
    if st == "fail":
        return 1.0
    if st == "decoding":
        return 0.94
    if st == "downloading":
        pct = int(f.get("pct") or 0)
        if pct > 0:
            return 0.08 + 0.86 * (pct / 100.0)
        if f.get("bytes_done", 0) > 0:
            return 0.14
        return 0.04
    return 0.0


def _progress_aggregate() -> dict:
    """Metricas agregadas para barras totais (nao so done/total discreto)."""
    files = _PROGRESS.get("files") or []
    total = len(files)
    if total <= 0:
        return {
            "batch_fraction": 0.0,
            "batch_pct": 0.0,
            "batch_done_display": 0.0,
            "in_flight_hours": 0.0,
        }
    parts = [_file_progress_fraction(f) for f in files]
    batch_frac = sum(parts) / total
    in_flight = sum(
        parts[i] for i, f in enumerate(files)
        if f.get("status") in ("downloading", "decoding")
    )
    return {
        "batch_fraction": round(batch_frac, 4),
        "batch_pct": round(batch_frac * 100, 1),
        "batch_done_display": round(batch_frac * total, 1),
        "in_flight_hours": round(in_flight, 2),
    }


def _progress_live_counts() -> Tuple[int, int, int]:
    """Retorna (baixando, lendo/decode, na_fila)."""
    files = _PROGRESS.get("files") or []
    dl = sum(1 for f in files if f["status"] == "downloading")
    dec = sum(1 for f in files if f["status"] == "decoding")
    queued = sum(1 for f in files if f["status"] == "pending")
    return dl, dec, queued


def _progress_ui_files(max_rows: int = 14) -> list:
    """Subconjunto para a UI: ativos + poucos concluidos recentes."""
    files = _PROGRESS.get("files") or []
    order = {
        "downloading": 0, "decoding": 1, "pending": 2,
        "ok": 3, "fail": 4,
    }
    active = [
        f for f in files
        if f["status"] in ("downloading", "decoding", "pending")
    ]
    active.sort(key=lambda f: (order.get(f["status"], 9), f["h"]))
    done = [f for f in files if f["status"] in ("ok", "fail")]
    done.sort(key=lambda f: f.get("finish_seq", 0), reverse=True)
    cap_active = max(8, max_rows - 4)
    visible = active[:cap_active] + done[:4]
    return [dict(f) for f in visible[:max_rows]]


def _progress_finish() -> None:
    """Encerra o batch de ingest (cache pode continuar crescendo)."""
    with _PROGRESS_LOCK:
        _PROGRESS["active"] = False
        if _PROGRESS.get("phase") == "ingest":
            _PROGRESS["stage"] = None


def progress_stage(key: str) -> None:
    """Marca a etapa de processamento atual (pos-download) para a UI."""
    with _PROGRESS_LOCK:
        _PROGRESS["phase"] = "processing"
        _PROGRESS["stage"] = key


def progress_done() -> None:
    """Encerra o ciclo: snapshot publicado e renderizado."""
    with _PROGRESS_LOCK:
        _PROGRESS["active"] = False
        _PROGRESS["phase"] = "done"
        _PROGRESS["stage"] = None


def _build_stages(phase: str, stage) -> list:
    """Monta a lista de etapas com status done/active/pending para a UI."""
    cur = _STAGE_ORDER.index(stage) if stage in _STAGE_ORDER else -1
    out = []
    for i, key in enumerate(_STAGE_ORDER):
        if phase == "done":
            st = "done"
        elif i < cur:
            st = "done"
        elif i == cur:
            st = "active"
        else:
            st = "pending"
        out.append({"key": key, "label": _STAGE_LABELS[key], "status": st})
    return out


def get_download_progress() -> dict:
    """Snapshot do progresso de ingest/download para a UI."""
    ingest_st: dict = {}
    refreshing = False
    ingest_ready = False
    try:
        from .merge_ingest import (
            ingest,
            HOURS_BACK_DEFAULT,
            MIN_OK_HOURS,
        )
        ingest_st = ingest.status()
        refreshing = ingest_st.get("refreshing", False)
        ingest_ready = ingest_st.get("ready", False)
        hours_back = ingest_st.get("hours_back", HOURS_BACK_DEFAULT)
        hours_cached = ingest_st.get("hours_cached_ok", 0)
        min_ok = MIN_OK_HOURS
    except Exception:
        hours_back = _PROGRESS.get("hours_back", 96)
        hours_cached = _PROGRESS.get("hours_cached_ok", 0)
        min_ok = _PROGRESS.get("min_ok_hours", 24)

    with _PROGRESS_LOCK:
        dl, dec, queued = _progress_live_counts()
        agg = _progress_aggregate()
        phase = _PROGRESS["phase"]
        batch_active = _PROGRESS["active"]
        active = batch_active or refreshing
        if not ingest_ready and hours_cached < min_ok:
            active = True
        in_flight = agg.get("in_flight_hours", 0.0)
        if batch_active and in_flight > 0:
            cache_display = hours_cached + in_flight
        else:
            cache_display = float(hours_cached)
        cache_pct = (
            min(100.0, (cache_display / hours_back) * 100.0)
            if hours_back else 0.0
        )
        return {
            "active": active,
            "refreshing": refreshing,
            "ingest_ready": ingest_ready,
            "total": _PROGRESS["total"],
            "done": _PROGRESS["done"],
            "ok": _PROGRESS["ok"],
            "fail": _PROGRESS["fail"],
            "batch_fraction": agg["batch_fraction"],
            "batch_pct": agg["batch_pct"],
            "batch_done_display": agg["batch_done_display"],
            "cache_hours_display": round(cache_display, 1),
            "cache_pct": round(cache_pct, 1),
            "downloading": dl,
            "decoding": dec,
            "in_progress": dl + dec,
            "queued": queued,
            "hours_back": hours_back,
            "hours_cached_ok": hours_cached,
            "min_ok_hours": min_ok,
            "batch_kind": _PROGRESS.get("batch_kind", "idle"),
            "target": _PROGRESS["target"],
            "started_at": _PROGRESS["started_at"],
            "files": _progress_ui_files(),
            "phase": phase,
            "stage": _PROGRESS["stage"],
            "stages": _build_stages(phase, _PROGRESS["stage"]),
            "workers": _PROGRESS.get("workers", DEFAULT_WORKERS),
            "decode_workers": _PROGRESS.get(
                "decode_workers", DEFAULT_DECODE_WORKERS
            ),
        }


def _hourly_url(dt: datetime) -> str:
    return (
        f"{INPE_BASE}/HOURLY/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/"
        f"MERGE_CPTEC_{dt.year:04d}{dt.month:02d}{dt.day:02d}{dt.hour:02d}.grib2"
    )


@dataclass
class RainSample:
    lat: float
    lon: float
    intensity_mmh: float
    # Acumulados parciais (seguidos do PDF):
    # - geológico: 72h observadas (MERGE) + 24h previstas (WRF) = 96h total
    # - hidrológico: 18h observadas (MERGE) + 6h previstas (WRF) = 24h total
    ac72h_mm: float
    ac18h_mm: float
    ac24h_mm: float
    ac96h_mm: float
    timestamp_utc: str
    source: str = "MERGE/INPE"
    # Metadados de qualidade do batch (opcionais, populados apenas no caminho real)
    files_ok: int = 0
    missing_24h: int = 0
    missing_96h: int = 0
    # Serie horaria bruta do ponto (mm por hora; indice 0 = hora mais
    # recente). Populada apenas quando fetch_real_batch(with_series=True),
    # usada para reaproveitar os dados do ciclo na Linha do Tempo.
    series: Optional[list] = None


# ---------------------------------------------------------------------------
# Backend eccodes - decode em memoria
# ---------------------------------------------------------------------------

def _eccodes_available() -> bool:
    try:
        import eccodes as _eccodes
        return _eccodes is not None
    except Exception:
        return False


_HTTP_SESSION: Optional[requests.Session] = None


def _http() -> requests.Session:
    """Sessao HTTP com keep-alive para reaproveitar conexoes."""
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        pool = max(1, DEFAULT_WORKERS)
        s = requests.Session()
        s.headers.update({"User-Agent": "PLI-HazardTrack/0.1 (eccodes streaming)"})
        adapter = HTTPAdapter(pool_connections=pool, pool_maxsize=pool)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _HTTP_SESSION = s
    return _HTTP_SESSION


def _fetch_grib_bytes(
    dt: datetime, h: Optional[int] = None
) -> Optional[bytes]:
    """Baixa GRIB horario com progresso por bytes (stream HTTP)."""
    if h is not None:
        _progress_begin(h)
    url = _hourly_url(dt)
    try:
        r = _http().get(url, timeout=HTTP_TIMEOUT, stream=True)
        if r.status_code != 200:
            log.debug("MERGE %s: HTTP %s", dt, r.status_code)
            return None
        cl = r.headers.get("Content-Length")
        total = int(cl) if cl and str(cl).isdigit() else None
        chunks = []
        done = 0
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                continue
            chunks.append(chunk)
            done += len(chunk)
            if h is not None:
                _progress_bytes(h, done, total)
        data = b"".join(chunks)
        if len(data) < 1000:
            log.debug(
                "MERGE %s: resposta curta (%d bytes)", dt, len(data)
            )
            return None
        if h is not None:
            _progress_download_done(h, len(data))
        return data
    except Exception as e:
        log.debug("MERGE %s falhou: %s", dt, e)
        return None


def _sample_grib_in_memory(grib_bytes: bytes,
                           lats: List[float],
                           lons_360: List[float]) -> List[float]:
    """
    Decodifica um GRIB em memoria e amostra todos os pontos de uma vez.
    Usa codes_new_from_message (eccodes 2.x) que aceita bytes diretamente.

    eccodes MEMFS nao e thread-safe; usar ProcessPoolExecutor no decode.
    """
    import eccodes

    n = len(lats)
    samples = [0.0] * n
    gid = eccodes.codes_new_from_message(grib_bytes)
    if gid is None:
        return samples
    try:
        try:
            nearest = eccodes.codes_grib_find_nearest_multiple(gid, False, lats, lons_360)
            for i, near in enumerate(nearest):
                v = float(near.value)
                samples[i] = 0.0 if (v > 1e30 or v < 0) else v
            return samples
        except Exception as e:
            log.debug("nearest_multiple falhou (%s); fallback ponto-a-ponto", e)

        for i in range(n):
            try:
                near = eccodes.codes_grib_find_nearest(gid, lats[i], lons_360[i])
                v = float(near[0].value)
                samples[i] = 0.0 if (v > 1e30 or v < 0) else v
            except Exception:
                pass
        return samples
    finally:
        eccodes.codes_release(gid)


def _mp_decode_grib(
    payload: Tuple[int, Optional[bytes], List[float], List[float]],
) -> Tuple[int, Optional[List[float]]]:
    """Worker de processo: decode GRIB (picklable)."""
    h, data, lats, lons_360 = payload
    if not data:
        return h, None
    try:
        return h, _sample_grib_in_memory(data, lats, lons_360)
    except Exception as e:
        log.debug("decode processo h=%d falhou: %s", h, e)
        return h, None


def _target_hour_for(now: datetime) -> datetime:
    return (
        now - timedelta(hours=PUBLISH_LAG_HOURS)
    ).replace(minute=0, second=0, microsecond=0)


def _hour_iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _hours_to_fetch(
    hours: List[Tuple[int, datetime]],
    by_iso: dict,
    refetch_recent: int,
) -> List[Tuple[int, datetime]]:
    """Horas ausentes ou recentes (republicacao INPE) a re-buscar."""
    todo: List[Tuple[int, datetime]] = []
    for h, dt in hours:
        key = _hour_iso(dt)
        ent = by_iso.get(key)
        ok = getattr(ent, "ok", None)
        if ent is None:
            ok = ent.get("ok") if isinstance(ent, dict) else False
        if not ok:
            todo.append((h, dt))
        elif h < refetch_recent:
            todo.append((h, dt))
    return todo


def _run_download_decode_batch(
    todo: List[Tuple[int, datetime]],
    lats: List[float],
    lons_360: List[float],
    dl_workers: int = DEFAULT_WORKERS,
    dec_workers: int = DEFAULT_DECODE_WORKERS,
    progress_ctx: Optional[dict] = None,
    on_hour_done=None,
) -> Dict[int, Tuple[Optional[List[float]], bool]]:
    """
    Pipeline: download paralelo (threads) + decode paralelo (processos).
    Retorna {h: (samples, ok)} para cada hora solicitada.
    """
    if not todo:
        return {}

    h0, dt0 = todo[0]
    target = dt0 + timedelta(hours=h0)
    if progress_ctx:
        _progress_start_ingest_batch(
            target,
            todo,
            hours_back=progress_ctx.get("hours_back", 96),
            hours_cached_ok=progress_ctx.get("hours_cached_ok", 0),
            min_ok_hours=progress_ctx.get("min_ok_hours", 24),
            batch_kind=progress_ctx.get("batch_kind", "full"),
            workers=dl_workers,
            decode_workers=dec_workers,
        )
    else:
        _progress_start_batch(target, todo, workers=dl_workers)
    hour_dt = {h: dt for h, dt in todo}
    results: Dict[int, Tuple[Optional[List[float]], bool]] = {}
    retry_queue: Dict[int, int] = {h: 0 for h, _ in todo}

    pending_dl = list(todo)
    wave_size = max(1, dl_workers)
    while pending_dl:
        wave = pending_dl[:wave_size]
        pending_dl = pending_dl[wave_size:]

        downloaded: Dict[int, Optional[bytes]] = {}
        with ThreadPoolExecutor(max_workers=max(1, dl_workers)) as tex:
            futs = {
                tex.submit(_fetch_grib_bytes, dt, h): (h, dt)
                for h, dt in wave
            }
            for fut in as_completed(futs):
                h, _dt = futs[fut]
                try:
                    downloaded[h] = fut.result()
                except Exception as e:
                    log.debug("download h=%d falhou: %s", h, e)
                    downloaded[h] = None

        to_decode: List[Tuple[int, Optional[bytes]]] = [
            (h, downloaded.get(h)) for h, _ in wave
        ]
        decode_out: Dict[int, Optional[List[float]]] = {}

        for h, data in to_decode:
            if data:
                _progress_decode_start(h)

        with ProcessPoolExecutor(max_workers=max(1, dec_workers)) as pex:
            futs = {
                pex.submit(
                    _mp_decode_grib, (h, data, lats, lons_360)
                ): h
                for h, data in to_decode
            }
            for fut in as_completed(futs):
                h = futs[fut]
                try:
                    _, samples = fut.result()
                except Exception as e:
                    log.debug("decode future h=%d: %s", h, e)
                    samples = None
                decode_out[h] = samples

        for h, _data in to_decode:
            samples = decode_out.get(h)
            if samples is not None:
                results[h] = (samples, True)
                _progress_terminal(h, True)
                if on_hour_done:
                    on_hour_done(h, samples, True)
            else:
                att = retry_queue.get(h, 0)
                if att < MAX_GRIB_RETRIES:
                    retry_queue[h] = att + 1
                    _progress_schedule_retry(h)
                    pending_dl.append((h, hour_dt[h]))
                else:
                    results[h] = (None, False)
                    _progress_terminal(h, False)

    return results


def _fetch_series_full(
    points: list,
    now_utc: Optional[datetime] = None,
    hours_back: int = 96,
    workers: int = DEFAULT_WORKERS,
):
    """Fetch completo (fallback sync quando ingest ainda nao tem cache)."""
    if not _eccodes_available():
        log.warning("eccodes nao disponivel")
        return None

    now = now_utc or datetime.now(timezone.utc)
    target_hour = _target_hour_for(now)
    n = len(points)
    lats = [float(p[0]) for p in points]
    lons_360 = [
        float(p[1]) if p[1] >= 0 else float(p[1]) + 360 for p in points
    ]
    hours = [
        (h, target_hour - timedelta(hours=h)) for h in range(hours_back)
    ]
    log.info(
        "MERGE fetch completo: target=%s, %d horas, %d pontos",
        target_hour.isoformat(), hours_back, n,
    )
    raw = _run_download_decode_batch(hours, lats, lons_360, workers)
    _progress_finish()

    series = [[0.0] * hours_back for _ in range(n)]
    hour_ok = [False] * hours_back
    files_ok = 0
    for h, (samples, ok) in raw.items():
        if ok and samples:
            for i in range(n):
                v = samples[i]
                if v > 0:
                    series[i][h] = v
            hour_ok[h] = True
            files_ok += 1

    if files_ok == 0:
        return None
    return target_hour, series, hour_ok, files_ok


def fetch_real_batch(
    points: list,
    now_utc: Optional[datetime] = None,
    hours_back: int = 96,
    workers: int = DEFAULT_WORKERS,
    with_series: bool = False,
    force_sync: bool = False,
) -> Optional[list]:
    """
    Retorna RainSample por ponto. Preferencia: cache RAM do ingest.
    Fallback: fetch completo sincrono (testes / bootstrap / historico).
    """
    if not force_sync:
        try:
            from .merge_ingest import ingest
            ingest.configure(points)
            batch = ingest.get_rain_batch(
                points, now_utc, with_series=with_series,
            )
            if batch is not None:
                return batch
        except Exception as e:  # noqa: BLE001
            log.debug("ingest indisponivel (%s); fallback sync", e)

    res = _fetch_series_full(points, now_utc, hours_back, workers)
    if res is None:
        return None
    target_hour, series, hour_ok, files_ok = res
    missing_24h = sum(1 for ok in hour_ok[:24] if not ok)
    missing_96h = sum(1 for ok in hour_ok[:96] if not ok)
    out = []
    ts = target_hour.isoformat()
    for i, (lat, lon) in enumerate(points):
        s = series[i]
        out.append(RainSample(
            lat=lat, lon=lon,
            intensity_mmh=round(s[0], 2),
            ac72h_mm=round(sum(s[:72]), 2),
            ac18h_mm=round(sum(s[:18]), 2),
            ac24h_mm=round(sum(s[:24]), 2),
            ac96h_mm=round(sum(s[:96]), 2),
            timestamp_utc=ts,
            source="MERGE/INPE (streaming)",
            files_ok=files_ok,
            missing_24h=missing_24h,
            missing_96h=missing_96h,
            series=[round(v, 2) for v in s] if with_series else None,
        ))
    return out


def fetch_hourly_series(
    points: list,
    now_utc: Optional[datetime] = None,
    hours_back: int = 192,
    workers: int = DEFAULT_WORKERS,
):
    try:
        from .merge_ingest import ingest
        ingest.configure(points)
        res = ingest.get_hourly_series(points, now_utc, hours_back)
        if res is not None:
            return res
    except Exception:
        pass
    res = _fetch_series_full(points, now_utc, min(hours_back, 96), workers)
    if res is None:
        return None
    target_hour, series, _, _ = res
    return target_hour, series


def fetch_real(lat: float, lon: float,
               now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    res = fetch_real_batch([(lat, lon)], now_utc)
    return res[0] if res else None



def fetch(lat: float, lon: float,
          now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    """API legada: retorna apenas dado real do MERGE; None se indisponivel."""
    return fetch_real(lat, lon, now_utc)
