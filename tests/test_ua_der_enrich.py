"""Atributos administrativos DER nas UAs (NATIVOS de uas_area_estudo).

Garante que as informacoes de DR (residencia DER), UBA e sede regional
sao propagadas em todas as UAs do GeoJSON consumido pelo backend.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "ua_zones" / "ua_geo.geojson"
HID = ROOT / "data" / "ua_zones" / "ua_hidro.geojson"


class TestUaDerAttributes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GEO.exists():
            raise unittest.SkipTest("ua_geo.geojson ausente")
        cls.data = json.loads(GEO.read_text(encoding="utf-8"))

    def test_geojson_tem_colunas_der_nativas(self):
        feat = self.data["features"][0]["properties"]
        for key in (
            "regional", "residencia_dr", "uba_codigo", "uba_nome",
            "municipio", "jurisdicao", "conservado_por", "subtrecho_der",
        ):
            self.assertIn(key, feat, f"falta atributo nativo {key}")

    def test_cobertura_total_dos_administrativos(self):
        props = [f["properties"] for f in self.data["features"]]
        with_dr = sum(1 for p in props if p.get("residencia_dr"))
        with_regional = sum(1 for p in props if p.get("regional"))
        with_uba = sum(
            1 for p in props if p.get("uba_codigo") or p.get("uba_nome")
        )
        # A camada uas_area_estudo herda os admins por construcao;
        # exigimos cobertura total (sem buracos por interpolacao).
        self.assertEqual(with_dr, len(props), "DR esperado em 100% das UAs")
        self.assertEqual(with_regional, len(props),
                         "Regional DER esperado em 100% das UAs")
        self.assertEqual(with_uba, len(props),
                         "UBA esperada em 100% das UAs")

    def test_valores_de_dr_conhecidos(self):
        props = [f["properties"] for f in self.data["features"]]
        drs = {p["residencia_dr"] for p in props}
        self.assertTrue(drs.issubset({"DR 05", "DR 06", "DR 10"}),
                        f"DRs inesperados: {drs}")


if __name__ == "__main__":
    unittest.main()
