"""Geometria das UAs (linhas): integridade do GeoJSON ua_geo.

A camada `uas_area_estudo` e composta por LineStrings. Este teste valida
apenas a integridade basica do GeoJSON consumido pelo backend.
"""
import json
import unittest
from pathlib import Path

from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "ua_zones" / "ua_geo.geojson"
HID = ROOT / "data" / "ua_zones" / "ua_hidro.geojson"


@unittest.skipUnless(GEO.exists(), "ua_geo.geojson ausente")
class TestUaGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_geo = json.loads(GEO.read_text(encoding="utf-8"))
        cls.feats_geo = cls.data_geo["features"]
        cls.data_hid = json.loads(HID.read_text(encoding="utf-8"))
        cls.feats_hid = cls.data_hid["features"]

    def test_total_809(self):
        self.assertEqual(len(self.feats_geo), 809)
        self.assertEqual(len(self.feats_hid), 809)

    def test_geometria_linestring(self):
        for f in self.feats_geo:
            g = shape(f["geometry"])
            self.assertIn(g.geom_type, ("LineString", "MultiLineString"))
            self.assertGreater(g.length, 0)

    def test_ua_ids_unicos(self):
        ids = [f["properties"]["ua_id"] for f in self.feats_geo]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
