"""
Testes do pipeline de ZONAS (UAs aproximadas) que substituem os pontos.

Valida:
- carregamento e schema das zonas digitalizadas;
- integridade geometrica e de RA;
- integracao no aggregator (snapshot por zona, com geometria);
- calibracao hibrida (zonas em trecho critico mapeado vem da tabela oficial).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.zones import ZONES  # noqa: E402  # pylint: disable=wrong-import-position


class TestZonasSchema(unittest.TestCase):
    def test_carrega_zonas(self):
        self.assertGreater(len(ZONES), 100, "esperado muitas zonas")

    def test_schema_minimo(self):
        req = {"id", "nome", "rodovia", "km", "regiao", "lat", "lon",
               "ra", "ra_geo", "ra_hid", "ra_source", "geometry"}
        for z in ZONES:
            self.assertTrue(req.issubset(z.keys()), f"faltam campos em {z}")

    def test_geometria_valida(self):
        for z in ZONES:
            self.assertIsInstance(z["geometry"], list)
            self.assertGreaterEqual(len(z["geometry"]), 2)
            for lat, lon in z["geometry"]:
                # area de estudo (litoral norte/baixada SP)
                self.assertTrue(-25 < lat < -22, f"lat fora da area: {lat}")
                self.assertTrue(-47 < lon < -44, f"lon fora da area: {lon}")

    def test_ra_em_dominio(self):
        for z in ZONES:
            for k in ("ra", "ra_geo", "ra_hid"):
                v = z[k]
                if v is not None:
                    self.assertIn(v, (0, 1, 2, 3, 4), f"{k}={v} invalido")

    def test_ra_e_max_dos_canais(self):
        # ra exibido deve ser o pior caso entre geo e hid (anti-sub-alerta)
        for z in ZONES:
            canais = [v for v in (z["ra_geo"], z["ra_hid"]) if v is not None]
            if canais:
                self.assertEqual(z["ra"], max(canais), f"ra != max em {z['id']}")

    def test_sem_zona_sem_dado(self):
        # zonas None foram descartadas no pipeline
        self.assertTrue(all(z["ra"] is not None for z in ZONES))


class TestZonasHibrido(unittest.TestCase):
    def test_existe_zona_calibrada_por_tabela(self):
        fontes = {z["ra_source"] for z in ZONES}
        self.assertTrue(any("tabela" in f for f in fontes),
                        "esperado zonas calibradas pela tabela oficial")

    def test_existe_zona_da_figura(self):
        fontes = {z["ra_source"] for z in ZONES}
        self.assertTrue(any("figura" in f for f in fontes),
                        "esperado zonas preenchidas pela figura")


class TestIntegracaoAggregator(unittest.TestCase):
    def test_snapshot_usa_zonas(self):
        from core.aggregator import state
        snap = state.get_snapshot()
        pts = snap["points"]
        self.assertEqual(len(pts), len(ZONES))
        # cada item do snapshot carrega a geometria da zona
        self.assertTrue(all(p.get("geometry") for p in pts))


if __name__ == "__main__":
    unittest.main()
