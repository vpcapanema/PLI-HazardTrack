"""Testes da chuva por pluviometros (core/gauge_primary) sem tocar a rede."""
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core import gauge_primary as gp

NOW = datetime(2026, 9, 15, 19, 4, tzinfo=timezone.utc)
TARGET = datetime(2026, 9, 15, 18, tzinfo=timezone.utc)
POINT = (-23.5, -45.5)


@dataclass
class FakeRain:
    intensity_mmh: float = 0.0
    ac18h_mm: float = 1.0
    ac24h_mm: float = 1.0
    ac72h_mm: float = 3.0
    ac96h_mm: float = 4.0
    source: str = "MERGE/INPE"


def _hours(n):
    return [TARGET - timedelta(hours=h) for h in range(n)]


def _constant(value, n=96):
    return {h: value for h in _hours(n)}


class TestHelpers(unittest.TestCase):
    def test_parse_hour_utc(self):
        self.assertEqual(
            gp.parse_hour("2026/09/15 18"), TARGET,
        )
        self.assertIsNone(gp.parse_hour(None))
        self.assertIsNone(gp.parse_hour("15/09/2026"))

    def test_target_is_last_complete_hour(self):
        self.assertEqual(gp.target_hour_for(NOW), TARGET)

    def test_idw_ignores_station_without_reading(self):
        stations = {"a": (-23.5, -45.45), "b": (-23.5, -45.55)}
        values = {"a": _constant(1.0), "b": _constant(1.0)}
        values["a"][TARGET] = 4.0
        del values["b"][TARGET]
        ps = gp.build_point_series([POINT], stations, values, TARGET)[0]
        self.assertIsNotNone(ps)
        assert ps is not None
        self.assertAlmostEqual(ps.series[0], 4.0, places=3)
        self.assertTrue(ps.covered_target)
        self.assertEqual(ps.stations, 2)


class TestApplyGaugePrimary(unittest.TestCase):
    def _run(self, stations, values):
        rain = [FakeRain()]
        with patch.object(gp.store, "refresh"), patch.object(
            gp.store, "data",
            return_value=(stations, values, TARGET, None),
        ):
            meta, used = gp.apply_gauge_primary([POINT], rain, NOW)
        return meta, used, rain[0]

    def test_replaces_rain_with_gauge_windows(self):
        values = {"1": _constant(1.0)}
        values["1"][TARGET] = 5.0
        meta, used, rain = self._run({"1": POINT}, values)
        self.assertEqual(used, [0])
        self.assertTrue(meta.applied)
        self.assertEqual(meta.stations_last_hour, 1)
        self.assertEqual(rain.intensity_mmh, 5.0)
        self.assertEqual(rain.ac18h_mm, 22.0)
        self.assertEqual(rain.ac24h_mm, 28.0)
        self.assertEqual(rain.ac72h_mm, 76.0)
        self.assertEqual(rain.ac96h_mm, 100.0)
        self.assertEqual(rain.source, gp.SOURCE_LABEL)

    def test_insufficient_coverage_keeps_merge(self):
        values = {"1": _constant(1.0, n=12)}
        meta, used, rain = self._run({"1": POINT}, values)
        self.assertEqual(used, [])
        self.assertEqual(meta.points_fallback, 1)
        self.assertEqual(rain, FakeRain())

    def test_missing_target_hour_keeps_merge(self):
        values = {"1": _constant(1.0)}
        del values["1"][TARGET]
        _, used, rain = self._run({"1": POINT}, values)
        self.assertEqual(used, [])
        self.assertEqual(rain, FakeRain())

    def test_no_station_in_radius_keeps_merge(self):
        values = {"far": _constant(1.0)}
        _, used, rain = self._run({"far": (-10.0, -50.0)}, values)
        self.assertEqual(used, [])
        self.assertEqual(rain, FakeRain())

    def test_api_failure_keeps_merge(self):
        rain = [FakeRain()]
        with patch.object(
            gp.store, "refresh", side_effect=RuntimeError("fora do ar"),
        ):
            meta, used = gp.apply_gauge_primary([POINT], rain, NOW)
        self.assertEqual(used, [])
        self.assertEqual(meta.error, "fora do ar")
        self.assertEqual(rain[0], FakeRain())

    def test_disabled_returns_untouched(self):
        rain = [FakeRain()]
        with patch.object(gp, "ENABLED", False):
            meta, used = gp.apply_gauge_primary([POINT], rain, NOW)
        self.assertFalse(meta.enabled)
        self.assertEqual(used, [])
        self.assertEqual(rain[0], FakeRain())


class TestGaugeSeriesStore(unittest.TestCase):
    def test_full_then_skip_then_incremental(self):
        store = gp.GaugeSeriesStore()
        calls = []

        def fake_hourly(ids, start, end):
            calls.append((list(ids), start, end))
            return {"1": {start: 1.0, TARGET: 2.0}}

        stations = {"1": POINT, "far": (-10.0, -50.0)}
        with patch.object(
            gp, "_fetch_station_list", return_value=stations,
        ) as st, patch.object(
            gp, "_fetch_hourly", side_effect=fake_hourly,
        ), patch.object(
            gp, "_now_mono", side_effect=[0.0, 100.0, 400.0],
        ):
            store.refresh([POINT], NOW)
            store.refresh([POINT], NOW + timedelta(minutes=5))
            store.refresh([POINT], NOW + timedelta(minutes=10))

        self.assertEqual(st.call_count, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], ["1"])
        self.assertEqual(calls[0][1], TARGET - timedelta(hours=95))
        self.assertEqual(calls[0][2], TARGET + timedelta(minutes=59))
        self.assertEqual(calls[1][1], TARGET - timedelta(hours=5))
        got_stations, values, target, _ = store.data()
        self.assertEqual(list(got_stations), ["1"])
        self.assertEqual(target, TARGET)
        self.assertIn(TARGET - timedelta(hours=95), values["1"])
        self.assertIn(TARGET - timedelta(hours=5), values["1"])
        self.assertEqual(values["1"][TARGET], 2.0)


if __name__ == "__main__":
    unittest.main()
