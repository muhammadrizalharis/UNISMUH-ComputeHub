"""Uji laporan jam GPU bulanan (B3) dan pemantauan kesehatan SMTP (D2).

Jalankan DALAM container app (router admin mengimpor fpdf):
  docker exec -w <repo>/backend ComputeHub-app python -m pytest tests/test_gpu_monthly.py -q
"""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import smtplib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.job import Job, JobDevice, JobSource, JobStatus
from app.models.user import User, UserRole

UTC = dt.timezone.utc


class GpuMonthlyTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import require_admin
        from app.api.routers import admin as admin_router
        from app.core.database import get_db
        from app.services import gpu_monthly

        tmp = tempfile.TemporaryDirectory(prefix="ch-gpumonth-test-")
        self.addCleanup(tmp.cleanup)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/g.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def get_test_db():
            async with self.sessions() as session:
                yield session

        for target in (admin_router.settings, gpu_monthly.settings):
            p = patch.object(target, "REPORT_TIMEZONE", "Asia/Makassar")
            p.start()
            self.addCleanup(p.stop)

        app = FastAPI()
        app.include_router(admin_router.router, prefix="/admin")
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1, role="admin", email="a@x.id")
        app.dependency_overrides[get_db] = get_test_db
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        def job(uid, name, secs, finished, gpu=0, peak=1000.0, interactive=False):
            return Job(
                name=name, user_id=uid, source_type=JobSource.paste, status=JobStatus.succeeded,
                device=JobDevice.gpu, gpu_index=gpu, actual_runtime_seconds=secs,
                peak_vram_mb=peak, is_interactive=interactive, finished_at=finished,
            )

        async def siapkan() -> None:
            async with self.engine.begin() as conn:
                await conn.run_sync(
                    lambda c: User.metadata.create_all(c, tables=[User.__table__, Job.__table__])
                )
            async with self.sessions() as s:
                s.add_all([
                    User(id=1, name="Ani", email="ani@x.id", username="ani",
                         hashed_password="x", role=UserRole.mahasiswa),
                    User(id=2, name="=Budi", email="budi@x.id", username="budi",
                         hashed_password="x", role=UserRole.dosen),
                ])
                s.add_all([
                    job(1, "train", 3600, dt.datetime(2026, 10, 10, 3, tzinfo=UTC)),
                    job(1, "nb", 1800, dt.datetime(2026, 10, 11, 3, tzinfo=UTC), interactive=True),
                    job(1, "Devbox VS Code", 900, dt.datetime(2026, 10, 12, 3, tzinfo=UTC),
                        interactive=True, peak=4096.0),
                    # Tanpa VRAM -> tidak dihitung (sama dengan kuota).
                    job(1, "sklearn", 7200, dt.datetime(2026, 10, 13, 3, tzinfo=UTC), peak=0.0),
                    # Tanpa GPU -> tidak dihitung.
                    job(1, "cpu", 7200, dt.datetime(2026, 10, 13, 4, tzinfo=UTC), gpu=None),
                    # 1 Nov 00:30 WITA = 31 Okt 16:30 UTC -> masuk NOVEMBER.
                    job(1, "lewat", 600, dt.datetime(2026, 10, 31, 16, 30, tzinfo=UTC)),
                    job(2, "dosen", 7200, dt.datetime(2026, 10, 20, 3, tzinfo=UTC)),
                ])
                await s.commit()

        asyncio.run(siapkan())

    def test_ringkasan_per_pengguna_dan_peran(self) -> None:
        r = self.client.get("/admin/report/gpu-monthly", params={"month": "2026-10"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["total_gpu_seconds"], 3600 + 1800 + 900 + 7200)
        self.assertEqual([u["username"] for u in d["users"]], ["budi", "ani"])
        ani = d["users"][1]
        self.assertEqual(ani["sessions"], 3)
        self.assertEqual(ani["batch_seconds"], 3600)
        self.assertEqual(ani["interactive_seconds"], 1800)
        self.assertEqual(ani["devbox_seconds"], 900)
        self.assertEqual(ani["peak_vram_mb"], 4096.0)
        roles = {r["role"]: r for r in d["by_role"]}
        self.assertEqual(roles["mahasiswa"]["gpu_seconds"], 6300)
        self.assertEqual(roles["dosen"]["users"], 1)

    def test_batas_bulan_memakai_wita(self) -> None:
        d = self.client.get("/admin/report/gpu-monthly", params={"month": "2026-11"}).json()
        self.assertEqual(d["total_gpu_seconds"], 600)

    def test_csv_aman_dari_formula(self) -> None:
        r = self.client.get("/admin/report/gpu-monthly.csv", params={"month": "2026-10"})
        self.assertEqual(r.status_code, 200)
        self.assertIn('jam-gpu-2026-10.csv', r.headers["content-disposition"])
        rows = list(csv.DictReader(io.StringIO(r.text)))
        self.assertEqual(rows[0]["nama"], "'=Budi")
        self.assertEqual(rows[0]["jam_gpu"], "2.00")
        self.assertEqual(rows[1]["jam_devbox"], "0.25")

    def test_bulan_tidak_valid(self) -> None:
        r = self.client.get("/admin/report/gpu-monthly", params={"month": "2026-13"})
        self.assertEqual(r.status_code, 422)


class SmtpHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.services import email as email_svc

        self.svc = email_svc
        self.sent: list[str] = []
        email_svc._status.update(
            last_ok_at=None, last_error="", last_error_at=None, consecutive_failures=0,
            last_check_at=None, last_check_ok=None,
        )
        email_svc._last_alert_at = 0.0
        for name, val in (
            ("SMTP_HOST", "smtp.example"), ("SMTP_USERNAME", "u"), ("SMTP_PASSWORD", "p"),
        ):
            p = patch.object(email_svc.settings, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(email_svc, "_telegram", lambda judul, isi: self.sent.append(judul))
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(email_svc.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_gagal_lalu_pulih_memberi_tahu_sekali(self) -> None:
        err = smtplib.SMTPAuthenticationError(535, b"bad creds")
        with patch.object(self.svc, "_deliver", side_effect=err):
            for _ in range(3):
                with self.assertRaises(smtplib.SMTPAuthenticationError):
                    self.svc.send_email(["a@x.id"], "s", "b")
        st = self.svc.status()
        self.assertEqual(st["consecutive_failures"], 3)
        self.assertIn("535", st["last_error"])
        self.assertEqual(self.sent, ["ComputeHub: email GAGAL"])  # dibatasi, tidak spam

        with patch.object(self.svc, "_deliver", return_value=None):
            self.svc.send_email(["a@x.id"], "s", "b")
        st = self.svc.status()
        self.assertEqual(st["consecutive_failures"], 0)
        self.assertIsNotNone(st["last_ok_at"])
        self.assertEqual(self.sent, ["ComputeHub: email GAGAL", "ComputeHub: email pulih"])

    def test_uji_koneksi_tanpa_mengirim(self) -> None:
        with patch.object(self.svc, "_deliver", return_value=None) as d:
            self.assertTrue(self.svc.check_connection())
        d.assert_called_once_with(None)
        st = self.svc.status()
        self.assertTrue(st["last_check_ok"])
        self.assertIsNone(st["last_ok_at"])

        with patch.object(self.svc, "_deliver", side_effect=OSError("timeout")):
            self.assertFalse(self.svc.check_connection())
        st = self.svc.status()
        self.assertFalse(st["last_check_ok"])
        self.assertEqual(st["consecutive_failures"], 1)


if __name__ == "__main__":
    unittest.main()
