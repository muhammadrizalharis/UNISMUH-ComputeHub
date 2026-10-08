"""Uji antrean backup/restore dari web (ops_requests) — service berkas + endpoint admin.

Jalankan DALAM container app (router admin mengimpor fpdf):
  docker exec -e PYTHONDONTWRITEBYTECODE=1 -w <repo>/backend ComputeHub-app \
      python -m unittest tests.test_ops_requests
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.audit import AuditLog
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services import ops_requests as svc

CONFIRM = "YA PULIHKAN"


def _heartbeat(home: Path, seconds_ago: int = 0, stopping: bool = False) -> None:
    seen = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_ago)
    data = {"pid": 1, "version": "1.0", "last_seen": seen.isoformat(timespec="seconds"), "busy_request": None}
    if stopping:
        data["stopping"] = True
    (home / "ops-agent.json").write_text(json.dumps(data))


class OpsRequestsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="ch-opsreq-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = patch.object(svc, "ch_home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_submit_backup_writes_pending_file(self) -> None:
        view = svc.submit("backup", {}, 19, "CHSuperAdmin", "a@b.c")
        path = self.home / "ops-requests" / "pending" / f"{view['id']}.json"
        self.assertTrue(path.exists())
        raw = json.loads(path.read_text())
        self.assertEqual(raw["action"], "backup")
        self.assertEqual(raw["requested_by"]["username"], "CHSuperAdmin")
        self.assertEqual(view["status"], "pending")
        self.assertEqual(svc.has_active_request("backup")["id"], view["id"])
        self.assertIsNone(svc.has_active_request("restore"))

    def test_restore_params_validation(self) -> None:
        base = {"source_type": "archive", "source": "computehub-20261004-023502.tar.gz.gpg", "scope": ["db", "users"], "confirm": CONFIRM}
        ok = svc.validate_restore_params(base)
        self.assertEqual(ok["scope"], ["db", "users"])
        self.assertFalse(ok["stop_sessions"])
        with self.assertRaises(ValueError):
            svc.validate_restore_params({**base, "confirm": "ya pulihkan"})
        with self.assertRaises(ValueError):
            svc.validate_restore_params({**base, "source": "../../etc/passwd"})
        with self.assertRaises(ValueError):
            svc.validate_restore_params({**base, "source_type": "offsite", "source": "computehub-20261004-023502.tar.gz"})
        with self.assertRaises(ValueError):
            svc.validate_restore_params({**base, "scope": ["memory"]})
        with self.assertRaises(ValueError):
            svc.validate_restore_params({**base, "source_type": "snapshot", "source": "ZZZZ"})
        snap = svc.validate_restore_params({**base, "source_type": "snapshot", "source": "2a06f4d9"})
        self.assertEqual(snap["source"], "2a06f4d9")
        roll = svc.validate_restore_params({**base, "source_type": "pre_restore", "source": "pre-restore-20261009-005151", "scope": ["env", "db"]})
        self.assertEqual(roll["scope"], ["db", "env"])

    def test_public_view_hides_confirm_and_reads_log_tail(self) -> None:
        view = svc.submit("restore", {"source_type": "archive", "source": "computehub-20261004-023502.tar.gz.gpg",
                                      "scope": ["db"], "confirm": CONFIRM}, 19, "CHSuperAdmin", "a@b.c")
        self.assertNotIn("confirm", view["params"])
        raw = json.loads((self.home / "ops-requests" / "pending" / f"{view['id']}.json").read_text())
        self.assertEqual(raw["params"]["confirm"], CONFIRM)  # agen membutuhkannya, UI tidak
        logs = self.home / "ops-requests" / "logs"
        logs.mkdir(parents=True)
        (logs / f"{view['id']}.log").write_text("\n".join(f"baris {i}" for i in range(300)))
        detail = svc.get_request(view["id"], log_tail_lines=50)
        self.assertEqual(detail["log"].splitlines()[0], "baris 250")
        self.assertEqual(detail["log"].splitlines()[-1], "baris 299")
        self.assertIsNone(svc.get_request("20261009-010101-zzzzzz"))
        self.assertIsNone(svc.get_request("../etc/passwd"))
        rows = svc.list_requests()
        self.assertEqual([r["id"] for r in rows], [view["id"]])

    def test_agent_status(self) -> None:
        self.assertFalse(svc.agent_status()["alive"])
        _heartbeat(self.home, seconds_ago=5)
        self.assertTrue(svc.agent_status()["alive"])
        _heartbeat(self.home, seconds_ago=120)
        self.assertFalse(svc.agent_status()["alive"])
        _heartbeat(self.home, seconds_ago=1, stopping=True)
        self.assertFalse(svc.agent_status()["alive"])

    def test_sources_passthrough(self) -> None:
        self.assertFalse(svc.sources()["available"])
        (self.home / "backup-sources.json").write_text(json.dumps({"generated_at": "x", "archives": [{"name": "a"}],
                                                                   "restic": {"available": True, "snapshots": []},
                                                                   "offsite": {"available": False, "archives": []},
                                                                   "pre_restore": [], "plain_archives": [], "disk": {}}))
        data = svc.sources()
        self.assertTrue(data["available"])
        self.assertEqual(data["archives"][0]["name"], "a")


class OpsRequestsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.deps import require_admin
        from app.api.routers import admin as admin_router
        from app.core.database import get_db

        tmp = tempfile.TemporaryDirectory(prefix="ch-opsreq-ep-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = patch.object(svc, "ch_home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/ops.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def get_test_db():
            async with self.sessions() as session:
                yield session

        self.actor = SimpleNamespace(id=19, role="admin", is_superadmin=True, username="CHSuperAdmin", email="super@example.invalid")
        app = FastAPI()
        app.include_router(admin_router.router, prefix="/admin")
        app.dependency_overrides[require_admin] = lambda: self.actor
        app.dependency_overrides[get_db] = get_test_db
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        async def siapkan() -> None:
            async with self.engine.begin() as conn:
                await conn.run_sync(lambda c: User.metadata.create_all(c, tables=[User.__table__, Job.__table__, AuditLog.__table__]))
            async with self.sessions() as s:
                s.add(User(id=24, name="QA", email="qa@example.invalid", hashed_password="x", role=UserRole.mahasiswa))
                await s.commit()
        asyncio.run(siapkan())

    def _audit_actions(self) -> list[str]:
        async def ambil() -> list[str]:
            from sqlalchemy import select
            async with self.sessions() as s:
                return list((await s.scalars(select(AuditLog.action).order_by(AuditLog.id))).all())
        return asyncio.run(ambil())

    def _tambah_job_running(self) -> None:
        async def tambah() -> None:
            async with self.sessions() as s:
                s.add(Job(id=1, user_id=24, name="latih model", status=JobStatus.running))
                await s.commit()
        asyncio.run(tambah())

    def test_backup_requires_superadmin_and_rejects_duplicates(self) -> None:
        self.actor.is_superadmin = False
        self.assertEqual(self.client.post("/admin/ops/backup").status_code, 403)
        self.actor.is_superadmin = True
        r = self.client.post("/admin/ops/backup")
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(r.json()["action"], "backup")
        self.assertEqual(self.client.post("/admin/ops/backup").status_code, 409)
        self.assertEqual(self._audit_actions(), ["ops.backup"])
        rows = self.client.get("/admin/ops/requests").json()
        self.assertEqual(len(rows), 1)
        detail = self.client.get(f"/admin/ops/requests/{rows[0]['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "pending")
        self.assertEqual(self.client.get("/admin/ops/requests/20261009-000000-ffffff").status_code, 404)

    def test_restore_validation_agent_and_sessions(self) -> None:
        body = {"source_type": "archive", "source": "computehub-20261004-023502.tar.gz.gpg", "scope": ["db", "users"], "confirm": CONFIRM}
        self.assertEqual(self.client.post("/admin/ops/restore", json={**body, "confirm": "salah"}).status_code, 400)
        self.assertEqual(self.client.post("/admin/ops/restore", json={**body, "source": "computehub-x.tar.gz.gpg"}).status_code, 400)
        # agen mati -> 503
        self.assertEqual(self.client.post("/admin/ops/restore", json=body).status_code, 503)
        _heartbeat(self.home)
        self._tambah_job_running()
        pre = self.client.get("/admin/ops/precheck").json()
        self.assertEqual(pre["jobs_running"], 1)
        self.assertEqual(pre["sessions_total"], 1)
        r = self.client.post("/admin/ops/restore", json=body)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["precheck"]["sessions_total"], 1)
        r = self.client.post("/admin/ops/restore", json={**body, "acknowledge_sessions": True, "stop_sessions": True})
        self.assertEqual(r.status_code, 202, r.text)
        view = r.json()
        self.assertEqual(view["params"]["scope"], ["db", "users"])
        self.assertTrue(view["params"]["stop_sessions"])
        self.assertNotIn("confirm", view["params"])
        raw = json.loads((self.home / "ops-requests" / "pending" / f"{view['id']}.json").read_text())
        self.assertEqual(raw["params"]["confirm"], CONFIRM)
        self.assertIn("ops.restore", self._audit_actions())
        # permintaan restore masih pending -> backup/drill ditolak sementara
        self.assertEqual(self.client.post("/admin/ops/backup").status_code, 409)
        self.assertEqual(self.client.post("/admin/ops/drill", json={}).status_code, 409)

    def test_drill_and_sources_and_refresh(self) -> None:
        self.assertEqual(self.client.post("/admin/ops/drill", json={"archive": "../x"}).status_code, 400)
        r = self.client.post("/admin/ops/drill", json={"archive": "computehub-20261004-023502.tar.gz.gpg"})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(r.json()["params"]["archive"], "computehub-20261004-023502.tar.gz.gpg")
        self.assertFalse(self.client.get("/admin/ops/sources").json()["available"])
        self.assertFalse(self.client.get("/admin/ops/agent").json()["alive"])
        self.actor.is_superadmin = False
        self.assertEqual(self.client.post("/admin/ops/sources/refresh").status_code, 202)  # admin biasa boleh menyegarkan
        self.assertEqual(self.client.post("/admin/ops/drill", json={}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
