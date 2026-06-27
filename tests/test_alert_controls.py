"""Testes para core/alert_controls e sincronizacao fire_pipeline."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import alert_controls as ac
from core import fire_pipeline as fp


class TestAlertControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ac.RUNTIME_DIR = Path(self.tmp.name)
        ac.CONTROLS_PATH = ac.RUNTIME_DIR / "alert_controls.json"

    def test_defaults_ligados(self):
        st = ac.get_state()
        self.assertTrue(st["geo_monitoring"])
        self.assertTrue(st["fire_monitoring"])

    def test_desligar_e_religar(self):
        ac.set_system("geo_monitoring", False, actor="test")
        self.assertFalse(ac.is_geo_enabled())
        ac.set_system("geo_monitoring", True, actor="test")
        self.assertTrue(ac.is_geo_enabled())

    def test_persiste_em_disco(self):
        ac.set_system("fire_monitoring", False, actor="test")
        raw = json.loads(ac.CONTROLS_PATH.read_text(encoding="utf-8"))
        self.assertFalse(raw["fire_monitoring"])
        self.assertEqual(raw["updated_by"], "test")


class TestFireSync(unittest.TestCase):
    def test_is_synced_exige_ran_at(self):
        latest = "INPE_FireRiskModel_2.2_FireRisk_20260622.nc"
        with mock.patch.object(fp, "_products_exist", return_value=True), \
             mock.patch.object(fp, "_read_marker", return_value={
                 "observed_file": latest,
                 "ran_at": None,
             }), \
             mock.patch.object(fp, "_stats_reference_date", return_value="2026-06-22"):
            self.assertFalse(fp._is_synced(latest))

    def test_is_synced_ok_apos_processamento(self):
        latest = "INPE_FireRiskModel_2.2_FireRisk_20260622.nc"
        with mock.patch.object(fp, "_products_exist", return_value=True), \
             mock.patch.object(fp, "_read_marker", return_value={
                 "observed_file": latest,
                 "ran_at": "2026-06-22T12:00:00+00:00",
             }), \
             mock.patch.object(fp, "_stats_reference_date", return_value="2026-06-22"):
            self.assertTrue(fp._is_synced(latest))

    def test_file_reference_date(self):
        name = "INPE_FireRiskModel_2.2_FireRisk_20260622.nc"
        self.assertEqual(fp._file_reference_date(name), "2026-06-22")


if __name__ == "__main__":
    unittest.main()
