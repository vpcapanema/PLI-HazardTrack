"""
Testes de regressao com cenarios oficiais do Produto 7 (Plano de Contingencia).

Fonte: Tabelas 3.3.3.1-3 (geologico) e 3.3.3.1-4 (hidrologico) do Relatorio
2053-R04-21 (Etapa 3), que validam a matriz RA x ICC -> RD em condicoes
reais de chuva.

CENARIO GEOLOGICO (Produto 7, item 3.3.3):
    I = 50 mm/h, Ac96h = 150 mm  (150^0.9 = 90.87)
    -> Regiao 1 (K=1000): CPC=4.54 -> ICCGEO2
    -> Regiao 2 (K=400):  CPC=11.36 -> ICCGEO2
    -> Regiao 3 (K=200):  CPC=22.72 -> ICCGEO3
    -> Regiao 4 (K=1000): CPC=4.54 -> ICCGEO2

CENARIO HIDROLOGICO (Produto 7, item 3.3.3):
    Ac24h = 100 mm
    -> Regioes 1, 4 permanecem ICCHID0
    -> Regioes 2, 3 atingem ICCHID2
"""

import os
import sys
import unittest
from importlib import import_module

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ferramentas", "relatorios-plano-contingencia"))

from core.risk import evaluate_point, rd_distribution, NIVEIS  # pylint: disable=wrong-import-position
from core.regions import APPROXIMATE_REGIONS, Region  # pylint: disable=wrong-import-position
get_ra_dist_for_point = import_module("ra_official").get_ra_dist_for_point


def _region(idx: int) -> Region:
    return Region(**APPROXIMATE_REGIONS[idx])


class TestCenarioGeologicoOficial(unittest.TestCase):
    """
    Cenario: I=50 mm/h, Ac96h=150 mm.
    Validacao contra Tabela 3.3.3.1-3 do Produto 7.
    """

    def test_regiao1_mogi_bertioga_iccgeo2(self):
        """Regiao 1 (SP-098): K=1000, breaks=[1,3,6,15]."""
        region = _region(0)
        r = evaluate_point(
            lat=-23.5, lon=-46.0, region=region,
            ac96h=150.0, intensity=50.0, ac24h=0.0, ra_geo=1
        )
        # 150^0.9 = 90.87 -> I_env = 1000 / 90.87 = 11.00
        # CPC = 50 / 11.00 = 4.54 -> ICCGEO2 (3 <= 4.54 < 6)
        self.assertEqual(r.icc_geo, 2)
        self.assertEqual(r.rd_geo, 2)  # RA=1 x ICC2 -> RD2

    def test_regiao2_caraguatatuba_iccgeo2(self):
        """Regiao 2 (SP-055): K=400, breaks=[1,6,12,24]."""
        region = _region(1)
        r = evaluate_point(
            lat=-23.5, lon=-45.0, region=region,
            ac96h=150.0, intensity=50.0, ac24h=0.0, ra_geo=1
        )
        # 150^0.9 = 90.87 -> I_env = 400 / 90.87 = 4.402
        # CPC = 50 / 4.402 = 11.36 -> ICCGEO2 (6 <= 11.36 < 12)
        self.assertEqual(r.icc_geo, 2)
        self.assertEqual(r.rd_geo, 2)  # RA=1 x ICC2 -> RD2

    def test_regiao3_sao_sebastiao_iccgeo3(self):
        """Regiao 3 (SP-055): K=200, breaks=[1,8,16,24]."""
        region = _region(2)
        r = evaluate_point(
            lat=-23.78, lon=-45.51, region=region,
            ac96h=150.0, intensity=50.0, ac24h=0.0, ra_geo=1
        )
        # 150^0.9 = 90.87 -> I_env = 200 / 90.87 = 2.201
        # CPC = 50 / 2.201 = 22.72 -> ICCGEO3 (16 <= 22.72 < 24)
        self.assertEqual(r.icc_geo, 3)
        self.assertEqual(r.rd_geo, 3)  # RA=1 x ICC3 -> RD3

    def test_regiao4_santos_bertioga_iccgeo2(self):
        """Regiao 4 (SP-055): K=1000, breaks=[1,4,8,16]."""
        region = _region(3)
        r = evaluate_point(
            lat=-23.9, lon=-46.2, region=region,
            ac96h=150.0, intensity=50.0, ac24h=0.0, ra_geo=1
        )
        # 150^0.9 = 90.87 -> I_env = 1000 / 90.87 = 11.00
        # CPC = 50 / 11.00 = 4.54 -> ICCGEO2 (4 <= 4.54 < 8)
        self.assertEqual(r.icc_geo, 2)
        self.assertEqual(r.rd_geo, 2)  # RA=1 x ICC2 -> RD2


