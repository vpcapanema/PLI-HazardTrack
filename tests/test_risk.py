"""
Testes unitarios deterministicos para core/risk.py.

Cobrem:
- calculate_cpc: formula CPC = I / (K * Ac96h^-0.9), bordas (chuva nula),
  diferenca entre regioes (K maior -> CPC menor para mesma chuva).
- classify_icc_geo / classify_icc_hid: limites das faixas 0..4.
- combine_ra_icc: matriz oficial RA x ICC (Tabela 3.2.1-1, REGEA-NIPPON 2021).
- evaluate_point: integracao ponto-a-ponto, incluindo regiao=None.
"""

import math
import os
import sys
import unittest

# Permite rodar via "python -m unittest" a partir da raiz do projeto.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.risk import (
    calculate_cpc,
    classify_icc_geo,
    classify_icc_hid,
    combine_ra_icc,
    evaluate_point,
    RD_MATRIX,
    NIVEIS,
)
from core.regions import APPROXIMATE_REGIONS, Region


def _region(idx: int) -> Region:
    return Region(**APPROXIMATE_REGIONS[idx])


class TestCalculateCPC(unittest.TestCase):
    def test_chuva_nula_retorna_zero(self):
        # Ac96h <= 0.5 mm e considerado "sem chuva relevante"
        self.assertEqual(calculate_cpc(intensity_mmh=0.0, ac96h_mm=0.0, k_geo=1000), 0.0)
        self.assertEqual(calculate_cpc(intensity_mmh=10.0, ac96h_mm=0.4, k_geo=1000), 0.0)
        self.assertEqual(calculate_cpc(intensity_mmh=10.0, ac96h_mm=0.5, k_geo=1000), 0.0)

    def test_intensidade_negativa_retorna_zero(self):
        # Sentinela defensiva
        self.assertEqual(calculate_cpc(intensity_mmh=-1.0, ac96h_mm=50.0, k_geo=1000), 0.0)

    def test_formula_envoltoria_basica(self):
        # I_env = K * Ac96h^-0.9; CPC = I / I_env
        # K=1000, Ac96h=100 -> I_env = 1000 * 100^-0.9 = 1000 / 100^0.9
        # 100^0.9 ~= 63.0957 -> I_env ~= 15.849
        # I=15 -> CPC ~= 0.9464
        cpc = calculate_cpc(intensity_mmh=15.0, ac96h_mm=100.0, k_geo=1000)
        self.assertAlmostEqual(cpc, 15.0 / (1000.0 * 100.0 ** -0.9), places=6)
        self.assertAlmostEqual(cpc, 0.9464, places=3)

    def test_regiao_mais_critica_tem_cpc_maior(self):
        # Mesma chuva, K menor (Sao Sebastiao K=200) tem envoltoria menor -> CPC maior
        cpc_mogi = calculate_cpc(intensity_mmh=15.0, ac96h_mm=100.0, k_geo=1000)  # R1
        cpc_sseb = calculate_cpc(intensity_mmh=15.0, ac96h_mm=100.0, k_geo=200)   # R3
        self.assertGreater(cpc_sseb, cpc_mogi)
        # Razao deve ser exatamente 5x (1000/200), porque K e linear no denominador
        self.assertAlmostEqual(cpc_sseb / cpc_mogi, 5.0, places=6)


