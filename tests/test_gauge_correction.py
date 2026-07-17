"""Testes da correcao por solo (core/gauge_correction) sem tocar a rede."""
import unittest
from dataclasses import dataclass

from core import gauge_correction as gc


@dataclass
class FakeRain:
    ac18h_mm: float
    ac24h_mm: float
    ac72h_mm: float
    ac96h_mm: float
    intensity_mmh: float


def _station(lat, lon, val, coverage_hours=24.0):
    return gc.GaugeStation(lat=lat, lon=lon, value_mm=val,
                           name="X", owner="CEMADEN", city="Y",
                           coverage_hours=coverage_hours)


class TestGaugeCorrection(unittest.TestCase):
    def setUp(self):
        gc._CACHE.clear()

    def _patch_stations(self, stations):
        gc._CACHE[gc.ANCHOR_HOURS] = (1e18, stations)  # nunca expira

    def test_downscale_when_gauge_much_lower(self):
        # Satelite 300mm, estacao colada mede 5mm -> deve reduzir forte.
        self._patch_stations([_station(-23.5, -45.5, 5.0)])
        rain = [FakeRain(295.0, 300.0, 320.0, 320.0, 0.0)]
        meta = gc.correct_rain_batch([(-23.5, -45.5)], rain)
        self.assertTrue(meta.applied)
        self.assertEqual(meta.points_corrected, 1)
        self.assertLess(rain[0].ac24h_mm, 300.0)
        # monotonicidade preservada
        self.assertLessEqual(rain[0].ac18h_mm, rain[0].ac24h_mm)
        self.assertLessEqual(rain[0].ac24h_mm, rain[0].ac72h_mm)
        self.assertLessEqual(rain[0].ac72h_mm, rain[0].ac96h_mm)

    def test_no_station_in_radius_keeps_satellite(self):
        # Estacao a >30km -> mantem satelite intacto.
        self._patch_stations([_station(-10.0, -50.0, 5.0)])
        rain = [FakeRain(295.0, 300.0, 320.0, 320.0, 0.0)]
        gc.correct_rain_batch([(-23.5, -45.5)], rain)
        self.assertEqual(rain[0].ac24h_mm, 300.0)

    def test_factor_clamped(self):
        # Estacao colada com valor absurdo nao explode alem de FACTOR_MAX.
        self._patch_stations([_station(-23.5, -45.5, 9999.0)])
        rain = [FakeRain(9.0, 10.0, 12.0, 12.0, 1.0)]
        gc.correct_rain_batch([(-23.5, -45.5)], rain)
        self.assertLessEqual(rain[0].ac24h_mm, 10.0 * gc.FACTOR_MAX + 0.01)

    def test_dry_consensus_overrides_extreme_satellite(self):
        stations = [
            _station(-23.50, -45.50, 0.0),
            _station(-23.51, -45.50, 0.0),
            _station(-23.49, -45.50, 0.0),
        ]
        self._patch_stations(stations)
        rain = [FakeRain(280.0, 300.0, 500.0, 600.0, 25.0)]
        meta = gc.correct_rain_batch([(-23.5, -45.5)], rain)
        self.assertEqual(meta.points_ground_override, 1)
        self.assertEqual(rain[0].ac24h_mm, 0.0)
        self.assertEqual(rain[0].intensity_mmh, 0.0)
        self.assertEqual(rain[0].ac72h_mm, 200.0)
        self.assertEqual(rain[0].ac96h_mm, 300.0)

    def test_dry_guard_requires_redundant_stations(self):
        self._patch_stations([_station(-23.5, -45.5, 0.0)])
        rain = [FakeRain(280.0, 300.0, 500.0, 600.0, 25.0)]
        meta = gc.correct_rain_batch([(-23.5, -45.5)], rain)
        self.assertEqual(meta.points_ground_override, 0)
        self.assertGreater(rain[0].ac24h_mm, 0.0)

    def test_dry_guard_ignores_stations_with_short_coverage(self):
        stations = [
            _station(-23.50, -45.50, 0.0, coverage_hours=4.0),
            _station(-23.51, -45.50, 0.0, coverage_hours=4.0),
            _station(-23.49, -45.50, 0.0, coverage_hours=4.0),
        ]
        self._patch_stations(stations)
        rain = [FakeRain(280.0, 300.0, 500.0, 600.0, 25.0)]
        meta = gc.correct_rain_batch([(-23.5, -45.5)], rain)
        self.assertEqual(meta.points_ground_override, 0)

    def test_both_dry_no_change(self):
        self._patch_stations([_station(-23.5, -45.5, 0.0)])
        rain = [FakeRain(0.0, 0.0, 0.0, 0.0, 0.0)]
        meta = gc.correct_rain_batch([(-23.5, -45.5)], rain)
        self.assertEqual(rain[0].ac24h_mm, 0.0)
        self.assertEqual(meta.points_corrected, 0)

    def test_disabled_returns_untouched(self):
        orig = gc.ENABLED
        gc.ENABLED = False
        try:
            rain = [FakeRain(295.0, 300.0, 320.0, 320.0, 0.0)]
            meta = gc.correct_rain_batch([(-23.5, -45.5)], rain)
            self.assertFalse(meta.applied)
            self.assertEqual(rain[0].ac24h_mm, 300.0)
        finally:
            gc.ENABLED = orig


if __name__ == "__main__":
    unittest.main()
