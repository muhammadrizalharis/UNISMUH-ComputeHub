"""Uji mode keras penyimpanan + notifikasi bertahap + permintaan tambahan kuota.

Jalankan DALAM container app (router admin/interactive mengimpor fpdf dll.):
  docker exec -e PYTHONDONTWRITEBYTECODE=1 -w <repo>/backend ComputeHub-app \
      python -m unittest tests.test_storage_quota
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.notification import Notification
from app.models.storage_request import StorageQuotaRequest
from app.models.user import User, UserRole
from app.models.user_policy import UserPolicy
from app.services import storage_guard as sg
from app.services import storage_request as sr


class BlocksNewWorkTests(unittest.TestCase):
    def test_matrix(self) -> None:
        with patch.object(settings, "SOFT_LIMIT_ENABLED", False), patch.object(settings, "STORAGE_HARD_LIMIT", False):
            self.assertTrue(sg.blocks_new_work())
        with patch.object(settings, "SOFT_LIMIT_ENABLED", True), patch.object(settings, "STORAGE_HARD_LIMIT", False):
            self.assertFalse(sg.blocks_new_work())
        with patch.object(settings, "SOFT_LIMIT_ENABLED", True), patch.object(settings, "STORAGE_HARD_LIMIT", True):
            self.assertTrue(sg.blocks_new_work())

    def test_upload_limit_respects_quota_in_hard_storage_mode(self) -> None:
        async def run() -> None:
            with patch.object(settings, "SOFT_LIMIT_ENABLED", True), patch.object(settings, "STORAGE_HARD_LIMIT", True), \
                    patch.object(sg, "user_disk_used_bytes", return_value=90 * 1024 * 1024):
                self.assertEqual(await sg.upload_limit_bytes(7, 100.0), 10 * 1024 * 1024)
            with patch.object(settings, "SOFT_LIMIT_ENABLED", True), patch.object(settings, "STORAGE_HARD_LIMIT", False), \
                    patch.object(sg, "user_disk_used_bytes", return_value=90 * 1024 * 1024):
                self.assertGreater(await sg.upload_limit_bytes(7, 100.0), 10 * 1024 * 1024)
        asyncio.run(run())

    def test_notify_stages_parsing_and_clear_over(self) -> None:
        with patch.object(settings, "STORAGE_NOTIFY_STAGES", "90, 80 ,100,abc,150"):
            self.assertEqual(sg.notify_stages(), [80, 90, 100])
        sg._over.add(5)
        sg._usage[5] = {"used_mb": 50.0, "quota_mb": 40.0, "ratio": 1.25}
        sg._stage_notified[5] = 100
        sg.clear_over(5, 100.0)
        self.assertFalse(sg.is_over_quota(5))
        self.assertEqual(sg.user_status(5)["quota_mb"], 100.0)
        self.assertNotIn(5, sg._stage_notified)


class _DbMixin:
    def _make_db(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="ch-quota-test-")
        self.addCleanup(tmp.cleanup)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/q.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def siapkan() -> None:
            async with self.engine.begin() as conn:
                await conn.run_sync(lambda c: User.metadata.create_all(
                    c, tables=[User.__table__, UserPolicy.__table__, Notification.__table__, StorageQuotaRequest.__table__]))
            async with self.sessions() as s:
                s.add(User(id=24, name="QA Mahasiswa", email="qa.mhs@example.invalid", hashed_password="x", role=UserRole.mahasiswa))
                s.add(User(id=20, name="QA Admin", email="qa.admin@example.invalid", hashed_password="x", role=UserRole.admin))
                s.add(UserPolicy(user_id=24, max_storage_mb=10240.0))
                await s.commit()
        asyncio.run(siapkan())


class StageNotificationTests(_DbMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._make_db()
        sg._stage_notified.clear()

    def test_notify_once_per_stage_and_survives_restart(self) -> None:
        async def run() -> None:
            async with self.sessions() as db:
                await sg._notify_stage(db, 24, 80, 8300.0, 10240.0)
                await sg._notify_stage(db, 24, 80, 8400.0, 10240.0)   # tahap sama -> ditahan (<3 hari)
                await sg._notify_stage(db, 24, 100, 10300.0, 10240.0)
                rows = (await db.execute(
                    Notification.__table__.select().where(Notification.user_id == 24).order_by(Notification.id))).all()
            self.assertEqual([r.type for r in rows], ["storage_warning", "storage_full"])
            self.assertTrue(rows[0].body.startswith("[80%]"))
            self.assertIn("ditolak", rows[1].title) if sg.blocks_new_work() else self.assertNotIn("ditolak", rows[1].title)
            self.assertEqual(rows[1].link, "/storage")
        asyncio.run(run())


class QuotaRequestFlowTests(_DbMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._make_db()
        sg._over.clear()
        sg._usage.clear()

    def test_create_validation_and_single_pending(self) -> None:
        async def run() -> None:
            async with self.sessions() as db:
                user = await db.get(User, 24)
                with patch.object(sr.asyncio, "create_task", lambda coro: coro.close()):
                    with self.assertRaises(ValueError):          # <= kuota sekarang
                        await sr.create(db, user, 10240.0, "alasan cukup panjang")
                    sg._usage[24] = {"used_mb": 9900.0, "quota_mb": 10240.0, "ratio": 0.97}
                    req = await sr.create(db, user, 20480.0, "[UJI QA] dataset skripsi 15 GB")
                    self.assertEqual((req.status, req.current_quota_mb, req.used_mb), ("pending", 10240.0, 9900.0))
                    with self.assertRaises(ValueError):          # masih ada pending
                        await sr.create(db, user, 30720.0, "alasan lain yang panjang")
        asyncio.run(run())

    def test_approve_sets_override_clears_over_and_notifies(self) -> None:
        async def run() -> None:
            sg._over.add(24)
            sg._usage[24] = {"used_mb": 10300.0, "quota_mb": 10240.0, "ratio": 1.006}
            async with self.sessions() as db:
                user = await db.get(User, 24)
                admin = await db.get(User, 20)
                with patch.object(sr.asyncio, "create_task", lambda coro: coro.close()):
                    req = await sr.create(db, user, 20480.0, "[UJI QA] butuh ruang model")
                req = await sr.decide(db, req, admin, approve=True, granted_mb=15360.0, note="disetujui sebagian")
                self.assertEqual((req.status, req.granted_mb, req.decided_by_email), ("approved", 15360.0, "qa.admin@example.invalid"))
                pol = await db.get(UserPolicy, 24)
                self.assertEqual(pol.max_storage_mb, 15360.0)
                notif = (await db.execute(Notification.__table__.select().where(Notification.user_id == 24))).all()
                self.assertEqual(notif[-1].type, "storage_request_approved")
                self.assertIn("15.0 GB", notif[-1].title)
                with self.assertRaises(ValueError):              # tak bisa diputuskan dua kali
                    await sr.decide(db, req, admin, approve=False)
            self.assertFalse(sg.is_over_quota(24))
            self.assertEqual(sg.user_status(24)["quota_mb"], 15360.0)
        asyncio.run(run())

    def test_reject_notifies_with_note(self) -> None:
        async def run() -> None:
            async with self.sessions() as db:
                user = await db.get(User, 24)
                admin = await db.get(User, 20)
                with patch.object(sr.asyncio, "create_task", lambda coro: coro.close()):
                    req = await sr.create(db, user, 20480.0, "[UJI QA] coba minta")
                req = await sr.decide(db, req, admin, approve=False, note="Rapikan dataset lama dulu.")
                self.assertEqual(req.status, "rejected")
                notif = (await db.execute(Notification.__table__.select().where(Notification.user_id == 24))).all()
                self.assertEqual((notif[-1].type, notif[-1].body), ("storage_request_rejected", "Rapikan dataset lama dulu."))
                pol = await db.get(UserPolicy, 24)
                self.assertEqual(pol.max_storage_mb, 10240.0)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
