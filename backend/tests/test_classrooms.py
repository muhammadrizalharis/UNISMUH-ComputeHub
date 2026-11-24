"""Uji Ruang Kelas: kelas & anggota (A1), materi (A2), kuota GPU (A3), ruang kerja & pantau (A4)."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.audit import AuditLog
from app.models.classroom import ClassMaterial, ClassMaterialCopy, ClassMember, Classroom
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.models.user_policy import UserPolicy
from app.services import quota as quota_svc


class ClassroomApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_active_user
        from app.api.routers import classrooms as router_mod
        from app.core.database import get_db

        from app.core.config import settings

        self.mod = router_mod
        data_tmp = tempfile.TemporaryDirectory(prefix="ch-class-data-")
        self.addCleanup(data_tmp.cleanup)
        self.data = Path(data_tmp.name)
        self.quota_left = 10**12
        self.real_effective = router_mod.user_policy_svc.effective
        patches = [
            mock.patch.object(settings, "DOCKER_USER_DATA_ROOT", str(self.data / "users")),
            mock.patch.object(settings, "UPLOAD_DISK_HEADROOM_MB", 0.0),
            mock.patch.object(router_mod.user_policy_svc, "effective",
                              mock.AsyncMock(return_value=SimpleNamespace(max_storage_mb=0))),
            mock.patch.object(router_mod.storage_guard, "upload_limit_bytes",
                              mock.AsyncMock(side_effect=lambda *_a: self.quota_left)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
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
                      ClassMaterial.__table__, ClassMaterialCopy.__table__, UserPolicy.__table__,
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

    # ------------------------------------------------------------ materi (A2)

    def ws(self, key: str) -> Path:
        root = self.data / "users" / str(self.u[key].id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def kelas_with_student(self) -> dict:
        room = self.create()
        self.client.post(f"/classrooms/{room['id']}/members", json={"user_ids": [self.u["mhs"].id]})
        return room

    def test_share_snapshot_and_student_copy(self) -> None:
        room = self.kelas_with_student()
        rid = room["id"]
        src = self.ws("dosen") / "Praktikum"
        (src / "data").mkdir(parents=True)
        (src / "modul1.ipynb").write_text('{"cells": []}')
        (src / "data" / "x.csv").write_text("a,b\n1,2\n")
        (src / ".ipynb_checkpoints").mkdir()
        (src / ".ipynb_checkpoints" / "junk.ipynb").write_text("{}")
        os.symlink("/etc/passwd", src / "rahasia")
        r = self.client.post(f"/classrooms/{rid}/materials",
                             json={"path": "Praktikum", "title": "Modul 1", "description": "CNN"})
        self.assertEqual(r.status_code, 201, r.text)
        mat = r.json()
        self.assertEqual((mat["kind"], mat["name"], mat["file_count"], mat["copy_count"]),
                         ("dir", "Praktikum", 2, 0))
        # Snapshot: suntingan pengajar setelah dibagikan tidak ikut.
        (src / "modul1.ipynb").write_text("DIUBAH")

        self.as_("mhs")
        lst = self.client.get(f"/classrooms/{rid}/materials").json()
        self.assertEqual(len(lst), 1)
        self.assertIsNone(lst[0]["copy_count"])
        self.assertIsNone(lst[0]["my_copy_path"])
        r = self.client.post(f"/classrooms/{rid}/materials/{mat['id']}/copy")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["path"], "Kelas/Deep Learning TI-5A/Praktikum")
        dest = self.ws("mhs") / r.json()["path"]
        self.assertEqual((dest / "modul1.ipynb").read_text(), '{"cells": []}')
        self.assertTrue((dest / "data" / "x.csv").exists())
        self.assertFalse(os.path.lexists(dest / "rahasia"))
        self.assertFalse((dest / ".ipynb_checkpoints").exists())
        # Ambil lagi -> tidak menimpa, diberi akhiran.
        (dest / "modul1.ipynb").write_text("kerjaan saya")
        again = self.client.post(f"/classrooms/{rid}/materials/{mat['id']}/copy").json()
        self.assertEqual(again["path"], "Kelas/Deep Learning TI-5A/Praktikum (2)")
        self.assertEqual((dest / "modul1.ipynb").read_text(), "kerjaan saya")
        self.assertEqual(again["material"]["my_copy_path"], again["path"])

        self.as_("dosen")
        self.assertEqual(self.client.get(f"/classrooms/{rid}/materials").json()[0]["copy_count"], 1)
        notes = self.db(lambda s: s.scalars(select(Notification).where(Notification.user_id == self.u["mhs"].id)))
        self.assertTrue(any("Modul 1" in n.body for n in notes.all()))

    def test_single_file_suffix_and_permissions(self) -> None:
        room = self.kelas_with_student()
        rid = room["id"]
        (self.ws("dosen") / "tugas.ipynb").write_text("{}")
        self.as_("mhs")
        (self.ws("mhs") / "x.ipynb").write_text("{}")
        self.assertEqual(self.client.post(f"/classrooms/{rid}/materials", json={"path": "x.ipynb"}).status_code, 403)
        self.as_("dosen")
        mat = self.client.post(f"/classrooms/{rid}/materials", json={"path": "tugas.ipynb"}).json()
        self.assertEqual(mat["title"], "tugas.ipynb")
        self.as_("mhs")
        p1 = self.client.post(f"/classrooms/{rid}/materials/{mat['id']}/copy").json()["path"]
        p2 = self.client.post(f"/classrooms/{rid}/materials/{mat['id']}/copy").json()["path"]
        self.assertEqual(p2, "Kelas/Deep Learning TI-5A/tugas (2).ipynb")
        self.assertNotEqual(p1, p2)
        self.as_("mhs2")
        self.assertEqual(self.client.post(f"/classrooms/{rid}/materials/{mat['id']}/copy").status_code, 404)

    def test_rejects_unsafe_sources_and_destinations(self) -> None:
        room = self.kelas_with_student()
        rid = room["id"]
        ws = self.ws("dosen")
        os.symlink("/etc", ws / "link")
        for path in ["link", "../1/x", ".trash", "", "tidak-ada.ipynb"]:
            r = self.client.post(f"/classrooms/{rid}/materials", json={"path": path or "/"})
            self.assertEqual(r.status_code, 400, (path, r.text))
        (ws / "a.ipynb").write_text("{}")
        mat = self.client.post(f"/classrooms/{rid}/materials", json={"path": "a.ipynb"}).json()
        self.as_("mhs")
        outside = self.data / "luar"
        outside.mkdir()
        shutil.rmtree(self.ws("mhs") / "Kelas")  # dibuat otomatis saat bergabung (A4)
        os.symlink(outside, self.ws("mhs") / "Kelas")
        r = self.client.post(f"/classrooms/{rid}/materials/{mat['id']}/copy")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(list(outside.iterdir()), [])
        os.unlink(self.ws("mhs") / "Kelas")
        self.quota_left = 1
        r = self.client.post(f"/classrooms/{rid}/materials/{mat['id']}/copy")
        self.assertEqual(r.status_code, 400)
        self.assertIn("kuota", r.json()["detail"])

    def test_delete_material_and_class_cleans_store(self) -> None:
        room = self.kelas_with_student()
        rid = room["id"]
        (self.ws("dosen") / "a.ipynb").write_text("{}")
        (self.ws("dosen") / "b.ipynb").write_text("{}")
        m1 = self.client.post(f"/classrooms/{rid}/materials", json={"path": "a.ipynb"}).json()
        self.client.post(f"/classrooms/{rid}/materials", json={"path": "b.ipynb"})
        store = self.data / "class-materials" / str(rid)
        self.assertEqual(len(list(store.iterdir())), 2)
        self.as_("mhs")
        self.client.post(f"/classrooms/{rid}/materials/{m1['id']}/copy")
        self.assertEqual(self.client.delete(f"/classrooms/{rid}/materials/{m1['id']}").status_code, 403)
        self.as_("dosen")
        self.assertEqual(self.client.delete(f"/classrooms/{rid}/materials/{m1['id']}").status_code, 204)
        self.assertEqual(len(list(store.iterdir())), 1)
        # Salinan mahasiswa tetap ada.
        self.assertTrue((self.ws("mhs") / "Kelas/Deep Learning TI-5A/a.ipynb").exists())
        self.assertEqual(self.client.delete(f"/classrooms/{rid}").status_code, 204)
        self.assertFalse(store.exists())
        left = self.db(lambda s: s.scalars(select(ClassMaterial)))
        self.assertEqual(left.all(), [])

    # ------------------------------------------------------------ kuota GPU kelas (A3)

    def set_policy(self, **kw) -> None:
        from app.services import policy as policy_svc

        p = mock.patch.object(policy_svc, "_cache", dataclasses.replace(policy_svc.get(), **kw))
        p.start()
        self.addCleanup(p.stop)

    def quota_of(self, key: str) -> int:
        from app.services import user_policy as up

        async def run(s):
            one = (await self.real_effective(s, self.u[key].id)).daily_gpu_seconds_quota
            many = (await up.effective_map(s, {self.u[key].id}))[self.u[key].id].daily_gpu_seconds_quota
            self.assertEqual(one, many)
            return one
        return self.db(run)

    def test_gpu_bonus_cap_and_effective_quota(self) -> None:
        self.set_policy(student_daily_gpu_seconds_quota=3600, dosen_daily_gpu_seconds_quota=7200,
                        class_gpu_bonus_max_seconds=7200)
        room = self.kelas_with_student()
        rid = room["id"]
        self.assertEqual(room["gpu_bonus_max_seconds"], 7200)
        today = quota_svc.local_today()
        end = (today + dt.timedelta(days=30)).isoformat()
        self.assertEqual(self.quota_of("mhs"), 3600)
        r = self.client.put(f"/classrooms/{rid}/gpu-bonus", json={"seconds": 10800, "end": end})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Maksimal", r.json()["detail"])
        for bad in [{"seconds": 3600}, {"seconds": 3600, "end": (today - dt.timedelta(days=1)).isoformat()},
                    {"seconds": 3600, "start": end, "end": today.isoformat()}]:
            self.assertEqual(self.client.put(f"/classrooms/{rid}/gpu-bonus", json=bad).status_code, 400, bad)
        r = self.client.put(f"/classrooms/{rid}/gpu-bonus", json={"seconds": 3600, "end": end})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["gpu_bonus_active"])
        self.assertEqual(r.json()["gpu_bonus_start"], today.isoformat())
        self.assertEqual(self.quota_of("mhs"), 7200)
        self.assertEqual(self.quota_of("dosen"), 7200)  # pengajar tidak ikut mendapat bonus
        self.assertEqual(self.quota_of("mhs2"), 3600)   # bukan anggota
        notes = self.db(lambda s: s.scalars(select(Notification).where(Notification.user_id == self.u["mhs"].id)))
        self.assertTrue(any("Tambahan kuota GPU" in n.title for n in notes.all()))
        # Mahasiswa tidak boleh mengatur.
        self.as_("mhs")
        self.assertEqual(self.client.put(f"/classrooms/{rid}/gpu-bonus", json={"seconds": 0}).status_code, 403)
        # Kelas lain dengan bonus lebih besar (admin bebas plafon) -> ambil yang terbesar.
        self.as_("admin")
        r2 = self.create("Kelas admin")
        self.client.post(f"/classrooms/{r2['id']}/members", json={"user_ids": [self.u["mhs"].id]})
        r = self.client.put(f"/classrooms/{r2['id']}/gpu-bonus", json={"seconds": 14400, "end": end})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.quota_of("mhs"), 3600 + 14400)
        self.client.patch(f"/classrooms/{r2['id']}", json={"archived": True})
        self.assertEqual(self.quota_of("mhs"), 7200)
        # Hapus bonus.
        self.as_("dosen")
        r = self.client.put(f"/classrooms/{rid}/gpu-bonus", json={"seconds": 0})
        self.assertEqual((r.json()["gpu_bonus_seconds"], r.json()["gpu_bonus_end"]), (0, None))
        self.assertEqual(self.quota_of("mhs"), 3600)

    def test_gpu_bonus_disabled_for_dosen_and_unlimited_untouched(self) -> None:
        self.set_policy(student_daily_gpu_seconds_quota=0, class_gpu_bonus_max_seconds=0)
        room = self.kelas_with_student()
        end = (quota_svc.local_today() + dt.timedelta(days=7)).isoformat()
        r = self.client.put(f"/classrooms/{room['id']}/gpu-bonus", json={"seconds": 3600, "end": end})
        self.assertEqual(r.status_code, 403)
        self.as_("admin")
        r = self.client.put(f"/classrooms/{room['id']}/gpu-bonus", json={"seconds": 3600, "end": end})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.quota_of("mhs"), 0)  # 0 = tanpa batas, tidak berubah


    # ------------------------------------------------ A4: ruang kerja & pantau kelas

    def test_class_folder_created_and_monitor_reads_only_it(self) -> None:
        room = self.kelas_with_student()
        rid = room["id"]
        kelas = self.ws("mhs") / "Kelas" / "Deep Learning TI-5A"
        self.assertTrue(kelas.is_dir())
        self.assertIn("autoSaveDelay", (kelas / ".vscode" / "settings.json").read_text())
        # Pengaturan milik mahasiswa tidak ditimpa.
        (kelas / ".vscode" / "settings.json").write_text("{}")
        self.as_("mhs2")
        self.client.post("/classrooms/join", json={"code": room["code"]})
        self.assertTrue((self.ws("mhs2") / "Kelas" / "Deep Learning TI-5A").is_dir())

        self.as_("mhs")
        r = self.client.get(f"/classrooms/{rid}/workspace")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"path": "Kelas/Deep Learning TI-5A",
                                    "folder": "Deep Learning TI-5A", "monitored": True})
        self.assertEqual((kelas / ".vscode" / "settings.json").read_text(), "{}")
        self.assertEqual(self.client.get(f"/classrooms/{rid}/monitor").status_code, 403)
        (kelas / "src").mkdir()
        (kelas / "src" / "main.py").write_text("print('halo')\n")
        nb = {"cells": [{"cell_type": "markdown", "source": ["# Judul"]},
                        {"cell_type": "code", "source": ["import torch\n", "x = 1"]}]}
        (kelas / "tugas.ipynb").write_text(__import__("json").dumps(nb))
        os.utime(kelas / "src" / "main.py", (1, 1))
        (self.ws("mhs") / "pribadi.txt").write_text("rahasia")

        self.as_("dosen")
        self.client.patch(f"/classrooms/{rid}", json={"name": "Nama Baru"})
        tiles = {t["name"]: t for t in self.client.get(f"/classrooms/{rid}/monitor").json()}
        ani = tiles["Ani"]
        self.assertEqual((ani["file_count"], ani["last_file"], ani["devbox_state"]), (2, "tugas.ipynb", "stopped"))
        self.assertEqual(ani["snippet"], "import torch\nx = 1")
        self.assertEqual(tiles["Budi"]["file_count"], 0)
        uid = self.u["mhs"].id
        tree = self.client.get(f"/classrooms/{rid}/monitor/{uid}/tree").json()
        self.assertEqual([e["name"] for e in tree], ["src", "tugas.ipynb"])
        self.client.get(f"/classrooms/{rid}/monitor/{uid}/tree", params={"path": "src"})
        f = self.client.get(f"/classrooms/{rid}/monitor/{uid}/file", params={"path": "src/main.py"}).json()
        self.assertEqual((f["content"], f["language"]), ("print('halo')\n", "python"))
        for bad in ("../../pribadi.txt", ".vscode/settings.json", "/etc/passwd"):
            r = self.client.get(f"/classrooms/{rid}/monitor/{uid}/file", params={"path": bad})
            self.assertEqual(r.status_code, 404, bad)
        audits = self.db(lambda s: s.scalars(select(AuditLog).where(AuditLog.action == "class.monitor_view")))
        self.assertEqual(len(audits.all()), 1)
        # Nama folder tetap walau kelas diganti nama.
        self.as_("mhs")
        self.assertEqual(self.client.get(f"/classrooms/{rid}/workspace").json()["folder"], "Deep Learning TI-5A")

    def test_monitor_rejects_symlinks_and_left_students(self) -> None:
        room = self.kelas_with_student()
        rid = room["id"]
        uid = self.u["mhs"].id
        kelas = self.ws("mhs") / "Kelas" / "Deep Learning TI-5A"
        (self.ws("mhs") / "pribadi.txt").write_text("rahasia")
        os.symlink(self.ws("mhs") / "pribadi.txt", kelas / "tautan.txt")
        os.symlink(self.ws("mhs"), kelas / "home")
        (kelas / "biner.bin").write_bytes(b"\x00\x01")
        tree = self.client.get(f"/classrooms/{rid}/monitor/{uid}/tree").json()
        self.assertEqual([e["name"] for e in tree], ["biner.bin"])
        for bad in ("tautan.txt", "home/pribadi.txt"):
            r = self.client.get(f"/classrooms/{rid}/monitor/{uid}/file", params={"path": bad})
            self.assertEqual(r.status_code, 404, bad)
        f = self.client.get(f"/classrooms/{rid}/monitor/{uid}/file", params={"path": "biner.bin"}).json()
        self.assertEqual((f["content"], f["reason"]), (None, "binary"))
        tile = self.client.get(f"/classrooms/{rid}/monitor").json()[0]
        self.assertEqual(tile["file_count"], 1)
        # Mahasiswa keluar -> tidak bisa dipantau lagi, foldernya tetap miliknya.
        self.as_("mhs")
        self.assertEqual(self.client.post(f"/classrooms/{rid}/leave").status_code, 204)
        self.as_("dosen")
        self.assertEqual(self.client.get(f"/classrooms/{rid}/monitor").json(), [])
        self.assertEqual(self.client.get(f"/classrooms/{rid}/monitor/{uid}/tree").status_code, 404)
        self.assertTrue((kelas / "biner.bin").exists())
        # Pengajar tidak bisa dipantau via endpoint ini.
        me = self.u["dosen"].id
        self.assertEqual(self.client.get(f"/classrooms/{rid}/monitor/{me}/tree").status_code, 404)

    def test_same_class_name_gets_distinct_folder(self) -> None:
        a = self.kelas_with_student()
        b = self.kelas_with_student()
        self.as_("mhs")
        fa = self.client.get(f"/classrooms/{a['id']}/workspace").json()["folder"]
        fb = self.client.get(f"/classrooms/{b['id']}/workspace").json()["folder"]
        self.assertEqual(fa, "Deep Learning TI-5A")
        self.assertEqual(fb, f"Deep Learning TI-5A ({b['id']})")
        self.as_("admin")
        self.assertEqual(self.client.get(f"/classrooms/{a['id']}/workspace").status_code, 404)

if __name__ == "__main__":
    unittest.main()