class TestCenarioHidrologicoOficial(unittest.TestCase):
    """
    Cenario: Ac24h = 100 mm.
    Validacao contra Tabela 3.3.3.1-4 do Produto 7.
    """

    def test_regiao1_mogi_bertioga_icchid0(self):
        """Regiao 1: hid breaks [110,160,200,280]. Ac24h=100 < 110 -> ICCHID0."""
        region = _region(0)
        r = evaluate_point(
            lat=-23.5, lon=-46.0, region=region,
            ac96h=0.0, intensity=0.0, ac24h=100.0, ra_hid=1
        )
        self.assertEqual(r.icc_hid, 0)
        self.assertEqual(r.rd_hid, 0)

    def test_regiao2_caraguatatuba_icchid2(self):
        """Regiao 2: hid breaks [70,80,120,143]. 80<=100<120 -> ICCHID2."""
        region = _region(1)
        r = evaluate_point(
            lat=-23.5, lon=-45.0, region=region,
            ac96h=0.0, intensity=0.0, ac24h=100.0, ra_hid=1
        )
        self.assertEqual(r.icc_hid, 2)
        self.assertEqual(r.rd_hid, 2)  # RA=1 x ICC2 -> RD2

    def test_regiao3_sao_sebastiao_icchid2(self):
        """Regiao 3: hid breaks [60,85,110,126]. 85<=100<110 -> ICCHID2."""
        region = _region(2)
        r = evaluate_point(
            lat=-23.78, lon=-45.51, region=region,
            ac96h=0.0, intensity=0.0, ac24h=100.0, ra_hid=1
        )
        self.assertEqual(r.icc_hid, 2)
        self.assertEqual(r.rd_hid, 2)

    def test_regiao4_santos_bertioga_icchid0(self):
        """Regiao 4: hid breaks [150,200,230,300]. 100 < 150 -> ICCHID0."""
        region = _region(3)
        r = evaluate_point(
            lat=-23.9, lon=-46.2, region=region,
            ac96h=0.0, intensity=0.0, ac24h=100.0, ra_hid=1
        )
        self.assertEqual(r.icc_hid, 0)
        self.assertEqual(r.rd_hid, 0)


class TestCenarioTrechoCriticoSaoSebastiao(unittest.TestCase):
    """
    Cenario critico do Produto 7 para trecho km 128-153 (Regiao 3).
    RA GEO1 (baixo) + ICCGEO3 -> RDGEO3 (Alerta).
    Validacao da matriz RA x ICC -> RD.
    """

    def test_ra1_icc3_da_rd3(self):
        region = _region(2)
        r = evaluate_point(
            lat=-23.78, lon=-45.51, region=region,
            ac96h=150.0, intensity=50.0, ac24h=100.0,
            ra_geo=1, ra_hid=1
        )
        # Geologico: ICCGEO=3, RA=1 -> RDGEO=3 (Alerta)
        self.assertEqual(r.rd_geo, 3)
        # Hidrologico: ICCHID=2, RA=1 -> RDHID=2 (Atenção)
        self.assertEqual(r.rd_hid, 2)
        # RD final = max
        self.assertEqual(r.rd, max(r.rd_geo, r.rd_hid))
        self.assertEqual(r.rd, 3)

    def test_ra4_icc3_da_rd4(self):
        """Trecho km 156-162 com RA GEO4 (muito alto)."""
        region = _region(2)
        r = evaluate_point(
            lat=-23.78, lon=-45.51, region=region,
            ac96h=150.0, intensity=50.0, ac24h=100.0,
            ra_geo=4, ra_hid=4
        )
        # Geologico: ICCGEO>=3, RA=4 -> RDGEO=4 (Alerta Maximo)
        self.assertEqual(r.rd_geo, 4)
        # Hidrologico: ICCHID=2, RA=4 -> RDHID=4 (Alerta Maximo)
        self.assertEqual(r.rd_hid, 4)
        self.assertEqual(r.rd, 4)
        self.assertEqual(r.nivel, NIVEIS[4])


