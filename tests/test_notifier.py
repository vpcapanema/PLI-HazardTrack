"""
Testes do servico de notificacao (core/notifier.py).

Cobre: desabilitado sem config; selecao por limiar; anti-spam (cooldown);
escalada de nivel; de-escalada; ignorar NO_DATA. Sem rede (canais stubbados).
"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notifier import Notifier  # noqa: E402  # pylint: disable=wrong-import-position

# pylint: disable=protected-access


def _zone(zid, rd, source="MERGE/INPE"):
    return {
        "id": zid, "nome": zid, "rodovia": "SP 055", "km": 100.0,
        "rd": rd, "nivel": f"N{rd}", "ra": rd,
        "lat": -23.8, "lon": -45.4, "ac24h_mm": 50, "ac96h_mm": 120,
        "region_name": "R", "source": source,
    }


def _make_enabled():
    n = Notifier()
    n.enabled_webhook = True
    n.enabled_email = False
    n.threshold = 3
    n.cooldown = timedelta(hours=6)
    n.sent = []
    n._send_webhook = lambda *a, **k: True
    n._send_email = lambda *a, **k: True
    return n


class TestNotifierDisabled(unittest.TestCase):
    def test_desabilitado_sem_config(self):
        n = Notifier()
        n.enabled_email = False
        n.enabled_webhook = False
        out = n.evaluate([_zone("Z1", 4)], {"max_rd": 4})
        self.assertEqual(out, 0)


class TestNotifierSelecao(unittest.TestCase):
    def setUp(self):
        self.n = _make_enabled()
        self.t0 = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)

    def test_alerta_novo_acima_limiar(self):
        out = self.n.evaluate([_zone("Z1", 3), _zone("Z2", 1)],
                              {"max_rd": 3}, self.t0)
        self.assertEqual(out, 1)

    def test_abaixo_limiar_nao_alerta(self):
        out = self.n.evaluate([_zone("Z2", 2)], {"max_rd": 2}, self.t0)
        self.assertEqual(out, 0)

    def test_no_data_ignorado(self):
        out = self.n.evaluate([_zone("Z1", 4, source="NO_DATA")],
                              {"max_rd": 0}, self.t0)
        self.assertEqual(out, 0)

    def test_cooldown_evita_repeticao(self):
        self.n.evaluate([_zone("Z1", 3)], {"max_rd": 3}, self.t0)
        # 1h depois, mesmo nivel -> nao reenvia
        out = self.n.evaluate([_zone("Z1", 3)], {"max_rd": 3},
                              self.t0 + timedelta(hours=1))
        self.assertEqual(out, 0)

    def test_escalada_reenvia(self):
        self.n.evaluate([_zone("Z1", 3)], {"max_rd": 3}, self.t0)
        out = self.n.evaluate([_zone("Z1", 4)], {"max_rd": 4},
                              self.t0 + timedelta(hours=1))
        self.assertEqual(out, 1)

    def test_lembrete_apos_cooldown(self):
        self.n.evaluate([_zone("Z1", 3)], {"max_rd": 3}, self.t0)
        out = self.n.evaluate([_zone("Z1", 3)], {"max_rd": 3},
                              self.t0 + timedelta(hours=7))
        self.assertEqual(out, 1)

    def test_desescalada_limpa_estado(self):
        self.n.evaluate([_zone("Z1", 4)], {"max_rd": 4}, self.t0)
        # caiu abaixo do limiar -> some do estado
        self.n.evaluate([_zone("Z1", 1)], {"max_rd": 1},
                        self.t0 + timedelta(hours=1))
        self.assertNotIn("Z1", self.n._last_alert)
        # volta a subir -> alerta novo
        out = self.n.evaluate([_zone("Z1", 3)], {"max_rd": 3},
                              self.t0 + timedelta(hours=2))
        self.assertEqual(out, 1)

    def test_status_tem_chaves(self):
        st = self.n.get_status()
        for k in ("enabled_email", "enabled_webhook", "threshold",
                  "cooldown_h", "sent_total"):
            self.assertIn(k, st)


if __name__ == "__main__":
    unittest.main()
