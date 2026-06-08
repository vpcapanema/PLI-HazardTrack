"""
Ingestao MERGE/CPTEC/INPE em STREAMING - sem cache em disco.

Estrategia:
- HTTP GET do GRIB2 horario direto do servidor INPE (paralelo, 8 workers)
- Decodificacao via eccodes 2.x com codes_new_from_message (aceita bytes)
- Decode SERIALIZADO com lock global (eccodes MEMFS nao e thread-safe)
- Amostragem batch via codes_grib_find_nearest_multiple (1 chamada para N pontos)
- Agregacao em memoria

Sem write em disco. Cada refresh busca dados frescos.

Estrutura no servidor INPE:
    https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/HOURLY/AAAA/MM/DD/MERGE_CPTEC_AAAAMMDDHH.grib2

Resolucao: 0.1 graus (~10 km). Cobertura: America do Sul. Sem auth.

nenhum GRIB chegar, fetch_real_batch retorna None e o aggregator marca o
snapshot como degraded; a UI mostra "Dado indisponivel" em vez de fingir
chuva sintetica.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import List, Optional, Tuple
import logging
import os
import requests

log = logging.getLogger("merge_inpe")

INPE_BASE = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM"
PUBLISH_LAG_HOURS = 3
HTTP_TIMEOUT = (10, 60)         # (connect, read)
# Em producao (Render free: 0.5 CPU / 512MB RAM) reduzimos os workers para
# nao estourar memoria nem saturar CPU. Pode ser sobreposto via env.
DEFAULT_WORKERS = int(os.environ.get("SAMAEG_WORKERS", "4"))

# eccodes MEMFS nao e thread-safe: serializa o decode entre threads.
_ECCODES_LOCK = Lock()

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
    # Fase do ciclo: "download" (baixando GRIBs), "processing"
    # (agregando/calculando) ou "done" (snapshot publicado).
    "phase": "idle",
    "stage": None,
}

# Etapas do ciclo com mensagens amistosas, na ordem de execucao. A UI usa
# isto para descrever o que o servidor esta fazendo apos o download.
_STAGE_ORDER = ["download", "aggregate", "forecast", "risk", "publish"]
_STAGE_LABELS = {
    "download": "Baixando os dados de chuva do INPE (MERGE)",
    "aggregate": "Organizando a chuva observada das ultimas 96 horas",
    "forecast": "Consultando a previsao de chuva (WRF / CPTEC)",
    "risk": "Calculando o risco de cada trecho da rodovia",
    "publish": "Atualizando o painel e o mapa de risco",
}


def _progress_start(target_hour: datetime, hours: list) -> None:
    """Inicializa o rastreador para um novo batch de download."""
    files = []
    for h, dt in hours:
        files.append({
            "h": h,
            "ts": dt.isoformat(),
            "name": _hourly_url(dt).rsplit("/", 1)[-1],
            "status": "pending",
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
            "phase": "download",
            "stage": "download",
        })


def _progress_mark(h: int, ok: bool) -> None:
    """Marca o status de um arquivo (ok/fail) ao concluir o worker."""
    with _PROGRESS_LOCK:
        f = (_PROGRESS.get("_index") or {}).get(h)
        if f is not None and f["status"] == "pending":
            f["status"] = "ok" if ok else "fail"
            _PROGRESS["done"] += 1
            if ok:
                _PROGRESS["ok"] += 1
            else:
                _PROGRESS["fail"] += 1


def _progress_finish() -> None:
    """Encerra o batch de progresso (download concluido)."""
    with _PROGRESS_LOCK:
        _PROGRESS["active"] = False


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
    """Snapshot do progresso de download para a UI (copia segura)."""
    with _PROGRESS_LOCK:
        return {
            "active": _PROGRESS["active"],
            "total": _PROGRESS["total"],
            "done": _PROGRESS["done"],
            "ok": _PROGRESS["ok"],
            "fail": _PROGRESS["fail"],
            "target": _PROGRESS["target"],
            "started_at": _PROGRESS["started_at"],
            "files": [dict(f) for f in _PROGRESS["files"]],
            "phase": _PROGRESS["phase"],
            "stage": _PROGRESS["stage"],
            "stages": _build_stages(
                _PROGRESS["phase"], _PROGRESS["stage"]
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
        s = requests.Session()
        s.headers.update({"User-Agent": "PLI-HazardTrack/0.1 (eccodes streaming)"})
        _HTTP_SESSION = s
    return _HTTP_SESSION


def _fetch_grib_bytes(dt: datetime) -> Optional[bytes]:
    """Baixa o GRIB horario para memoria. Retorna None em falha."""
    url = _hourly_url(dt)
    try:
        r = _http().get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200 or len(r.content) < 1000:
            log.debug("MERGE %s: HTTP %s (%d bytes)", dt, r.status_code, len(r.content))
            return None
        return r.content
    except Exception as e:
        log.debug("MERGE %s falhou: %s", dt, e)
        return None


def _sample_grib_in_memory(grib_bytes: bytes,
                           lats: List[float],
                           lons_360: List[float]) -> List[float]:
    """
    Decodifica um GRIB em memoria e amostra todos os pontos de uma vez.
    Usa codes_new_from_message (eccodes 2.x) que aceita bytes diretamente.

    eccodes MEMFS nao e thread-safe; o chamador deve manter _ECCODES_LOCK.
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