class TestCenarioCombinadoOficial(unittest.TestCase):
    """
    Cenario combinado do Produto 7:
    - Geologico: I=50 mm/h, Ac96h=150 mm
    - Hidrologico: Ac24h=100 mm
    Validacao do RD final (max de geo e hid) para cada regiao.
    """

    def test_regiao1_rd_final(self):
        region = _region(0)
        r = evaluate_point(
            lat=-23.5, lon=-46.0, region=region,
            ac96h=150.0, intensity=50.0, ac24h=100.0, ra_geo=1, ra_hid=1
        )
        # Geo: ICCGEO=2 -> RDGEO=2; Hid: ICCHID=0 -> RDHID=0; RD=max=2
        self.assertEqual(r.rd, 2)

    def test_regiao2_rd_final(self):
        region = _region(1)
        r = evaluate_point(
            lat=-23.5, lon=-45.0, region=region,
            ac96h=150.0, intensity=50.0, ac24h=100.0, ra_geo=1, ra_hid=1
        )
        # Geo: ICCGEO=2 -> RDGEO=2; Hid: ICCHID=2 -> RDHID=2; RD=max=2
        self.assertEqual(r.rd, 2)

    def test_regiao3_rd_final(self):
        region = _region(2)
        r = evaluate_point(
            lat=-23.78, lon=-45.51, region=region,
            ac96h=150.0, intensity=50.0, ac24h=100.0, ra_geo=1, ra_hid=1
        )
        # Geo: ICCGEO=3 -> RDGEO=3; Hid: ICCHID=2 -> RDHID=2; RD=max=3
        self.assertEqual(r.rd, 3)

    def test_regiao4_rd_final(self):
        region = _region(3)
        r = evaluate_point(
            lat=-23.9, lon=-46.2, region=region,
            ac96h=150.0, intensity=50.0, ac24h=100.0, ra_geo=1, ra_hid=1
        )
        # Geo: ICCGEO=2 -> RDGEO=2; Hid: ICCHID=0 -> RDHID=0
        self.assertEqual(r.rd, 2)


