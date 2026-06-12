"""
Testes do pipeline de ZONAS (UAs) — malhas geo e hidro separadas.

Valida:
- carregamento e schema das duas malhas mono-canal;
- integridade geometrica e de RA por canal;
- integracao no aggregator (snapshot points_geo / points_hidro).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.zones import ZONES_GEO, ZONES_HIDRO  # noqa: E402


class TestZonasSchema(unittest.TestCase):
    def test_carrega_zonas(self):
        self.assertEqual(len(ZONES_GEO), 809, "esperado 809 UAs geo")
        self.assertEqual(len(ZONES_HIDRO), 809, "esperado 809 UAs hidro")

    def test_schema_minimo(self):
        req = {"id", "nome", "rodovia", "km", "regiao", "lat", "lon",
               "ra", "hazard", "ra_source", "geometry"}
        for z in ZONES_GEO + ZONES_HIDRO:
            self.assertTrue(req.issubset(z.keys()), f"faltam campos em {z}")

    def test_hazard_por_malha(self):
        self.assertTrue(all(z["hazard"] == "geo" for z in ZONES_GEO))
        self.assertTrue(all(z["hazard"] == "hidro" for z in ZONES_HIDRO))

    def test_geometria_valida(self):
        for z in ZONES_GEO + ZONES_HIDRO:
            self.assertIsInstance(z["geometry"], list)
            self.assertGreaterEqual(len(z["geometry"]), 2)
            for lat, lon in z["geometry"]:
                self.assertTrue(-25 < lat < -22, f"lat fora da area: {lat}")
                self.assertTrue(-47 < lon < -44, f"lon fora da area: {lon}")

    def test_ra_em_dominio(self):
        for z in ZONES_GEO + ZONES_HIDRO:
            v = z["ra"]
            self.assertIsNotNone(v)
            self.assertIn(v, (0, 1, 2, 3, 4), f"ra={v} invalido em {z['id']}")

    def test_ids_pareados(self):
        ids_geo = {z["id"] for z in ZONES_GEO}
        ids_hid = {z["id"] for z in ZONES_HIDRO}
        self.assertEqual(ids_geo, ids_hid)


class TestZonasHibrido(unittest.TestCase):
    def test_existe_zona_calibrada_por_tabela(self):
        fontes = {z["ra_source"] for z in ZONES_GEO + ZONES_HIDRO}
        self.assertTrue(any("tabela" in f for f in fontes),
                        "esperado zonas calibradas pela tabela oficial")

    def test_existe_zona_da_figura(self):
        fontes = {z["ra_source"] for z in ZONES_GEO + ZONES_HIDRO}
        self.assertTrue(any("figura" in f for f in fontes),
                        "esperado zonas preenchidas pela figura")


class TestIntegracaoAggregator(unittest.TestCase):
    def test_snapshot_usa_zonas(self):
        from core.aggregator import state
        snap = state.get_snapshot()
        geo = snap["points_geo"]
        hidro = snap["points_hidro"]
        self.assertEqual(len(geo), len(ZONES_GEO))
        self.assertEqual(len(hidro), len(ZONES_HIDRO))
        self.assertTrue(all(p.get("geometry") for p in geo + hidro))


if __name__ == "__main__":
    unittest.main()
