"""Testes de codificacao e unidades DER nos popups."""

import unittest

from core.text_encoding import fix_text
from core.der_units import lookup_der_units, format_uba_display


class TestTextEncoding(unittest.TestCase):
    def test_fix_mojibake(self):
        bad = "SÃ£o SebastiÃ£o"
        self.assertEqual(fix_text(bad), "São Sebastião")

    def test_fix_plain_passthrough(self):
        self.assertEqual(fix_text("Caraguatatuba"), "Caraguatatuba")


class TestDerUnits(unittest.TestCase):
    def test_ua_mogi_bertioga_tem_uba(self):
        units = lookup_der_units(-23.756, -46.039, "SP 098", 90.269)
        self.assertTrue(
            units.get("regional_cgr") or units.get("regional"),
            "CGR deve ser identificada",
        )
        self.assertTrue(
            units.get("rc") or units.get("residencia_conserva"),
            "RC deve ser identificada",
        )
        label = format_uba_display(units)
        self.assertNotEqual(label, "—")


if __name__ == "__main__":
    unittest.main()
