"""Progresso agregado das barras totais de download."""
import unittest

from core.merge_inpe import _file_progress_fraction, _progress_aggregate


class TestMergeProgress(unittest.TestCase):
    def test_pending_zero(self):
        self.assertEqual(_file_progress_fraction({"status": "pending"}), 0.0)

    def test_downloading_com_pct(self):
        f = {"status": "downloading", "pct": 50, "bytes_done": 5000}
        self.assertAlmostEqual(_file_progress_fraction(f), 0.51, places=2)

    def test_decoding_quase_pronto(self):
        self.assertEqual(_file_progress_fraction({"status": "decoding"}), 0.94)

    def test_ok_completo(self):
        self.assertEqual(_file_progress_fraction({"status": "ok"}), 1.0)

    def test_aggregate_misto(self):
        from core.merge_inpe import _PROGRESS, _PROGRESS_LOCK
        with _PROGRESS_LOCK:
            saved = dict(_PROGRESS)
            _PROGRESS.update({
                "files": [
                    {"status": "ok"},
                    {"status": "downloading", "pct": 50, "bytes_done": 1},
                    {"status": "pending"},
                ],
                "total": 3,
                "done": 1,
            })
            agg = _progress_aggregate()
            _PROGRESS.clear()
            _PROGRESS.update(saved)
        self.assertGreater(agg["batch_pct"], 33.0)
        self.assertLess(agg["batch_pct"], 67.0)


if __name__ == "__main__":
    unittest.main()