class TestDistribuicaoRDOficial(unittest.TestCase):
    """
    Valida a DISTRIBUICAO de Unidades de Analise por nivel de RD contra as
    colunas "Risco Dinamico (RD)" das Tabelas 3.3.3.1-3 e 3.3.3.1-4 (Produto 7).

    Esta e a validacao mais forte: reproduz numero a numero o resultado oficial
    do cenario proposto, garantindo que o motor de risco por distribuicao esta
    fiel ao relatorio.
    """

    def test_caraguatatuba_geo_icc2(self):
        # Tabela 3.3.3.1-3, trecho 53,6-102 sob ICCGEO2:
        # RD0=7, RD2=95, RD3=12, RD4=61 (33+28 que ja eram + gradacoes)
        dist = {0: 7, 1: 95, 2: 12, 3: 28, 4: 33}
        self.assertEqual(
            rd_distribution(dist, 2), {0: 7, 2: 95, 3: 12, 4: 61}
        )

    def test_sao_sebastiao_128_153_geo_icc3(self):
        # Tabela 3.3.3.1-3, trecho 128-153 sob ICCGEO3:
        # RD0=4, RD3=32, RD4=99
        dist = {0: 4, 1: 32, 2: 29, 3: 29, 4: 41}
        self.assertEqual(rd_distribution(dist, 3), {0: 4, 3: 32, 4: 99})

    def test_mogi_bertioga_geo_icc2(self):
        # Tabela 3.3.3.1-3, trecho 77-98 sob ICCGEO2:
        # RD0=1, RD2=53, RD3=5, RD4=22 (6+16)
        dist = {0: 1, 1: 53, 2: 5, 3: 6, 4: 16}
        self.assertEqual(
            rd_distribution(dist, 2), {0: 1, 2: 53, 3: 5, 4: 22}
        )

    def test_santos_bertioga_hid_bug_corrigido(self):
        # Bug: RA HID0 era 75 (na verdade era o RD HID0 do cenario).
        # Tabela 3.3.3.1-4 trecho 191,4-223,6: RA HID0=4, HID1=67, HID2=1, HID3=3
        d = get_ra_dist_for_point("SP 055", 200.0)
        self.assertEqual(d["dist_hid"], {0: 4, 1: 67, 2: 1, 3: 3, 4: 0})
        # Maior classe presente = HID3 (nao HID0)
        self.assertEqual(d["ra_hid_max"], 3)

    def test_mogi_bertioga_hid_presente(self):
        # Regressao: distribuicao hidrologica de SP-098 estava ausente.
        d = get_ra_dist_for_point("SP 098", 85.0)
        self.assertEqual(d["dist_hid"], {0: 60, 1: 59, 2: 5, 3: 2, 4: 0})
        self.assertEqual(d["ra_hid_max"], 3)


class TestAntiSubAlerta(unittest.TestCase):
    """
    Garante que um trecho heterogeneo (moda baixa, mas com UAs de risco muito
    alto) NAO seja sub-alertado: o RD do trecho deve refletir o pior caso.
    """

    def test_distribuicao_eleva_para_pior_caso(self):
        # Caraguatatuba (Regiao 2): moda RA GEO1, mas existem 33 UAs RA GEO4.
        # Sob ICCGEO2, a moda daria RD2 (Atencao); o pior caso deve dar RD4.
        region = _region(1)
        dist = {0: 7, 1: 95, 2: 12, 3: 28, 4: 33}
        r = evaluate_point(
            lat=-23.5, lon=-45.0, region=region,
            ac96h=150.0, intensity=50.0, ac24h=0.0,
            ra_geo_dist=dist,
        )
        self.assertEqual(r.icc_geo, 2)
        self.assertEqual(r.rd_geo, 4)        # pior caso, nao a moda (2)
        self.assertEqual(r.rd, 4)
        self.assertEqual(r.nivel, NIVEIS[4])
        # 61 UAs estao no nivel de pior caso (RD4)
        self.assertEqual(r.rd_unidades, 61)
        self.assertEqual(r.rd_geo_dist, {0: 7, 2: 95, 3: 12, 4: 61})

    def test_moda_escalar_ra_geo_sub_alertaria(self):
        # Prova do perigo: usando apenas RAGEO=1 (moda), o mesmo trecho
        # sob ICCGEO2 ficaria em RD2 (Atencao) - sub-alerta dos 61 criticos.
        region = _region(1)
        r = evaluate_point(
            lat=-23.5, lon=-45.0, region=region,
            ac96h=150.0, intensity=50.0, ac24h=0.0, ra_geo=1,
        )
        self.assertEqual(r.rd_geo, 2)  # escalar unico (perigoso vs distrib.)

    def test_sem_ra_geo_nem_hid_e_sem_dado(self):
        region = _region(0)
        r = evaluate_point(
            lat=-23.5, lon=-46.0, region=region,
            ac96h=150.0, intensity=50.0, ac24h=100.0,
        )
        self.assertEqual(r.nivel, "SEM DADO - RA nao mapeado")
        self.assertIsNone(r.ra)


if __name__ == "__main__":
    unittest.main()
