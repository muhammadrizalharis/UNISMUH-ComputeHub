"""Uji bukti cadangan (ops_events): endpoint admin + kesesuaian DDL skrip host.

Jalankan DALAM container app (router admin mengimpor fpdf):
  docker exec -e PYTHONDONTWRITEBYTECODE=1 -w <repo>/backend ComputeHub-app \
      python -m unittest tests.test_ops_events
"""

from __future__ import annotations

import datetime as dt
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.ops_event import OpsEvent


class OpsEventsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.deps import require_admin
        from app.api.routers import admin as admin_router
        from app.core.database import get_db

        # Berkas sementara + NullPool: TestClient memakai event loop sendiri, koneksi
        # aiosqlite tidak boleh dibagi antar loop.
        tmp = tempfile.TemporaryDirectory(prefix="ch-ops-test-")
        self.addCleanup(tmp.cleanup)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/ops.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def get_test_db():
            async with self.sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(admin_router.router, prefix="/admin")
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1, role="admin")
        app.dependency_overrides[get_db] = get_test_db
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        import asyncio

        async def siapkan() -> None:
            async with self.engine.begin() as conn:
                await conn.run_sync(lambda c: OpsEvent.metadata.create_all(c, tables=[OpsEvent.__table__]))
            async with self.sessions() as session:
                t0 = dt.datetime(2026, 10, 1, 2, 30, tzinfo=dt.timezone.utc)
                session.add_all([
                    OpsEvent(created_at=t0, kind="backup", status="ok", title="Snapshot restic (rekonstruksi)",
                             detail="", data={"backfill": True}, source="ops_event.py --backfill", dedup_key="restic:abc"),
                    OpsEvent(created_at=t0 + dt.timedelta(days=1), kind="backup", status="fail", title="Backup GAGAL",
                             detail="baris 242", data={}, source="backup.sh", duration_seconds=12),
                    OpsEvent(created_at=t0 + dt.timedelta(days=2), kind="backup", status="ok", title="Backup selesai",
                             detail="Arsip x", data={"archive": "computehub-x.tar.gz.gpg", "offsite_tar": "ok"},
                             source="backup.sh", duration_seconds=3600),
                    OpsEvent(created_at=t0 + dt.timedelta(days=1, hours=1), kind="restore_drill", status="ok",
                             title="Restore drill SUKSES", detail="", data={"tables": 12, "users": 40, "jobs": 1200},
                             source="restore_drill.sh"),
                ])
                await session.commit()

        asyncio.run(siapkan())

    def test_events_listing_filters_and_orders_newest_first(self) -> None:
        semua = self.client.get("/admin/ops/events").json()
        self.assertEqual([e["title"] for e in semua][:2], ["Backup selesai", "Restore drill SUKSES"])
        hanya_drill = self.client.get("/admin/ops/events", params={"kind": "restore_drill"}).json()
        self.assertEqual(len(hanya_drill), 1)
        self.assertEqual(hanya_drill[0]["data"]["users"], 40)
        self.assertEqual(self.client.get("/admin/ops/events", params={"kind": "ngawur"}).json(), semua)

    def test_backup_status_summary_uses_live_backup_and_counts_restic(self) -> None:
        with patch.object(Path, "glob", return_value=iter(())):
            body = self.client.get("/admin/ops/backup-status").json()
        self.assertEqual(body["last_backup"]["title"], "Backup selesai")
        self.assertEqual(body["last_backup_ok"]["data"]["offsite_tar"], "ok")
        self.assertEqual(body["last_restore_drill"]["data"]["tables"], 12)
        self.assertEqual(body["restic_snapshots_recorded"], 1)
        self.assertEqual(body["events_total"], 4)
        self.assertIn("restore_drill", body["policy"])

    def test_csv_export_has_header_and_all_rows(self) -> None:
        resp = self.client.get("/admin/ops/events.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["content-type"])
        baris = resp.text.lstrip("\ufeff").splitlines()
        self.assertEqual(baris[0].split(","), ["waktu", "jenis", "status", "judul", "durasi_detik", "sumber", "data", "detail"])
        self.assertEqual(len(baris), 5)

    def test_event_pdf_for_plain_and_manifest_records(self) -> None:
        semua = self.client.get("/admin/ops/events").json()
        drill = next(e for e in semua if e["kind"] == "restore_drill")
        with patch.object(Path, "glob", return_value=iter(())):
            resp = self.client.get(f"/admin/ops/events/{drill['id']}/pdf")
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertRegex(resp.headers["content-disposition"], r'filename="cadangan_restore_drill_\d+_\d{8}_\d{4}\.pdf"')
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertGreater(len(resp.content), 1500)
        # catatan backup dengan manifest -> bagian Detail Backup ikut dibuat
        import asyncio

        async def tambah() -> int:
            async with self.sessions() as s:
                e = OpsEvent(kind="backup", status="ok", title="Backup manual (web, CHSuperAdmin) selesai", detail="",
                             data={"archive": "computehub-20261009-005039.tar.gz.gpg", "offsite_tar": "ok", "trigger": "web",
                                   "manifest": {"archive_kind": "full", "trigger": "web", "requested_by": "CHSuperAdmin", "duration_seconds": 60,
                                                "database": {"name": "computehub", "tables": 15, "estimated_rows": 1772784, "dump_bytes": 182225525, "globals_included": True},
                                                "workspaces": {"accounts": [{"dir": "24", "username": "CHqastudent", "role": "mahasiswa", "files": 2, "bytes": 300005}], "accounts_total": 1, "files_total": 2, "bytes_total": 300005},
                                                "components": {"env": {"included": True}, "joblogs": {"included": True, "files": 112}},
                                                "archive": {"name": "computehub-20261009-005039.tar.gz.gpg", "bytes": 28728307, "sha256": "2d1739db" * 8, "form": "terenkripsi (.gpg)"},
                                                "offsite": {"tar": "ok", "remote": "gdrive:ComputeHub-Backups"}, "restic": {"status": "ok", "snapshot": "2a06f4d9"},
                                                "files": [{"path": "db.sql", "bytes": 182225525}]}},
                             source="backup.sh", duration_seconds=60)
                s.add(e)
                await s.commit()
                return e.id
        eid = asyncio.run(tambah())
        with patch.object(Path, "glob", return_value=iter(())):
            resp = self.client.get(f"/admin/ops/events/{eid}/pdf")
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertGreater(len(resp.content), 2500)
        self.assertEqual(self.client.get("/admin/ops/events/999999/pdf").status_code, 404)


class OpsEventScriptDdlParityTests(unittest.TestCase):
    """DDL di scripts/ops_event.py harus memuat kolom yang sama dengan model."""

    def test_script_ddl_matches_model_columns(self) -> None:
        skrip = (Path(__file__).resolve().parents[2] / "scripts" / "ops_event.py").read_text(encoding="utf-8")
        ddl = re.search(r"CREATE TABLE IF NOT EXISTS ops_events \((.*?)\);", skrip, re.S).group(1)
        kolom_skrip = {baris.strip().split()[0] for baris in ddl.strip().splitlines() if baris.strip()}
        kolom_model = {c.name for c in OpsEvent.__table__.columns}
        self.assertEqual(kolom_skrip, kolom_model)
        self.assertIn("ix_ops_events_created_at", skrip)
        self.assertIn("ix_ops_events_kind", skrip)


if __name__ == "__main__":
    unittest.main()
