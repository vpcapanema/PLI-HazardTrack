"""Protecao e catalogo da API publica."""

import os
import unittest
from unittest.mock import patch

from app import app  # noqa: E402


class PublicApiAuthTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_manifest_lists_fire_risk_endpoints(self):
        res = self.client.get("/api/public")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("fire_risk_layers", body["endpoints"])
        self.assertIn("auth", body)

    def test_open_mode_without_key(self):
        res = self.client.get("/api/public/fire-risk/snapshot")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Public-Api-Auth"), "open")

    @patch.dict(os.environ, {"PUBLIC_API_KEY": "segredo-teste"}, clear=False)
    def test_requires_key_when_configured(self):
        with app.app_context():
            app.config["TESTING"] = True
        res = self.client.get("/api/public/fire-risk/snapshot")
        self.assertEqual(res.status_code, 401)
        body = res.get_json()
        self.assertEqual(body["error"], "unauthorized")

    @patch.dict(os.environ, {"PUBLIC_API_KEY": "segredo-teste"}, clear=False)
    def test_accepts_x_api_key(self):
        res = self.client.get(
            "/api/public/fire-risk/snapshot",
            headers={"X-API-Key": "segredo-teste"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Public-Api-Auth"), "required")

    @patch.dict(os.environ, {"PUBLIC_API_KEY": "segredo-teste"}, clear=False)
    def test_accepts_bearer_token(self):
        res = self.client.get(
            "/api/public/fire-risk/layers",
            headers={"Authorization": "Bearer segredo-teste"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["type"], "FeatureCollection")


if __name__ == "__main__":
    unittest.main()
