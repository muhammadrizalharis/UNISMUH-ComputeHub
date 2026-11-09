"""Tes endpoint /metrics (observability Prometheus).

Mandiri: membangun app FastAPI minimal, memasang setup_metrics, lalu memeriksa
gerbang token + keluaran metrik. Tidak menyentuh DB.
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient


class MetricsEndpointTest(unittest.TestCase):
    def _build(self, token: str = "") -> TestClient:
        from app.core import metrics as metrics_mod
        from app.core.config import settings

        settings.METRICS_ENABLED = True
        settings.METRICS_TOKEN = token

        app = FastAPI()

        @app.get("/ping")
        async def ping() -> dict:
            return {"ok": True}

        metrics_mod.setup_metrics(app, version="test")
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_metrics_exposed_without_token(self):
        client = self._build(token="")
        client.get("/ping")
        resp = client.get("/metrics")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("computehub_http_requests_total", body)
        self.assertIn("computehub_app_info", body)
        self.assertIn("process_resident_memory_bytes", body)

    def test_token_required_when_set(self):
        client = self._build(token="rahasia")
        self.assertEqual(client.get("/metrics").status_code, 403)
        self.assertEqual(
            client.get("/metrics?token=salah").status_code, 403
        )
        ok = client.get("/metrics", headers={"Authorization": "Bearer rahasia"})
        self.assertEqual(ok.status_code, 200)
        ok2 = client.get("/metrics?token=rahasia")
        self.assertEqual(ok2.status_code, 200)

    def test_request_counter_increments(self):
        client = self._build(token="")
        for _ in range(3):
            client.get("/ping")
        body = client.get("/metrics").text
        # Label path dinormalisasi ke template route (/ping), status 200.
        line = [
            ln
            for ln in body.splitlines()
            if ln.startswith("computehub_http_requests_total{")
            and 'path="/ping"' in ln
            and 'status="200"' in ln
        ]
        self.assertTrue(line, "metrik request /ping tidak ditemukan")
        self.assertGreaterEqual(float(line[0].rsplit(" ", 1)[1]), 3.0)

    def test_skip_prefixes_not_counted(self):
        client = self._build(token="")
        client.get("/metrics")
        body = client.get("/metrics").text
        self.assertNotIn('path="/metrics"', body)


if __name__ == "__main__":
    unittest.main()
