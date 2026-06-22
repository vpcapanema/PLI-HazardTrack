"""Testes para core/der_cameras (normalizacao e validacao HLS)."""
from __future__ import annotations

import unittest
from unittest import mock

from core import der_cameras as dc


class TestNormalizeCamera(unittest.TestCase):
    def test_campos_derivados(self):
        out = dc.normalize_camera({
            "id": 5,
            "rodovia": "SP 055",
            "km": "KM 073+000",
            "nome": "Doutor Manoel Hypollito Rego",
            "local": "UBATUBA",
            "lat": -23.518319,
            "lng": -45.201084,
            "status": 1,
            "sentido": "MARANDUBA",
        })
        self.assertEqual(out["label"], "SP 055 · KM 073+000")
        self.assertEqual(out["stream_path"], "cam_5/stream.m3u8")
        self.assertFalse(out["maintenance"])
        self.assertTrue(out["online"])

    def test_manutencao(self):
        out = dc.normalize_camera({"id": 1, "status": 2})
        self.assertTrue(out["maintenance"])
        self.assertFalse(out["online"])


class TestValidateHlsPath(unittest.TestCase):
    def test_valido(self):
        self.assertEqual(
            dc.validate_hls_path("cam_5/stream.m3u8"),
            "cam_5/stream.m3u8",
        )

    def test_rejeita_traversal(self):
        self.assertIsNone(dc.validate_hls_path("../etc/passwd"))
        self.assertIsNone(dc.validate_hls_path("cam_5/../../x.m3u8"))


class TestFetchCameras(unittest.TestCase):
    def test_cache_hit(self):
        dc._CACHE.cameras = [{"id": 1}]  # noqa: SLF001
        dc._CACHE.at = __import__("time").time()  # noqa: SLF001
        with mock.patch("core.der_cameras.requests.get") as mget:
            cams, cached = dc.fetch_cameras()
        mget.assert_not_called()
        self.assertTrue(cached)
        self.assertEqual(len(cams), 1)


if __name__ == "__main__":
    unittest.main()
