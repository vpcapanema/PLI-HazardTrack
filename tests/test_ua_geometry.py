"""Geometria das UAs: sem cordas longas nem sobreposicao."""
import json
import math
import unittest
from pathlib import Path

from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "ua_zones" / "ua_geo.geojson"


def _max_edge_m(geom, lat):
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    mx = 0.0
    for poly in polys:
        coords = list(poly.exterior.coords)
        for i in range(len(coords) - 1):
            a, b = coords[i], coords[i + 1]
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            mx = max(mx, d * 111320 * math.cos(math.radians(lat)))
    return mx


def _overlap_pairs(feats, min_m2=0.5):
    polys = []
    for f in feats:
        g = shape(f["geometry"]).buffer(0)
        polys.append(g)
    tree = STRtree(polys)
    pairs = []
    for i, pi in enumerate(polys):
        for j in tree.query(pi):
            if j <= i:
                continue
            inter = pi.intersection(polys[j])
            if not inter.is_empty and inter.area > min_m2:
                pairs.append((feats[i]["properties"]["id"],
                              feats[j]["properties"]["id"],
                              inter.area))
    return pairs


@unittest.skipUnless(GEO.exists(), "ua_geo.geojson ausente")
class TestUaGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(GEO.read_text(encoding="utf-8"))
        cls.feats = cls.data["features"]

    def test_total_809(self):
        self.assertEqual(len(self.feats), 809)

    def test_no_long_chords_r3(self):
        r3 = [f for f in self.feats if f["properties"].get("regiao") == 3]
        bad = []
        for f in r3:
            g = shape(f["geometry"])
            lat = g.centroid.y
            mx = _max_edge_m(g, lat)
            if mx > 2000:
                bad.append((f["properties"]["id"], mx))
        self.assertEqual(bad, [], f"cordas >2 km: {bad}")

    def test_no_overlaps_globally(self):
        pairs = _overlap_pairs(self.feats)
        self.assertEqual(pairs, [], f"sobreposicoes: {pairs[:5]}")


if __name__ == "__main__":
    unittest.main()
