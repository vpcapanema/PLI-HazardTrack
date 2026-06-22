"""Feed publico GeoJSON das UAs."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.aggregator import state  # noqa: E402
from core.ua_public_feed import (  # noqa: E402
    build_ua_layers_geojson,
    point_to_feature,
)


class TestUaPublicFeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = state.get_snapshot()

    def test_feature_collection_schema(self):
        fc = build_ua_layers_geojson(self.snap)
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertIn("metadata", fc)
        self.assertIn("features", fc)
        # v2 = atributos NATIVOS de uas_area_estudo (ua_id, RAGEO, ...)
        self.assertEqual(fc["metadata"]["api_version"], "2")
        self.assertGreater(len(fc["features"]), 0)

    def test_geojson_coordinates_lon_lat(self):
        fc = build_ua_layers_geojson(self.snap, hazard="geo")
        feat = fc["features"][0]
        geom = feat["geometry"]
        self.assertIn(geom["type"], ("Polygon", "LineString"))
        if geom["type"] == "Polygon":
            lon, lat = geom["coordinates"][0][0]
        else:
            lon, lat = geom["coordinates"][0]
        self.assertTrue(-47 < lon < -44, f"lon={lon}")
        self.assertTrue(-25 < lat < -22, f"lat={lat}")

    def test_hazard_filter(self):
        geo = build_ua_layers_geojson(self.snap, hazard="geo")
        hid = build_ua_layers_geojson(self.snap, hazard="hidro")
        all_fc = build_ua_layers_geojson(self.snap, hazard="all")
        self.assertEqual(len(geo["features"]), 809)
        self.assertEqual(len(hid["features"]), 809)
        self.assertEqual(len(all_fc["features"]), 1618)
        self.assertTrue(
            all(p["properties"]["hazard"] == "geo"
                for p in geo["features"])
        )

    def test_min_rd_filter(self):
        fc = build_ua_layers_geojson(self.snap, min_rd=3)
        for feat in fc["features"]:
            self.assertGreaterEqual(int(feat["properties"]["rd"]), 3)

    def test_public_properties(self):
        fc = build_ua_layers_geojson(self.snap, hazard="geo")
        feat = fc["features"][0]
        props = feat["properties"]
        # Atributos NATIVOS da camada uas_area_estudo + calculados
        for key in (
            "ua_id", "sigla_rodovia", "regiao_id", "regiao_nome",
            "km_inicial", "km_final", "escala", "tipo",
            "municipio", "regional", "residencia_dr",
            "uba_codigo", "uba_nome",
            "RAGEO", "icc_geo_thresholds", "trecho_critico_geo",
            "rd", "nivel", "hazard",
        ):
            self.assertIn(key, props, f"falta {key}")
        # Feature ID = ua_id (sem campo legado "id" no properties)
        self.assertEqual(feat["id"], props["ua_id"])

    def test_hidro_public_properties(self):
        fc = build_ua_layers_geojson(self.snap, hazard="hidro")
        props = fc["features"][0]["properties"]
        for key in (
            "RAHID", "icc_hid_thresholds", "trecho_critico_hid",
        ):
            self.assertIn(key, props)
        self.assertNotIn("RAGEO", props)
        self.assertNotIn("icc_geo_thresholds", props)

    def test_point_to_feature_skips_empty(self):
        self.assertIsNone(point_to_feature({"ua_id": "x", "geometry": []}))


class TestPublicUaLayersRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["SAMAEG_DISABLE_BOOTSTRAP"] = "1"
        from app import app as flask_app  # noqa: E402
        cls.client = flask_app.test_client()

    def test_route_ok(self):
        res = self.client.get("/api/public/ua-layers?hazard=geo")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"FeatureCollection", res.data)
        self.assertIn(b"application/geo+json", res.content_type.encode())

    def test_route_invalid_min_rd(self):
        res = self.client.get("/api/public/ua-layers?min_rd=9")
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
