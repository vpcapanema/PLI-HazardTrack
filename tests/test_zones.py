"""
Testes do pipeline de ZONAS (UAs) - malhas geo e hidro separadas.

Valida:
- Carregamento e schema das duas malhas mono-canal a partir dos
  GeoJSONs gerados pelo `04_export_ua_geojsons.py` (atributos
  NATIVOS de uas_area_estudo);
- Integridade geometrica e de RA por canal;
- Integracao no aggregator (snapshot points_geo / points_hidro).
"""
import os
import sys
import unittest

sys.path.insert(0,
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.zones import ZONES_GEO, ZONES_HIDRO  # noqa: E402


class TestZonasSchema(unittest.TestCase):
    def test_carrega_zonas(self):
        self.assertEqual(len(ZONES_GEO), 809, "esperado 809 UAs geo")
        self.assertEqual(len(ZONES_HIDRO), 809, "esperado 809 UAs hidro")

    def test_schema_nativo_minimo_geo(self):
        req = {
            "ua_id", "regiao_id", "regiao_nome", "sigla_rodovia",
            "escala", "tipo", "extensao_km", "km_inicial", "km_final",
            "subtrecho_der", "municipio", "regional", "residencia_dr",
            "uba_nome", "uba_codigo",
            "RAGEO", "icc_geo_thresholds", "trecho_critico_geo",
            "hazard", "geometry", "geometry_type",
        }
        for z in ZONES_GEO:
            self.assertTrue(
                req.issubset(z.keys()),
                f"faltam campos em {z.get('ua_id')}: "
                f"{req - z.keys()}",
            )

    def test_schema_nativo_minimo_hidro(self):
        req = {
            "ua_id", "regiao_id", "regiao_nome", "sigla_rodovia",
            "escala", "tipo", "extensao_km", "km_inicial", "km_final",
            "subtrecho_der", "municipio", "regional", "residencia_dr",
            "uba_nome", "uba_codigo",
            "RAHID", "icc_hid_thresholds", "trecho_critico_hid",
            "hazard", "geometry", "geometry_type",
        }
        for z in ZONES_HIDRO:
            self.assertTrue(
                req.issubset(z.keys()),
                f"faltam campos em {z.get('ua_id')}: "
                f"{req - z.keys()}",
            )

    def test_hazard_por_malha(self):
        self.assertTrue(all(z["hazard"] == "geo" for z in ZONES_GEO))
        self.assertTrue(all(z["hazard"] == "hidro" for z in ZONES_HIDRO))

    def test_geometria_valida(self):
        for z in ZONES_GEO + ZONES_HIDRO:
            self.assertIsInstance(z["geometry"], list)
            self.assertGreaterEqual(len(z["geometry"]), 2)
            for lat, lon in z["geometry"]:
                self.assertTrue(-25 < lat < -22,
                                f"lat fora da area: {lat}")
                self.assertTrue(-47 < lon < -44,
                                f"lon fora da area: {lon}")

    def test_RAGEO_em_dominio(self):
        for z in ZONES_GEO:
            v = z["RAGEO"]
            self.assertIsNotNone(v)
            self.assertIn(v, (0, 1, 2, 3, 4),
                          f"RAGEO={v} invalido em {z['ua_id']}")

    def test_RAHID_em_dominio(self):
        for z in ZONES_HIDRO:
            v = z["RAHID"]
            self.assertIsNotNone(v)
            # RAHID oficial vai ate 3 (sem nivel 4 mapeado)
            self.assertIn(v, (0, 1, 2, 3),
                          f"RAHID={v} invalido em {z['ua_id']}")

    def test_ua_ids_pareados(self):
        ids_geo = {z["ua_id"] for z in ZONES_GEO}
        ids_hid = {z["ua_id"] for z in ZONES_HIDRO}
        self.assertEqual(ids_geo, ids_hid)

    def test_icc_thresholds_parseados(self):
        # icc_geo_thresholds deve ser lista de 4 floats (4 limites = 5 classes)
        for z in ZONES_GEO[:5]:
            t = z["icc_geo_thresholds"]
            self.assertIsInstance(t, list)
            self.assertEqual(len(t), 4)
            self.assertTrue(all(isinstance(x, float) for x in t))
        for z in ZONES_HIDRO[:5]:
            t = z["icc_hid_thresholds"]
            self.assertIsInstance(t, list)
            self.assertEqual(len(t), 4)


class TestIntegracaoAggregator(unittest.TestCase):
    def test_snapshot_usa_zonas(self):
        from core.aggregator import state
        snap = state.get_snapshot()
        geo = snap["points_geo"]
        hidro = snap["points_hidro"]
        self.assertEqual(len(geo), len(ZONES_GEO))
        self.assertEqual(len(hidro), len(ZONES_HIDRO))
        self.assertTrue(all(p.get("geometry") for p in geo + hidro))

    def test_snapshot_propaga_atributos_nativos(self):
        from core.aggregator import state
        snap = state.get_snapshot()
        for p in snap["points_geo"][:3]:
            self.assertIn("ua_id", p)
            self.assertIn("sigla_rodovia", p)
            self.assertIn("regiao_nome", p)
            self.assertIn("km_inicial", p)
            self.assertIn("km_final", p)
            self.assertIn("residencia_dr", p)
            self.assertIn("uba_codigo", p)
            self.assertIn("RAGEO", p)
        for p in snap["points_hidro"][:3]:
            self.assertIn("RAHID", p)


if __name__ == "__main__":
    unittest.main()
