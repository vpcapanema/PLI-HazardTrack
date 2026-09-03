"""Testes de core/admin_telemetry e core/admin_analytics."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("SAMAEG_DISABLE_BOOTSTRAP", "1")

from core import admin_analytics as aa  # noqa: E402
from core import admin_telemetry as tel  # noqa: E402


def _ts(minutes_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ).isoformat()


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tel.reset_for_tests(Path(self.tmp.name))
        self.addCleanup(tel.reset_for_tests, Path(self.tmp.name))

    def test_record_persiste_e_le_de_volta(self):
        tel.record({"started_at": _ts(20), "outcome": "ok", "max_rd": 2})
        tel.record({"started_at": _ts(10), "outcome": "ok", "max_rd": 3})
        raw = tel.TELEMETRY_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw), 2)
        # Simula reinicio do processo: cache RAM zerado, arquivo mantido
        tel._loaded = False
        tel._entries = []
        rows = tel.load()
        self.assertEqual([r["max_rd"] for r in rows], [2, 3])

    def test_filtro_por_janela(self):
        tel.record({"started_at": _ts(60 * 30), "outcome": "ok"})
        tel.record({"started_at": _ts(5), "outcome": "ok"})
        self.assertEqual(len(tel.load(hours=24)), 1)
        self.assertEqual(len(tel.load()), 2)

    def test_ring_buffer_compacta(self):
        with mock.patch.object(tel, "MAX_ENTRIES", 8):
            for i in range(12):
                tel.record({"started_at": _ts(100 - i), "i": i})
            rows = tel.load()
            self.assertEqual(len(rows), 8)
            self.assertEqual(rows[-1]["i"], 11)
            lines = tel.TELEMETRY_PATH.read_text(
                encoding="utf-8",
            ).splitlines()
            # arquivo compactado com histerese (<= 1.25 x MAX)
            self.assertLessEqual(len(lines), 10)
            self.assertEqual(json.loads(lines[-1])["i"], 11)

    def test_linha_corrompida_e_ignorada(self):
        tel.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        tel.TELEMETRY_PATH.write_text(
            json.dumps({"started_at": _ts(1)}) + "\n{broken\n",
            encoding="utf-8",
        )
        self.assertEqual(len(tel.load()), 1)


class TestAnalyticsHelpers(unittest.TestCase):
    def test_bins(self):
        bins = aa._bin_counts([0, 4.9, 5, 30, 500], [0, 5, 15, 30])
        self.assertEqual([b["count"] for b in bins], [2, 1, 0, 2])
        self.assertEqual(bins[-1]["label"], "≥ 30")

    def test_percentil(self):
        self.assertEqual(aa._percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertIsNone(aa._percentile([], 0.5))

    def test_delta_alertas(self):
        rows = [
            {"at": _ts(130), "alert_count": 1},
            {"at": _ts(70), "alert_count": 4},
            {"at": _ts(0), "alert_count": 6},
        ]
        self.assertEqual(aa._delta_alerts(rows, 1), 2)
        self.assertEqual(aa._delta_alerts(rows, 2), 5)
        self.assertIsNone(aa._delta_alerts(rows, 24))

    def test_clamp_hours(self):
        self.assertEqual(aa.clamp_hours("abc"), aa.DEFAULT_HOURS)
        self.assertEqual(aa.clamp_hours(1), aa.MIN_HOURS)
        self.assertEqual(aa.clamp_hours(99999), aa.MAX_HOURS)

    def test_regional_limiares(self):
        snap = {
            "regions": [{
                "regiao_id": 1, "regiao_nome": "R1", "sigla_rodovia": "SP-055",
                "hid24h_breaks": [70, 80, 120, 143], "cpc_breaks": [1, 6, 12, 24],
            }],
            "points": [
                {"regiao_id": 1, "hazard": "geo", "rd": 2,
                 "ac24h_mm": 75.0, "ac96h_mm": 90.0, "intensity_mmh": 3.0,
                 "cpc": 7.0},
                {"regiao_id": 1, "hazard": "geo", "rd": 0,
                 "ac24h_mm": 10.0, "ac96h_mm": 12.0, "intensity_mmh": 0.5,
                 "cpc": 0.2},
                {"regiao_id": 1, "hazard": "hidro", "rd": 1,
                 "ac24h_mm": 75.0},
                {"regiao_id": 9, "hazard": "geo", "rd": 0},
            ],
        }
        out = aa._regional(snap)
        self.assertEqual(out["points_unassigned"], 1)
        r = out["regions"][0]
        self.assertEqual(r["uas_geo"], 2)
        self.assertEqual(r["uas_hidro"], 1)
        self.assertEqual(r["levels_geo"], [1, 0, 1, 0, 0])
        self.assertEqual(r["ac24h_max"], 75.0)
        self.assertEqual(r["hid_level_by_rain"], 1)
        self.assertEqual(r["hid_next_break"], 80)
        self.assertEqual(r["hid_margin_mm"], 5.0)
        self.assertEqual(r["cpc_level"], 2)

    def test_fire_horizons_transicoes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)

        def _fc(pairs):
            return json.dumps({"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {
                    "trecho_id": t, "rf_classe": c}}
                for t, c in pairs
            ]})
        (root / "obs.geojson").write_text(
            _fc([(1, "baixo"), (2, "alto"), (3, "SEM_DADO")]), "utf-8")
        (root / "d1.geojson").write_text(
            _fc([(1, "critico"), (2, "medio"), (3, "SEM_DADO")]), "utf-8")
        files = (
            ("observado", root / "obs.geojson"),
            ("D+1", root / "d1.geojson"),
            ("D+2", root / "missing.geojson"),
        )
        with mock.patch.object(aa, "FIRE_HORIZON_FILES", files), \
                mock.patch.dict(aa._fire_cache, {"key": None, "value": None}):
            out = aa._fire_horizons()
        self.assertTrue(out["available"])
        self.assertEqual([h["horizon"] for h in out["horizons"]],
                         ["observado", "D+1"])
        self.assertEqual(out["horizons"][0]["classes"]["SEM_DADO"], 1)
        tr = out["transitions"][0]
        self.assertEqual((tr["worsen"], tr["improve"], tr["same"]), (1, 1, 0))

    def test_ops_resumo(self):
        entries = [
            {"started_at": _ts(20), "outcome": "ok", "duration_s": 10,
             "files_ok": 96, "data_status": "ok"},
            {"started_at": _ts(10), "outcome": "error", "duration_s": 30,
             "files_ok": 48, "data_status": "degraded"},
        ]
        ops = aa._ops(entries, {"uptime_s": 5, "cycle_count": 2})
        self.assertEqual(ops["success_rate_pct"], 50.0)
        self.assertEqual(ops["degraded"], 1)
        self.assertEqual(ops["completeness_pct"], 75.0)
        self.assertEqual(ops["interval_p50_min"], 10.0)


class TestBuildAnalytics(unittest.TestCase):
    def test_payload_completo_sem_dados(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tel.reset_for_tests(Path(tmp.name))
        self.addCleanup(tel.reset_for_tests, Path(tmp.name))
        with mock.patch.object(aa.state, "get_rain_series",
                               return_value=None), \
                mock.patch.object(aa.state, "get_point_history",
                                  return_value={}):
            out = aa.build_analytics(
                {"uptime_s": 1, "cycle_count": 0}, hours=6,
            )
        self.assertEqual(out["window_hours"], 6)
        self.assertFalse(out["series"]["available"])
        self.assertFalse(out["hourly"]["available"])
        self.assertFalse(out["escalation"]["available"])
        self.assertIn("regional", out)
        self.assertIn("fire_horizons", out)
        self.assertIn("ops", out)


if __name__ == "__main__":
    unittest.main()
