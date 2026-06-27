"""Testes de formatacao do painel admin."""

import unittest
from datetime import datetime, timezone

from core.admin_format import (
    format_date_br,
    format_datetime_br,
    sanitize_source_path,
)


class AdminFormatTests(unittest.TestCase):
    def test_format_datetime_br(self):
        dt = datetime(2026, 6, 27, 18, 30, 45, tzinfo=timezone.utc)
        out = format_datetime_br(dt)
        self.assertRegex(out, r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$")

    def test_format_date_br_iso(self):
        self.assertEqual(format_date_br("2026-06-27"), "27/06/2026")

    def test_sanitize_source_path(self):
        raw = r"D:\REPOSITORIOS\PLI-HazardTrack\data\queimadas\processed\x.gpkg"
        self.assertEqual(
            sanitize_source_path(raw),
            "data/queimadas/processed/x.gpkg",
        )


if __name__ == "__main__":
    unittest.main()
