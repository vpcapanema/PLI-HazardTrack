"""
Testes da composicao observado+previsto do Risco Dinamico, conforme o
Produto 6 (secao 4.5.3) do Plano de Contingencia:

  - Geologico:  Ac96h   = 72h observadas (MERGE) + 24h previstas (WRF)
  - Hidrologico: Soma24h = 18h observadas (MERGE) + 6h previstas (WRF)
  - Intensidade usada no CPC = observada (a previsao NAO altera I)

Tambem testa a degradacao transparente quando a previsao esta indisponivel.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.risk import compose_pdf_windows, evaluate_point  # noqa: E402  # pylint: disable=wrong-import-position
from core.regions import Region  # noqa: E402  # pylint: disable=wrong-import-position


class TestComposicaoJanelas(unittest.TestCase):
    def test_com_previsao_segue_pdf(self):
        ac96, ac24, fonte = compose_pdf_windows(
            ac72h_obs=100.0, ac18h_obs=40.0,
            ac96h_obs=110.0, ac24h_obs=55.0,
            prev24h_mm=30.0, prev6h_mm=12.0,
        )
        # 96h = 72h obs + 24h prev ; 24h = 18h obs + 6h prev
        self.assertEqual(ac96, 130.0)   # 100 + 30
        self.assertEqual(ac24, 52.0)    # 40 + 12
        self.assertEqual(fonte, "WRF")

    def test_nao_usa_96h_observado_quando_ha_previsao(self):
        # Deve usar 72h+prev, NAO o 96h observado (evita dupla contagem)
        ac96, _, _ = compose_pdf_windows(
            ac72h_obs=100.0, ac18h_obs=40.0,
            ac96h_obs=999.0, ac24h_obs=55.0,
            prev24h_mm=30.0, prev6h_mm=12.0,
        )
        self.assertEqual(ac96, 130.0)
        self.assertNotEqual(ac96, 999.0)

    def test_sem_previsao_degrada_observado(self):
        ac96, ac24, fonte = compose_pdf_windows(
            ac72h_obs=100.0, ac18h_obs=40.0,
            ac96h_obs=110.0, ac24h_obs=55.0,
            prev24h_mm=None, prev6h_mm=None,
        )
        self.assertEqual(ac96, 110.0)
        self.assertEqual(ac24, 55.0)
        self.assertEqual(fonte, "OBS_ONLY")

    def test_previsao_parcial_e_tratada_como_indisponivel(self):
        # Se faltar um dos componentes, nao compoe (degrada)
        _, _, fonte = compose_pdf_windows(
            ac72h_obs=100.0, ac18h_obs=40.0,
            ac96h_obs=110.0, ac24h_obs=55.0,
            prev24h_mm=30.0, prev6h_mm=None,
        )
        self.assertEqual(fonte, "OBS_ONLY")


class TestComposicaoElevaRisco(unittest.TestCase):
    """A previsao deve poder ELEVAR o RD em relacao ao observado puro
    (e o ponto central do PDF: antecipar o evento)."""

    def _region(self):
        return Region(
            id=2, nome="Caraguatatuba-Ubatuba", rodovia="SP 055",
            k_geo=1.0,
            cpc_breaks=[0.2, 0.4, 0.6, 0.8],
            hid24h_breaks=[30, 60, 90, 120],
            polygon=[(-24.0, -45.5), (-24.0, -45.0),
                     (-23.5, -45.0), (-23.5, -45.5)],
        )

    def test_previsao_aumenta_icc_hid(self):
        region = self._region()
        # observado 24h = 18h obs (20mm) -> ICC baixo
        # com previsao: 20 + 80 prev = 100mm -> ICC mais alto
        obs = evaluate_point(
            lat=-23.7, lon=-45.4, region=region,
            ac96h=50.0, intensity=1.0, ac24h=20.0, ra_hid=2,
        )
        composto_ac24 = 20.0 + 80.0
        prev = evaluate_point(
            lat=-23.7, lon=-45.4, region=region,
            ac96h=50.0, intensity=1.0, ac24h=composto_ac24, ra_hid=2,
        )
        self.assertGreater(prev.icc_hid, obs.icc_hid)
        self.assertGreaterEqual(prev.rd, obs.rd)


if __name__ == "__main__":
    unittest.main()
