"""Testes do mecanismo de notificacao usado pelo SSE /api/progress/stream.

Cobre:
- versao monotonica que incrementa em cada mutacao
- wait_for_progress_change desbloqueia ao haver mudanca
- wait_for_progress_change respeita timeout (sem mudanca -> retorna versao igual)
- throttle de _progress_bytes (1 notify por bucket de 5%)
"""
from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timezone

from core import merge_inpe as mi


def _reset_progress() -> None:
    """Estado neutro entre testes (versao inclusa nao reseta a 0)."""
    with mi._PROGRESS_LOCK:
        mi._PROGRESS.update({
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
            "hours_back": 96,
            "min_ok_hours": 24,
            "batch_kind": "idle",
        })


class TestProgressVersion(unittest.TestCase):
    def setUp(self):
        _reset_progress()

    def test_version_incrementa_em_start_batch(self):
        v0 = mi.get_progress_version()
        dt = datetime(2026, 6, 22, 5, tzinfo=timezone.utc)
        mi._progress_start_ingest_batch(
            dt, [(0, dt)], hours_back=1, min_ok_hours=1,
        )
        v1 = mi.get_progress_version()
        self.assertGreater(v1, v0)

    def test_version_incrementa_em_terminal(self):
        dt = datetime(2026, 6, 22, 5, tzinfo=timezone.utc)
        mi._progress_start_ingest_batch(
            dt, [(0, dt)], hours_back=1, min_ok_hours=1,
        )
        v0 = mi.get_progress_version()
        mi._progress_terminal(0, ok=True)
        v1 = mi.get_progress_version()
        self.assertGreater(v1, v0)

    def test_version_incrementa_em_stage_e_done(self):
        v0 = mi.get_progress_version()
        mi.progress_stage("aggregate")
        v1 = mi.get_progress_version()
        self.assertGreater(v1, v0)
        mi.progress_done()
        v2 = mi.get_progress_version()
        self.assertGreater(v2, v1)


class TestWaitForChange(unittest.TestCase):
    def setUp(self):
        _reset_progress()

    def test_timeout_retorna_mesma_versao(self):
        v0 = mi.get_progress_version()
        t0 = time.monotonic()
        v1 = mi.wait_for_progress_change(v0, timeout_s=0.2)
        elapsed = time.monotonic() - t0
        self.assertEqual(v1, v0)
        self.assertGreaterEqual(elapsed, 0.18)

    def test_acorda_em_mudanca(self):
        v0 = mi.get_progress_version()
        wakeup_ts: list = []

        def waiter():
            v = mi.wait_for_progress_change(v0, timeout_s=2.0)
            wakeup_ts.append((time.monotonic(), v))

        th = threading.Thread(target=waiter)
        th.start()
        time.sleep(0.05)
        t_change = time.monotonic()
        mi.progress_stage("aggregate")
        th.join(timeout=1.0)

        self.assertEqual(len(wakeup_ts), 1)
        t_wake, v_wake = wakeup_ts[0]
        self.assertGreater(v_wake, v0)
        # Acordou em menos de 200ms apos a mudanca (idealmente <50ms)
        self.assertLess(t_wake - t_change, 0.3)


class TestProgressBytesThrottle(unittest.TestCase):
    def setUp(self):
        _reset_progress()
        dt = datetime(2026, 6, 22, 5, tzinfo=timezone.utc)
        mi._progress_start_ingest_batch(
            dt, [(0, dt)], hours_back=1, min_ok_hours=1,
        )
        mi._progress_begin(0)

    def test_chunks_pequenos_geram_poucos_notifies(self):
        # Sem throttle: 100 chunks de 1% gerariam 100 notifies.
        # Com throttle de 5%: ~20 notifies.
        v0 = mi.get_progress_version()
        for done in range(0, 1000, 10):  # 100 chunks de 1%
            mi._progress_bytes(0, done, 1000)
        v1 = mi.get_progress_version()
        n_notifies = v1 - v0
        self.assertLessEqual(n_notifies, 22, f"esperava <=22, obtive {n_notifies}")
        self.assertGreaterEqual(n_notifies, 18, f"esperava >=18, obtive {n_notifies}")

    def test_sem_total_nao_notifica(self):
        v0 = mi.get_progress_version()
        for done in range(0, 1000, 100):
            mi._progress_bytes(0, done, None)
        v1 = mi.get_progress_version()
        # Sem total nao consegue calcular bucket; nenhum notify gerado.
        self.assertEqual(v1, v0)


if __name__ == "__main__":
    unittest.main()
