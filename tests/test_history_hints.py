"""Testes das sugestoes de consulta historica."""
import unittest

from core.history_hints import DEMO_HISTORY_EVENTS, get_history_hints


class TestHistoryHints(unittest.TestCase):
    def test_events_tem_campos_obrigatorios(self):
        for ev in DEMO_HISTORY_EVENTS:
            self.assertIn("at_utc", ev)
            self.assertIn("label", ev)
            self.assertIn("max_level", ev)
            self.assertGreaterEqual(ev["max_level"], 3)

    def test_get_history_hints_retorna_lista(self):
        data = get_history_hints()
        self.assertIn("events", data)
        self.assertGreaterEqual(len(data["events"]), 1)
        self.assertIn("disclaimer", data)


if __name__ == "__main__":
    unittest.main()
