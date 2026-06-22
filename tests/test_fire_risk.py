import unittest

from core.fire_risk import get_fire_risk_geojson, get_fire_risk_snapshot


class FireRiskFeedTest(unittest.TestCase):
    def test_snapshot_loads_public_fire_risk(self):
        snap = get_fire_risk_snapshot()
        self.assertEqual(snap["modulo"], "queimadas")
        self.assertGreater(snap["total_trechos"], 0)
        self.assertIn(snap["data_status"], {"ok", "no_data"})

    def test_geojson_loads_public_fire_risk_layer(self):
        body = get_fire_risk_geojson()
        self.assertEqual(body["type"], "FeatureCollection")
        self.assertGreater(len(body["features"]), 0)
        first = body["features"][0]["properties"]
        self.assertIn("trecho_id", first)
        self.assertIn("rf_classe", first)


if __name__ == "__main__":
    unittest.main()