def _process_hour(dt: datetime,
                  lats: List[float],
                  lons_360: List[float]) -> Tuple[datetime, Optional[List[float]]]:
    """Download paralelo (rede) + decode serializado (eccodes nao e thread-safe)."""
    data = _fetch_grib_bytes(dt)
    if data is None:
        return dt, None
    try:
        with _ECCODES_LOCK:
            return dt, _sample_grib_in_memory(data, lats, lons_360)
    except Exception as e:
        log.debug("erro decode %s: %s", dt, e)
        return dt, None
    finally:
        data = None  # noqa: F841 - solta a referencia para o GC


def _fetch_series(points: list,
                  now_utc: Optional[datetime] = None,
                  hours_back: int = 96,
                  workers: int = DEFAULT_WORKERS):
    """Stream paralelo de GRIB2 horarios; retorna a serie horaria bruta.

    Returns (target_hour, series, hour_ok, files_ok) onde
    series[i][h] = chuva (mm) do ponto i, h horas antes de target_hour.
    Retorna None se eccodes indisponivel ou se nenhum GRIB foi lido.
    """
    if not _eccodes_available():
        log.warning("eccodes nao disponivel; chamador deve usar MOCK")
        return None

    now = now_utc or datetime.now(timezone.utc)
    target_hour = (now - timedelta(hours=PUBLISH_LAG_HOURS)).replace(minute=0, second=0, microsecond=0)

    n = len(points)
    lats = [float(p[0]) for p in points]
    lons_360 = [float(p[1]) if p[1] >= 0 else float(p[1]) + 360 for p in points]

    series = [[0.0] * hours_back for _ in range(n)]
    hour_ok = [False] * hours_back
    files_ok = 0

    hours = [(h, target_hour - timedelta(hours=h)) for h in range(hours_back)]

    log.info(
        "MERGE batch: target=%s, %d horas, %d pontos, %d workers",
        target_hour.isoformat(), hours_back, n, max(1, workers)
    )

    progress_every = max(1, hours_back // 6)  # ~6 marcos no log
    _progress_start(target_hour, hours)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(_process_hour, dt, lats, lons_360): h for h, dt in hours}
        done = 0
        for fut in as_completed(futures):
            h = futures[fut]
            try:
                _, samples = fut.result()
            except Exception as e:
                log.debug("worker falhou em h=%d: %s", h, e)
                samples = None
            done += 1
            _progress_mark(h, samples is not None)
            if samples is None:
                if done % progress_every == 0:
                    log.info("MERGE progress %d/%d (ok=%d)", done, hours_back, files_ok)
                continue
            for i in range(n):
                v = samples[i]
                if v > 0:
                    series[i][h] = v
            hour_ok[h] = True
            files_ok += 1
            if done % progress_every == 0:
                log.info("MERGE progress %d/%d (ok=%d)", done, hours_back, files_ok)

    _progress_finish()

    if files_ok == 0:
        log.warning("nenhum GRIB MERGE foi lido com sucesso")
        return None

    return target_hour, series, hour_ok, files_ok


def fetch_real_batch(points: list,
                     now_utc: Optional[datetime] = None,
                     hours_back: int = 96,
                     workers: int = DEFAULT_WORKERS,
                     with_series: bool = False) -> Optional[list]:
    """
    Stream paralelo de 96 GRIB2 horarios direto do INPE.
    Retorna lista de RainSample na mesma ordem de `points` (ou None se eccodes indisponivel).

    Cada RainSample carrega tres metricas extras de qualidade do batch (iguais para
    todos os pontos, replicadas por conveniencia da API):
      - files_ok          numero total de horas lidas com sucesso (0..96)
      - missing_24h       horas faltando na janela 0..23h
      - missing_96h       horas faltando na janela 0..95h

    Com `with_series=True`, cada RainSample.series carrega a serie horaria
    bruta do ponto (reaproveitada pela Linha do Tempo, sem novo download).
    """
    res = _fetch_series(points, now_utc, hours_back, workers)
    if res is None:
        return None
    target_hour, series, hour_ok, files_ok = res

    missing_24h = sum(1 for ok in hour_ok[:24] if not ok)
    missing_96h = sum(1 for ok in hour_ok[:96] if not ok)
    log.info(
        "MERGE streaming: %d/%d arquivos lidos para %d pontos (faltando 24h=%d, 96h=%d)",
        files_ok, len(hour_ok), len(points), missing_24h, missing_96h
    )

    out = []
    ts = target_hour.isoformat()
    for i, (lat, lon) in enumerate(points):
        s = series[i]
        ac18h = sum(s[:18])
        ac72h = sum(s[:72])
        out.append(RainSample(
            lat=lat, lon=lon,
            intensity_mmh=round(s[0], 2),
            ac72h_mm=round(ac72h, 2),
            ac18h_mm=round(ac18h, 2),
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


def fetch_hourly_series(points: list,
                        now_utc: Optional[datetime] = None,
                        hours_back: int = 192,
                        workers: int = DEFAULT_WORKERS):
    """Serie horaria bruta por ponto para a animacao temporal (Linha do Tempo).

    Baixa `hours_back` GRIB2 horarios (default 192 = 96 quadros + janela
    movel de 96h) e devolve (target_hour, series), onde series[i][h] e a
    chuva (mm) do ponto i, h horas antes de target_hour. None se indisponivel.
    """
    res = _fetch_series(points, now_utc, hours_back, workers)
    if res is None:
        return None
    target_hour, series, _hour_ok, _files_ok = res
    return target_hour, series


def fetch_real(lat: float, lon: float,
               now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    res = fetch_real_batch([(lat, lon)], now_utc)
    return res[0] if res else None



def fetch(lat: float, lon: float,
          now_utc: Optional[datetime] = None) -> Optional[RainSample]:
    """API legada: retorna apenas dado real do MERGE; None se indisponivel."""
    return fetch_real(lat, lon, now_utc)
