"""
Ingestao continua MERGE/INPE em background + cache incremental em RAM.

- Thread de ingestao atualiza a serie horaria sem bloquear o ciclo de RD.
- Cache por hora absoluta (ISO UTC): ciclos seguintes baixam so horas novas
  ou recentes (republicacao INPE).
- O aggregator le o batch pronto via get_rain_batch() (somente RAM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from threading import Lock, Thread
from typing import Dict, List, Optional, Tuple
import logging
import os
import time

from .merge_inpe import (
    RainSample,
    PUBLISH_LAG_HOURS,
    _eccodes_available,
    _target_hour_for,
    _hours_to_fetch,
    _run_download_decode_batch,
    _progress_finish,
)

log = logging.getLogger("merge_ingest")

INGEST_INTERVAL_S = int(os.environ.get("SAMAEG_INGEST_INTERVAL_S", "120"))
REFETCH_RECENT_H = int(os.environ.get("SAMAEG_REFETCH_RECENT_H", "3"))
HOURS_BACK_DEFAULT = int(os.environ.get("SAMAEG_HOURS_BACK", "96"))
MIN_OK_HOURS = int(os.environ.get("SAMAEG_MIN_OK_HOURS", "24"))


@dataclass
class _HourEntry:
    samples: List[float] = field(default_factory=list)
    ok: bool = False
    updated_at: Optional[datetime] = None


class MergeIngestStore:
    """Cache thread-safe da serie horaria MERGE por hora absoluta."""

    def __init__(self):
        self._lock = Lock()
        self._coords: Optional[List[Tuple[float, float]]] = None
        self._lats: List[float] = []
        self._lons_360: List[float] = []
        self._by_iso: Dict[str, _HourEntry] = {}
        self._target_hour: Optional[datetime] = None
        self._hours_back = HOURS_BACK_DEFAULT
        self._ready = False
        self._last_refresh_at: Optional[datetime] = None
        self._last_fetched = 0
        self._thread: Optional[Thread] = None
        self._stop = False
        self._refreshing = False

    def configure(self, coords: List[Tuple[float, float]]) -> None:
        with self._lock:
            if self._coords == coords:
                return
            self._coords = list(coords)
            self._lats = [float(c[0]) for c in coords]
            self._lons_360 = [
                float(c[1]) if c[1] >= 0 else float(c[1]) + 360
                for c in coords
            ]
            self._by_iso.clear()
            self._target_hour = None
            self._ready = False

    def start(self) -> None:
        import multiprocessing as mp
        if mp.current_process().name != "MainProcess":
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = Thread(target=self._loop, name="merge-ingest", daemon=True)
        self._thread.start()
        log.info(
            "Ingest MERGE iniciado (intervalo=%ds, refetch=%dh)",
            INGEST_INTERVAL_S, REFETCH_RECENT_H,
        )

    def is_refreshing(self) -> bool:
        with self._lock:
            return self._refreshing

    def should_wait(self) -> bool:
        """True enquanto o cache inicial ainda esta sendo populado."""
        with self._lock:
            if self._ready:
                return False
            if self._refreshing:
                return True
            ok_h = 0
            if self._target_hour:
                ok_h = sum(
                    1 for h in range(HOURS_BACK_DEFAULT)
                    if self._hour_ok_locked(self._target_hour, h)
                )
            if not self._by_iso and self._last_refresh_at is None:
                return True
            if ok_h < MIN_OK_HOURS:
                if self._last_refresh_at is None:
                    return True
                age = (
                    datetime.now(timezone.utc) - self._last_refresh_at
                ).total_seconds()
                if age < INGEST_INTERVAL_S * 5:
                    return True
        from .merge_inpe import get_download_progress
        prog = get_download_progress()
        if prog.get("active"):
            return True
        total = prog.get("total") or 0
        done = prog.get("done") or 0
        if total > 0 and done < total:
            return True
        return False

    def _trigger_snapshot_update(self) -> None:
        def _run() -> None:
            try:
                from .aggregator import state
                state.update()
            except Exception:  # noqa: BLE001
                log.exception("falha ao atualizar snapshot apos ingest pronto")

        Thread(
            target=_run, daemon=True, name="ingest-ready-update",
        ).start()

    def stop(self) -> None:
        self._stop = True

    def _loop(self) -> None:
        while not self._stop:
            try:
                with self._lock:
                    need_full = not self._ready
                self.refresh(force_full=need_full)
            except Exception:  # noqa: BLE001
                log.exception("falha no ciclo de ingest MERGE")
            time.sleep(INGEST_INTERVAL_S)

    def refresh(self, now: Optional[datetime] = None, force_full: bool = False):
        """Baixa/decodifica horas faltantes ou recentes e atualiza cache."""
        if not _eccodes_available():
            log.warning("eccodes indisponivel; ingest MERGE ignorado")
            return
        with self._lock:
            if not self._coords:
                return
            if self._refreshing:
                return
            self._refreshing = True
            lats = list(self._lats)
            lons_360 = list(self._lons_360)
            by_iso = self._by_iso

        try:
            now = now or datetime.now(timezone.utc)
            target = _target_hour_for(now)
            hours = [
                (h, target - timedelta(hours=h))
                for h in range(HOURS_BACK_DEFAULT)
            ]
            if force_full:
                todo = hours
            else:
                todo = _hours_to_fetch(hours, by_iso, REFETCH_RECENT_H)

            if not todo and self._target_hour == target:
                with self._lock:
                    self._last_refresh_at = datetime.now(timezone.utc)
                return

            if todo:
                log.info(
                    "MERGE ingest: %d hora(s) a buscar (target=%s)",
                    len(todo), target.isoformat(),
                )
                with self._lock:
                    ok_before = sum(
                        1 for h in range(HOURS_BACK_DEFAULT)
                        if self._hour_ok_locked(target, h)
                    )
                batch_kind = "full" if force_full else "incremental"
                progress_ctx = {
                    "hours_back": HOURS_BACK_DEFAULT,
                    "hours_cached_ok": ok_before,
                    "min_ok_hours": MIN_OK_HOURS,
                    "batch_kind": batch_kind,
                }

                def _on_hour(h: int, samples, ok: bool) -> None:
                    self._store_hour(target, h, samples, ok)

                results = _run_download_decode_batch(
                    todo, lats, lons_360,
                    progress_ctx=progress_ctx,
                    on_hour_done=_on_hour,
                )
            else:
                results = {}

            with self._lock:
                was_ready = self._ready
                self._target_hour = target
                now_u = datetime.now(timezone.utc)
                for h, (samples, ok) in results.items():
                    dt = target - timedelta(hours=h)
                    key = dt.replace(tzinfo=timezone.utc).isoformat()
                    self._by_iso[key] = _HourEntry(
                        samples=list(samples) if samples else [],
                        ok=ok,
                        updated_at=now_u,
                    )
                ok_count = sum(
                    1 for h in range(HOURS_BACK_DEFAULT)
                    if self._hour_ok_locked(target, h)
                )
                self._ready = ok_count >= MIN_OK_HOURS
                self._last_refresh_at = now_u
                self._last_fetched = len(todo)
                became_ready = self._ready and not was_ready
                _progress_finish()
            if became_ready:
                log.info(
                    "MERGE ingest pronto (%d horas ok); disparando snapshot",
                    ok_count,
                )
                self._trigger_snapshot_update()
        finally:
            with self._lock:
                self._refreshing = False

    def _store_hour(
        self,
        target: datetime,
        h: int,
        samples: Optional[List[float]],
        ok: bool,
    ) -> None:
        """Grava hora no cache assim que decode termina (progresso live)."""
        dt = target - timedelta(hours=h)
        key = dt.replace(tzinfo=timezone.utc).isoformat()
        with self._lock:
            self._target_hour = target
            self._by_iso[key] = _HourEntry(
                samples=list(samples) if samples else [],
                ok=ok,
                updated_at=datetime.now(timezone.utc),
            )

    def _hour_ok_locked(self, target: datetime, h: int) -> bool:
        dt = target - timedelta(hours=h)
        key = dt.replace(tzinfo=timezone.utc).isoformat()
        ent = self._by_iso.get(key)
        return ent is not None and ent.ok and len(ent.samples) > 0

    def _build_series_locked(
        self, target: datetime, n_points: int
    ) -> Tuple[List[List[float]], List[bool], int]:
        series = [[0.0] * HOURS_BACK_DEFAULT for _ in range(n_points)]
        hour_ok = [False] * HOURS_BACK_DEFAULT
        files_ok = 0
        for h in range(HOURS_BACK_DEFAULT):
            dt = target - timedelta(hours=h)
            key = dt.replace(tzinfo=timezone.utc).isoformat()
            ent = self._by_iso.get(key)
            if ent and ent.ok and len(ent.samples) == n_points:
                for i, v in enumerate(ent.samples):
                    if v > 0:
                        series[i][h] = v
                hour_ok[h] = True
                files_ok += 1
        return series, hour_ok, files_ok

    def get_rain_batch(
        self,
        coords: List[Tuple[float, float]],
        now_utc: Optional[datetime] = None,
        with_series: bool = False,
    ) -> Optional[List[RainSample]]:
        """Le batch pronto do cache (sem download no caminho quente)."""
        self.configure(coords)
        with self._lock:
            if not self._ready or not self._coords:
                return None
            target = self._target_hour
            if target is None:
                return None
            n = len(self._coords)
            series, hour_ok, files_ok = self._build_series_locked(target, n)

        missing_24h = sum(1 for ok in hour_ok[:24] if not ok)
        missing_96h = sum(1 for ok in hour_ok[:96] if not ok)
        ts = target.isoformat()
        src = "MERGE/INPE (cache RAM)"
        out: List[RainSample] = []
        for i, (lat, lon) in enumerate(coords):
            s = series[i]
            out.append(RainSample(
                lat=lat, lon=lon,
                intensity_mmh=round(s[0], 2),
                ac72h_mm=round(sum(s[:72]), 2),
                ac18h_mm=round(sum(s[:18]), 2),
                ac24h_mm=round(sum(s[:24]), 2),
                ac96h_mm=round(sum(s[:96]), 2),
                timestamp_utc=ts,
                source=src,
                files_ok=files_ok,
                missing_24h=missing_24h,
                missing_96h=missing_96h,
                series=[round(v, 2) for v in s] if with_series else None,
            ))
        return out

    def get_hourly_series(
        self,
        coords: List[Tuple[float, float]],
        now_utc: Optional[datetime] = None,
        hours_back: int = 192,
    ):
        self.configure(coords)
        with self._lock:
            if not self._ready or not self._target_hour:
                return None
            target = self._target_hour
            n = len(coords)
            series, _, _ = self._build_series_locked(target, n)
            if hours_back > HOURS_BACK_DEFAULT:
                extra = hours_back - HOURS_BACK_DEFAULT
                for row in series:
                    row.extend([0.0] * extra)
        return target, series

    def status(self) -> dict:
        with self._lock:
            ok_h = 0
            if self._target_hour:
                ok_h = sum(
                    1 for h in range(HOURS_BACK_DEFAULT)
                    if self._hour_ok_locked(self._target_hour, h)
                )
            return {
                "ready": self._ready,
                "refreshing": self._refreshing,
                "target_hour": (
                    self._target_hour.isoformat()
                    if self._target_hour else None
                ),
                "hours_cached_ok": ok_h,
                "hours_back": HOURS_BACK_DEFAULT,
                "last_refresh_at": (
                    self._last_refresh_at.isoformat()
                    if self._last_refresh_at else None
                ),
                "last_fetched_count": self._last_fetched,
                "ingest_interval_s": INGEST_INTERVAL_S,
            }


# Singleton operacional
ingest = MergeIngestStore()