class TestClassifyICCGeo(unittest.TestCase):
    # cpc_breaks da Regiao 1 = [1, 3, 6, 15]
    BREAKS = [1, 3, 6, 15]

    def test_faixa_0_abaixo_do_primeiro_break(self):
        self.assertEqual(classify_icc_geo(0.0, self.BREAKS), 0)
        self.assertEqual(classify_icc_geo(0.99, self.BREAKS), 0)

    def test_limites_inferiores_de_cada_faixa(self):
        # cpc < break[i] retorna i (limite inferior INclusivo da faixa i+1)
        self.assertEqual(classify_icc_geo(1.0, self.BREAKS), 1)   # 1..<3
        self.assertEqual(classify_icc_geo(3.0, self.BREAKS), 2)   # 3..<6
        self.assertEqual(classify_icc_geo(6.0, self.BREAKS), 3)   # 6..<15
        self.assertEqual(classify_icc_geo(15.0, self.BREAKS), 4)  # >=15

    def test_faixa_4_extremo(self):
        self.assertEqual(classify_icc_geo(100.0, self.BREAKS), 4)

    def test_cpc_none_retorna_zero(self):
        self.assertEqual(classify_icc_geo(None, self.BREAKS), 0)


class TestClassifyICCHid(unittest.TestCase):
    # hid24h_breaks da Regiao 3 (Sao Sebastiao) = [60, 85, 110, 126]
    BREAKS = [60, 85, 110, 126]

    def test_chuva_baixa_e_zero(self):
        self.assertEqual(classify_icc_hid(0.0, self.BREAKS), 0)
        self.assertEqual(classify_icc_hid(59.9, self.BREAKS), 0)

    def test_limites_de_faixa(self):
        self.assertEqual(classify_icc_hid(60.0, self.BREAKS), 1)
        self.assertEqual(classify_icc_hid(84.9, self.BREAKS), 1)
        self.assertEqual(classify_icc_hid(85.0, self.BREAKS), 2)
        self.assertEqual(classify_icc_hid(110.0, self.BREAKS), 3)
        self.assertEqual(classify_icc_hid(126.0, self.BREAKS), 4)
        self.assertEqual(classify_icc_hid(500.0, self.BREAKS), 4)


class TestCombineRAICC(unittest.TestCase):
    def test_matriz_oficial_completa(self):
        # Replica exata da tabela 3.2.1-1 do REGEA-NIPPON.
        expected = [
            [0, 0, 0, 0, 0],   # RA0
            [0, 1, 2, 3, 4],   # RA1
            [0, 2, 3, 4, 4],   # RA2
            [0, 3, 4, 4, 4],   # RA3
            [0, 4, 4, 4, 4],   # RA4
        ]
        for ra in range(5):
            for icc in range(5):
                self.assertEqual(
                    combine_ra_icc(ra, icc),
                    expected[ra][icc],
                    msg=f"RA={ra}, ICC={icc}"
                )

    def test_clamp_de_entradas_invalidas(self):
        # Valores fora de 0..4 devem ser clamped sem exception
        self.assertEqual(combine_ra_icc(-5, 2), RD_MATRIX[0][2])
        self.assertEqual(combine_ra_icc(2, 99), RD_MATRIX[2][4])
        self.assertEqual(combine_ra_icc(99, -3), RD_MATRIX[4][0])

    def test_ra_zero_sempre_da_rd_zero(self):
        for icc in range(5):
            self.assertEqual(combine_ra_icc(0, icc), 0)

    def test_icc_zero_sempre_da_rd_zero(self):
        # Conforme tabela, primeira coluna inteira e zero (sem chuva, sem alerta)
        for ra in range(5):
            self.assertEqual(combine_ra_icc(ra, 0), 0)


