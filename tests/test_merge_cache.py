"""Testes para core/merge_cache (cache em disco + politica de refetch).

Cobre:
- coords_hash determinismo + sensibilidade a mudancas
- round-trip de GRIB e samples
- atomicidade (nada de .tmp orfao)
- sanidade de tamanho (GRIB curto -> recusado)
- should_refetch nos limites (fresh, mid c/s last_check, stale)
- prune_old respeita TTL
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from core import merge_cache as mc


def _utc(y: int, m: int, d: int, h: int) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


class TestCoordsHash(unittest.TestCase):
    def test_deterministico(self):
        lats = [-23.5, -23.6, -23.7]
        lons = [313.7, 313.6, 313.5]
        self.assertEqual(
            mc.coords_hash(lats, lons),
            mc.coords_hash(lats, lons),
        )

    def test_sensivel_a_n_pontos(self):
        a = mc.coords_hash([-23.5, -23.6], [313.7, 313.6])
        b = mc.coords_hash([-23.5, -23.6, -23.7], [313.7, 313.6, 313.5])
        self.assertNotEqual(a, b)

    def test_sensivel_a_valor(self):
        a = mc.coords_hash([-23.5], [313.7])
        b = mc.coords_hash([-23.5001], [313.7])
        self.assertNotEqual(a, b)

    def test_formato(self):
        h = mc.coords_hash([-23.5], [313.7])
        self.assertEqual(len(h), 12)
        int(h, 16)  # so digitos hex


class _TmpCacheMixin(unittest.TestCase):
    """Redireciona CACHE_ROOT/GRIB_DIR/SAMPLES_DIR para tmpdir."""

    def _patch_cache_root(self, root: Path) -> None:
        self._patches = [
            mock.patch.object(mc, "CACHE_ROOT", root),
            mock.patch.object(mc, "GRIB_DIR", root / "grib"),
            mock.patch.object(mc, "SAMPLES_DIR", root / "samples"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)


class TestGribRoundtrip(_TmpCacheMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch_cache_root(Path(self._tmp.name))

    def test_write_then_read(self):
        dt = _utc(2026, 6, 22, 5)
        data = b"GRIB" + (b"x" * 5000)
        mc.write_grib(dt, data)
        out = mc.read_grib(dt)
        self.assertEqual(out, data)

    def test_read_inexistente(self):
        self.assertIsNone(mc.read_grib(_utc(2026, 6, 22, 5)))

    def test_recusa_grib_curto_no_write(self):
        dt = _utc(2026, 6, 22, 5)
        mc.write_grib(dt, b"curto")
        self.assertIsNone(mc.read_grib(dt))

    def test_recusa_grib_curto_no_read(self):
        dt = _utc(2026, 6, 22, 5)
        path = mc.GRIB_DIR / "2026-06-22" / "05.grib2"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 100)
        self.assertIsNone(mc.read_grib(dt))

    def test_atomico_sem_tmp_orfao(self):
        dt = _utc(2026, 6, 22, 5)
        mc.write_grib(dt, b"GRIB" + b"x" * 5000)
        leftovers = list(mc.GRIB_DIR.rglob("*.tmp"))
        self.assertEqual(leftovers, [])


class TestSamplesRoundtrip(_TmpCacheMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch_cache_root(Path(self._tmp.name))
        self.chash = "abc123def456"
        self.dt = _utc(2026, 6, 22, 5)

    def test_write_then_read(self):
        samples = [0.0, 0.5, 2.7, 12.3]
        mc.write_samples(self.chash, self.dt, samples)
        out = mc.read_samples(self.chash, self.dt)
        self.assertEqual(out, samples)

    def test_read_inexistente(self):
        self.assertIsNone(mc.read_samples(self.chash, self.dt))

    def test_recusa_vazio(self):
        mc.write_samples(self.chash, self.dt, [])
        self.assertIsNone(mc.read_samples(self.chash, self.dt))

    def test_isola_por_coords_hash(self):
        mc.write_samples(self.chash, self.dt, [1.0, 2.0])
        self.assertIsNone(mc.read_samples("outro_hash000", self.dt))

    def test_metadados_no_payload(self):
        mc.write_samples(self.chash, self.dt, [0.1, 0.2])
        path = mc._samples_path(self.chash, self.dt)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["coords_hash"], self.chash)
        self.assertEqual(payload["n"], 2)
        self.assertIn("hour_utc", payload)
        self.assertEqual(payload["samples"], [0.1, 0.2])

    def test_arredondamento_4_casas(self):
        mc.write_samples(self.chash, self.dt, [1.123456789])
        out = mc.read_samples(self.chash, self.dt)
        self.assertEqual(out, [1.1235])

    def test_json_corrompido_retorna_none(self):
        path = mc._samples_path(self.chash, self.dt)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ nao eh json valido", encoding="utf-8")
        self.assertIsNone(mc.read_samples(self.chash, self.dt))

    def test_atomico_sem_tmp_orfao(self):
        mc.write_samples(self.chash, self.dt, [1.0, 2.0])
        leftovers = list(mc.SAMPLES_DIR.rglob("*.tmp"))
        self.assertEqual(leftovers, [])


class TestShouldRefetch(unittest.TestCase):
    def setUp(self):
        self.now = _utc(2026, 6, 22, 12)

    def test_fresh_sempre_refetch(self):
        for age_h in [0, 1, 2, 3]:
            dt = self.now - timedelta(hours=age_h)
            self.assertTrue(
                mc.should_refetch(dt, self.now),
                f"idade {age_h}h deveria refazer",
            )

    def test_stale_nunca_refetch(self):
        for age_h in [24, 48, 96, 720]:
            dt = self.now - timedelta(hours=age_h)
            self.assertFalse(
                mc.should_refetch(dt, self.now),
                f"idade {age_h}h NAO deveria refazer",
            )

    def test_mid_sem_last_check_refetch(self):
        dt = self.now - timedelta(hours=10)
        self.assertTrue(mc.should_refetch(dt, self.now, last_check=None))

    def test_mid_check_recente_nao_refetch(self):
        dt = self.now - timedelta(hours=10)
        last = self.now - timedelta(hours=1)
        self.assertFalse(mc.should_refetch(dt, self.now, last_check=last))

    def test_mid_check_antigo_refetch(self):
        dt = self.now - timedelta(hours=10)
        last = self.now - timedelta(hours=25)
        self.assertTrue(mc.should_refetch(dt, self.now, last_check=last))

    def test_aceita_naive_datetime(self):
        dt_naive = self.now.replace(tzinfo=None) - timedelta(hours=2)
        self.assertTrue(mc.should_refetch(dt_naive, self.now))

    def test_now_default_eh_utc(self):
        dt = datetime.now(timezone.utc) - timedelta(hours=1)
        self.assertTrue(mc.should_refetch(dt))


class TestPruneOld(_TmpCacheMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch_cache_root(Path(self._tmp.name))

    def test_prune_desativado_quando_ttl_zero(self):
        with mock.patch.object(mc, "CACHE_TTL_DAYS", 0):
            n_g, n_s = mc.prune_old()
            self.assertEqual((n_g, n_s), (0, 0))

    def test_remove_arquivos_antigos(self):
        old = _utc(2025, 1, 1, 0)
        recent = _utc(2026, 6, 22, 5)
        mc.write_grib(old, b"GRIB" + b"x" * 5000)
        mc.write_grib(recent, b"GRIB" + b"y" * 5000)
        # Forca mtime antigo
        old_path = mc._grib_path(old)
        ts_old = (old.timestamp())
        import os as _os
        _os.utime(old_path, (ts_old, ts_old))

        now = _utc(2026, 6, 22, 12)
        with mock.patch.object(mc, "CACHE_TTL_DAYS", 30):
            n_g, _ = mc.prune_old(now=now)
        self.assertEqual(n_g, 1)
        self.assertIsNone(mc.read_grib(old))
        self.assertIsNotNone(mc.read_grib(recent))

    def test_preserva_arquivos_recentes(self):
        dt = _utc(2026, 6, 22, 5)
        mc.write_grib(dt, b"GRIB" + b"x" * 5000)
        now = _utc(2026, 6, 22, 12)
        with mock.patch.object(mc, "CACHE_TTL_DAYS", 30):
            n_g, n_s = mc.prune_old(now=now)
        self.assertEqual((n_g, n_s), (0, 0))
        self.assertIsNotNone(mc.read_grib(dt))


class TestDiskStats(_TmpCacheMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch_cache_root(Path(self._tmp.name))

    def test_vazio(self):
        stats = mc.disk_stats()
        self.assertEqual(stats["grib_files"], 0)
        self.assertEqual(stats["sample_files"], 0)
        self.assertEqual(stats["bytes_total"], 0)

    def test_conta_arquivos(self):
        dt = _utc(2026, 6, 22, 5)
        mc.write_grib(dt, b"GRIB" + b"x" * 5000)
        mc.write_samples("abc123def456", dt, [1.0, 2.0])
        stats = mc.disk_stats()
        self.assertEqual(stats["grib_files"], 1)
        self.assertEqual(stats["sample_files"], 1)
        self.assertGreater(stats["bytes_total"], 5000)


if __name__ == "__main__":
    unittest.main()
