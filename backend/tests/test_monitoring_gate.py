"""Tes gerbang super-admin untuk endpoint monitoring (Prometheus proxy).

Memastikan admin biasa (bukan admin utama) menerima 403 sebelum endpoint
menyentuh Prometheus. Tidak memerlukan Prometheus berjalan.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace


class MonitoringGateTests(unittest.TestCase):
    def _client(self, *, is_superadmin: bool):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.deps import require_admin
        from app.api.routers import admin as admin_router

        app = FastAPI()
        app.include_router(admin_router.router, prefix="/admin")
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
            id=1, role="admin", is_superadmin=is_superadmin
        )
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_admin_biasa_ditolak(self):
        client = self._client(is_superadmin=False)
        self.assertEqual(
            client.get("/admin/ops/monitoring/summary").status_code, 403
        )
        self.assertEqual(
            client.get("/admin/ops/monitoring/series").status_code, 403
        )
        self.assertEqual(
            client.get("/admin/ops/monitoring/metrics").status_code, 403
        )
        self.assertEqual(
            client.get(
                "/admin/ops/monitoring/metric-series?name=computehub_app_info"
            ).status_code,
            403,
        )

    def test_metric_series_tolak_nama_tak_valid(self):
        # Gerbang super-admin lolos, tapi nama metrik tak diizinkan -> 400
        # (mencegah injeksi PromQL). Diperiksa SEBELUM menyentuh Prometheus.
        client = self._client(is_superadmin=True)
        self.assertEqual(
            client.get(
                "/admin/ops/monitoring/metric-series?name=up) or (1"
            ).status_code,
            400,
        )
        self.assertEqual(
            client.get(
                "/admin/ops/monitoring/metric-series?name=node_cpu_seconds_total"
            ).status_code,
            400,  # prefix tidak diizinkan
        )

    def test_superadmin_tidak_403(self):
        # Super-admin lolos gerbang; endpoint lalu mencoba Prometheus. Tanpa
        # Prometheus hasilnya tetap 200 dengan prometheus_reachable=false
        # (galat httpx ditangani di dalam endpoint).
        client = self._client(is_superadmin=True)
        resp = client.get("/admin/ops/monitoring/summary")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("prometheus_reachable", resp.json())


if __name__ == "__main__":
    unittest.main()