class TestEvaluatePoint(unittest.TestCase):
    def test_fora_de_cobertura_retorna_neutro(self):
        # region=None -> tudo zerado, nivel "Monitoramento"
        r = evaluate_point(
            lat=0.0, lon=0.0, region=None,
            ac96h=200.0, intensity=30.0, ac24h=180.0,
            ra_geo=4, ra_hid=4,
        )
        self.assertIsNone(r.region_id)
        self.assertEqual(r.rd, 0)
        self.assertEqual(r.nivel, "Fora de cobertura")

    def test_chuva_zero_da_rd_zero(self):
        region = _region(0)  # Regiao 1
        r = evaluate_point(
            lat=-23.7, lon=-46.1, region=region,
            ac96h=0.0, intensity=0.0, ac24h=0.0,
            ra_geo=4, ra_hid=4,
        )
        self.assertEqual(r.icc_geo, 0)
        self.assertEqual(r.icc_hid, 0)
        self.assertEqual(r.rd, 0)
        self.assertEqual(r.cpc, 0.0)

    def test_cenario_critico_sao_sebastiao(self):
        # Regiao 3: K=200, breaks=[1,8,16,24], hid breaks=[60,85,110,126]
        # Ac96h=300 mm, I=20 mm/h, Ac24h=130 mm
        # I_env = 200 * 300^-0.9 = 200 / 300^0.9 ~ 200 / 174.96 ~ 1.143
        # CPC = 20 / 1.143 ~ 17.5 -> ICC_geo = 3 (16<=17.5<24)
        # Ac24h=130 -> ICC_hid = 4 (>=126)
        # RA=1 -> RD_geo=3, RD_hid=4 -> RD=4 -> "Alerta Maximo"
        region = _region(2)
        r = evaluate_point(
            lat=-23.78, lon=-45.51, region=region,
            ac96h=300.0, intensity=20.0, ac24h=130.0,
            ra_geo=1, ra_hid=1,
        )
        self.assertEqual(r.region_id, 3)
        self.assertEqual(r.icc_geo, 3)
        self.assertEqual(r.icc_hid, 4)
        self.assertEqual(r.rd, 4)
        self.assertEqual(r.nivel, NIVEIS[4])
        self.assertGreater(r.cpc, 16.0)
        self.assertLess(r.cpc, 24.0)

    def test_rd_e_max_de_geo_e_hid(self):
        # Ac24h baixa (ICC_hid=0), CPC alta (ICC_geo>0): rd deve seguir o geo.
        region = _region(2)  # Sao Sebastiao
        r = evaluate_point(
            lat=-23.78, lon=-45.51, region=region,
            ac96h=300.0, intensity=20.0, ac24h=10.0,
            ra_geo=1, ra_hid=1,
        )
        self.assertEqual(r.icc_hid, 0)
        self.assertGreaterEqual(r.icc_geo, 3)
        self.assertEqual(r.rd, max(r.rd_geo, r.rd_hid))
        # Como ICC_hid=0, RD_hid=0 e RD = RD_geo
        self.assertEqual(r.rd, r.rd_geo)

    def test_sem_ra_oficial_retorna_sem_dado(self):
        region = _region(0)
        r = evaluate_point(
            lat=-23.7, lon=-46.1, region=region,
            ac96h=100.0, intensity=10.0, ac24h=50.0,
        )
        self.assertEqual(r.nivel, "SEM DADO - RA nao mapeado")
        self.assertIsNone(r.ra)


class TestRegionPolygons(unittest.TestCase):
    """
    Verifica que o gap entre Regiao 3 e 4 foi fechado.
    Antes do fix, SP055-C07 (-23.815, -45.810) caia em region=None.
    """

    def test_sp055_c07_pertence_a_regiao(self):
        from core.regions import find_region_for_point, load_regions
        regions = load_regions()
        r = find_region_for_point(-23.815, -45.810, regions)
        self.assertIsNotNone(r, "SP055-C07 nao deveria cair em region=None apos o fix")

    def test_pontos_de_sao_sebastiao_caem_na_regiao_3(self):
        from core.regions import find_region_for_point, load_regions
        regions = load_regions()
        # Maresias, Camburi, Juquehy
        for lat, lon in [(-23.745, -45.430), (-23.785, -45.510), (-23.810, -45.600)]:
            r = find_region_for_point(lat, lon, regions)
            self.assertIsNotNone(r)
            self.assertEqual(r.id, 3, msg=f"Esperado regiao 3 em ({lat}, {lon}), veio {r.id}")


if __name__ == "__main__":
    unittest.main()
