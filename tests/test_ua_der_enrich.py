"""Testes de enriquecimento DER nas UAs."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "ua_zones" / "ua_geo.geojson"


class TestUaDerAttributes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GEO.exists():
            raise unittest.SkipTest("ua_geo.geojson ausente")
        cls.data = json.loads(GEO.read_text(encoding="utf-8"))

    def test_geojson_tem_colunas_der(self):
        feat = self.data["features"][0]["properties"]
        for key in ("cgr", "rc", "uba", "uba_codigo", "residencia_conserva"):
            self.assertIn(key, feat, f"falta atributo {key} na UA")

    def test_maioria_com_rc_e_cgr(self):
        props = [f["properties"] for f in self.data["features"]]
        with_rc = sum(1 for p in props if p.get("rc"))
        with_cgr = sum(1 for p in props if p.get("cgr"))
        self.assertGreater(with_rc, 700, "RC deveria cobrir a maioria das UAs")
        self.assertGreater(with_cgr, 700, "CGR deveria cobrir a maioria das UAs")

    def test_ua_r3_074_tem_unidades_der(self):
        match = [
            f["properties"] for f in self.data["features"]
            if f["properties"].get("id") == "UA-R3-074"
        ]
        self.assertEqual(len(match), 1)
        p = match[0]
        self.assertTrue(p.get("rc"))
        self.assertTrue(p.get("cgr"))
        self.assertTrue(p.get("uba_codigo") or p.get("uba"))


if __name__ == "__main__":
    unittest.main()
