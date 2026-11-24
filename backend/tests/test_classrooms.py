"""Uji Ruang Kelas (A1): buat kelas, gabung via kode, anggota manual, hak akses."""

from __future__ import annotations

import asyncio
import tempfile
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.audit import AuditLog
from app.models.classroom import ClassMember, Classroom
from app.models.notification import Notification
from app.models.user import User, UserRole


class ClassroomApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_active_user
        from app.api.routers import classrooms as router_mod
        from app.core.database import get_db

        self.mod = router_mod
        router_mod._join_failures.clear()
        tmp = tempfile.TemporaryDirectory(prefix="ch-class-test-")
        self.addCleanup(tmp.cleanup)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/c.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def get_test_db():
            async with self.sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(router_mod.router, prefix="/classrooms")
        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[get_current_active_user] = lambda: self.me
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        async def siapkan() -> dict[str, User]:
            tables = [User.__table__, Classroom.__table__, ClassMember.__table__,
                      Notification.__table__, AuditLog.__table__]
            async with self.engine.begin() as conn:
                await conn.run_sync(lambda c: User.metadata.create_all(c, tables=tables))
            data = {
                "admin": ("Admin", "adm@x.id", "CHadm", UserRole.admin),
                "dosen": ("Bu Dosen", "dosen@x.id", "CHdosen", UserRole.dosen),
                "dosen2": ("Pak Asisten", "asis@x.id", "CHasis", UserRole.dosen),
                "mhs": ("Ani", "105841100120@x.id", "CH105841100120", UserRole.mahasiswa),
                "mhs2": ("Budi", "105841100121@x.id", "CH105841100121", UserRole.mahasiswa),
            }
            out = {}
            async with self.sessions() as s:
                for key, (name, email, uname, role) in data.items():
                    u = User(name=name, email=email, username=uname, hashed_password="x", role=role)
                    s.add(u)
                    out[key] = u
                await s.commit()
            return out

        self.u = asyncio.run(siapkan())
        self.me = self.u["dosen"]

    def as_(self, key: str) -> None:
        self.me = self.u[key]

    def create(self, name: str = "Deep Learning TI-5A") -> dict:
        r = self.client.post("/classrooms", json={"name": name, "description": "Praktikum"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def db(self, coro_fn):
        async def run():
            async with self.sessions() as s:
                return await coro_fn(s)
        return asyncio.run(run())

    def test_only_dosen_and_admin_can_create(self) -> None:
        room = self.create()
        self.assertEqual(room["my_role"], "pengajar")
        self.assertEqual(len(room["code"]), 8)
        self.assertEqual(room["teachers"], ["Bu Dosen"])
        self.as_("admin")
        self.create("Kelas admin")
        self.as_("mhs")
        r = self.client.post("/classrooms", json={"name": "Kelas mhs"})
        self.assertEqual(r.status_code, 403)

    def test_join_by_code_and_student_privacy(self) -> None:
        room = self.create()
        self.as_("mhs")
        r = self.client.post("/classrooms/join", json={"code": room["code"][:4].lower() + "-" + room["code"][4:]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["my_role"], "mahasiswa")
        self.assertIsNone(r.json()["code"])
        again = self.client.post("/classrooms/join", json={"code": room["code"]})
        self.assertEqual(again.status_code, 200)
        self.as_("mhs2")
        self.client.post("/classrooms/join", json={"code": room["code"]})
        detail = self.client.get(f"/classrooms/{room['id']}").json()
        self.assertEqual(detail["student_count"], 2)
        self.assertEqual([m["role"] for m in detail["members"]], ["pengajar"])
        self.assertIsNone(detail["members"][0]["email"])
        self.assertFalse(detail["can_manage"])
        self.assertEqual(self.client.patch(f"/classrooms/{room['id']}", json={"name": "Hack"}).status_code, 403)
        self.as_("dosen")
        full = self.client.get(f"/classrooms/{room['id']}").json()
        self.assertEqual(len(full["members"]), 3)
        self.assertTrue(all(m["email"] for m in full["members"]))

    def test_non_member_gets_404_and_admin_sees_all(self) -> None:
        room = self.create()
        self.as_("mhs")
        self.assertEqual(self.client.get(f"/classrooms/{room['id']}").status_code, 404)
        self.assertEqual(self.client.get("/classrooms").json(), [])
        self.as_("admin")
        self.assertEqual(self.client.get("/classrooms").json(), [])
        semua = self.client.get("/classrooms", params={"scope": "all"}).json()
        self.assertEqual([c["my_role"] for c in semua], ["admin"])
        self.assertTrue(semua[0]["can_manage"])

    def test_join_closed_archived_and_rate_limited(self) -> None:
        room = self.create()
        self.client.patch(f"/classrooms/{room['id']}", json={"join_enabled": False})
        self.as_("mhs")
        self.assertEqual(self.client.post("/classrooms/join", json={"code": room["code"]}).status_code, 403)
        for _ in range(self.mod.JOIN_FAIL_LIMIT):
            self.assertEqual(self.client.post("/classrooms/join", json={"code": "ZZZZZZZZ"}).status_code, 404)
        self.assertEqual(self.client.post("/classrooms/join", json={"code": room["code"]}).status_code, 429)

    def test_regenerate_code_invalidates_old(self) -> None:
        room = self.create()
        baru = self.client.post(f"/classrooms/{room['id']}/code").json()["code"]
        self.assertNotEqual(baru, room["code"])
        self.as_("mhs")
        self.assertEqual(self.client.post("/classrooms/join", json={"code": room["code"]}).status_code, 404)
        self.assertEqual(self.client.post("/classrooms/join", json={"code": baru}).status_code, 200)

    def test_add_members_manual_by_email_username_nim(self) -> None:
        room = self.create()
        r = self.client.post(f"/classrooms/{room['id']}/members", json={
            "identifiers": ["105841100120@X.ID", "CH105841100121", "105841100121", "tidakada", "dosen@x.id"],
        })
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()
        self.assertEqual(res["added"], ["105841100120@X.ID", "CH105841100121"])
        self.assertEqual(res["not_found"], ["tidakada"])
        self.assertEqual(res["already"], ["dosen@x.id"])
        r2 = self.client.post(f"/classrooms/{room['id']}/members", json={"identifiers": ["105841100120"]})
        self.assertEqual(r2.json()["already"], ["105841100120"])
        notes = self.db(lambda s: s.scalars(select(Notification)))
        self.assertEqual({n.user_id for n in notes.all()}, {self.u["mhs"].id, self.u["mhs2"].id})
        audit = self.db(lambda s: s.scalars(select(AuditLog.action)))
        self.assertIn("class.member_add", audit.all())

    def test_co_teacher_and_last_teacher_protection(self) -> None:
        room = self.create()
        rid = room["id"]
        self.assertEqual(self.client.post(f"/classrooms/{rid}/leave").status_code, 400)
        self.assertEqual(
            self.client.patch(f"/classrooms/{rid}/members/{self.u['dosen'].id}", json={"role": "mahasiswa"}).status_code,
            400,
        )
        self.client.post(f"/classrooms/{rid}/members", json={"user_ids": [self.u["dosen2"].id], "role": "pengajar"})
        self.as_("dosen2")
        detail = self.client.get(f"/classrooms/{rid}").json()
        self.assertTrue(detail["can_manage"])
        self.assertEqual(detail["teacher_count"], 2)
        self.as_("dosen")
        self.assertEqual(self.client.post(f"/classrooms/{rid}/leave").status_code, 204)
        self.as_("dosen2")
        self.assertEqual(self.client.delete(f"/classrooms/{rid}/members/{self.u['dosen2'].id}").status_code, 400)

    def test_candidates_search_excludes_members(self) -> None:
        room = self.create()
        r = self.client.get(f"/classrooms/{room['id']}/candidates", params={"q": "1058"})
        self.assertEqual(sorted(c["name"] for c in r.json()), ["Ani", "Budi"])
        r = self.client.get(f"/classrooms/{room['id']}/candidates", params={"q": "dosen"})
        self.assertEqual(r.json(), [])
        self.as_("mhs")
        self.assertEqual(
            self.client.get(f"/classrooms/{room['id']}/candidates", params={"q": "an"}).status_code, 404
        )

    def test_remove_member_and_delete_class(self) -> None:
        room = self.create()
        rid = room["id"]
        self.client.post(f"/classrooms/{rid}/members", json={"user_ids": [self.u["mhs"].id]})
        self.assertEqual(self.client.delete(f"/classrooms/{rid}/members/{self.u['mhs'].id}").status_code, 204)
        self.as_("mhs")
        self.assertEqual(self.client.get(f"/classrooms/{rid}").status_code, 404)
        self.as_("dosen")
        self.assertEqual(self.client.delete(f"/classrooms/{rid}").status_code, 204)
        left = self.db(lambda s: s.scalars(select(ClassMember)))
        self.assertEqual(left.all(), [])


if __name__ == "__main__":
    unittest.main()
