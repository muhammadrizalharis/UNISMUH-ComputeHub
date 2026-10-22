"""Uji log audit admin: filter, paging, ringkasan, dan ekspor CSV.

Jalankan DALAM container app (router admin mengimpor fpdf):
  docker exec -e PYTHONDONTWRITEBYTECODE=1 -w <repo>/backend ComputeHub-app \
      python -m unittest tests.test_audit_log
"""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.audit import AuditLog


class AuditLogEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import require_admin
        from app.api.routers import admin as admin_router
        from app.core.database import get_db

        tmp = tempfile.TemporaryDirectory(prefix="ch-audit-test-")
        self.addCleanup(tmp.cleanup)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/audit.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def get_test_db():
            async with self.sessions() as session:
                yield session

        p = patch.object(admin_router.settings, "REPORT_TIMEZONE", "Asia/Makassar")
        p.start()
        self.addCleanup(p.stop)

        app = FastAPI()
        app.include_router(admin_router.router, prefix="/admin")
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1, role="admin", email="adm@x.id")
        app.dependency_overrides[get_db] = get_test_db
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        async def siapkan() -> None:
            async with self.engine.begin() as conn:
                await conn.run_sync(lambda c: AuditLog.metadata.create_all(c, tables=[AuditLog.__table__]))
            async with self.sessions() as session:
                # 2026-10-01 23:30 WITA = 15:30 UTC; 2026-10-02 00:30 WITA = 16:30 UTC (1 Okt UTC!)
                t0 = dt.datetime(2026, 10, 1, 15, 30, tzinfo=dt.timezone.utc)
                session.add_all([
                    AuditLog(created_at=t0, actor_id=1, actor_email="adm@x.id", action="storage_quota.approve",
                             target_type="user", target_id="7", detail="setujui 50 GB"),
                    AuditLog(created_at=t0 + dt.timedelta(hours=1), actor_id=2, actor_email="lain@x.id",
                             action="storage_quota.reject", target_type="user", target_id="8",
                             detail="=HYPERLINK(\"x\") tolak 100% kuota"),
                    AuditLog(created_at=t0 + dt.timedelta(days=3), actor_id=1, actor_email="adm@x.id",
                             action="user.delete", target_type="user", target_id="9", detail="hapus akun"),
                    AuditLog(created_at=t0 + dt.timedelta(days=4), actor_id=1, actor_email="adm@x.id",
                             action="storage_quota_extra", target_type="x", target_id="1", detail="bukan grup"),
                ])
                await session.commit()

        asyncio.run(siapkan())

    def get(self, **params):
        r = self.client.get("/admin/audit", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_urutan_dan_paging(self) -> None:
        semua = self.get()
        self.assertEqual([a["action"] for a in semua][:2], ["storage_quota_extra", "user.delete"])
        hal2 = self.get(skip=1, limit=2)
        self.assertEqual([a["id"] for a in hal2], [semua[1]["id"], semua[2]["id"]])

    def test_filter_aksi_grup_dan_persis(self) -> None:
        grup = self.get(action="storage_quota")
        self.assertEqual(sorted(a["action"] for a in grup), ["storage_quota.approve", "storage_quota.reject"])
        self.assertEqual(len(self.get(action="user.delete")), 1)

    def test_filter_aktor_dan_kata_kunci(self) -> None:
        self.assertEqual(len(self.get(actor="lain")), 1)
        self.assertEqual(len(self.get(q="100%")), 1)
        self.assertEqual(len(self.get(q="%")), 1)  # % diperlakukan literal
        self.assertEqual(len(self.get(q="_")), 0)

    def test_filter_tanggal_zona_wita(self) -> None:
        # 2 Okt WITA hanya berisi entri 00:30 WITA (yang di UTC masih 1 Okt).
        r = self.get(date_from="2026-10-02", date_to="2026-10-02")
        self.assertEqual([a["action"] for a in r], ["storage_quota.reject"])
        self.assertEqual(len(self.get(date_to="2026-10-01")), 1)

    def test_ringkasan(self) -> None:
        r = self.client.get("/admin/audit/summary", params={"action": "storage_quota"}).json()
        self.assertEqual(r["total"], 2)
        self.assertEqual(len(r["actions"]), 4)
        self.assertEqual(r["actors"], ["adm@x.id", "lain@x.id"])

    def test_ekspor_csv(self) -> None:
        r = self.client.get("/admin/audit.csv", params={"action": "storage_quota"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("attachment", r.headers["content-disposition"])
        teks = r.content.decode("utf-8")
        self.assertTrue(teks.startswith("\ufeff"))
        baris = list(csv.reader(io.StringIO(teks.lstrip("\ufeff"))))
        self.assertEqual(len(baris), 3)
        self.assertEqual(baris[1][1], "2026-10-02 00:30:00")
        self.assertTrue(baris[1][8].startswith("'="))

        async def cek() -> list[str]:
            async with self.sessions() as s:
                return list(await s.scalars(select(AuditLog.action).where(AuditLog.action == "audit.export")))

        self.assertEqual(asyncio.run(cek()), ["audit.export"])


if __name__ == "__main__":
    unittest.main()
