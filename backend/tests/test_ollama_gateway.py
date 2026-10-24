"""Uji gerbang Ollama: kunci API, batas laju/konkurensi, allowlist model, admin CRUD.

Catatan: jalur HTTP Bearer tidak diuji di sini karena harness menyamarkan header
`Authorization: Bearer`. Logika autentikasi diuji langsung lewat `find_valid_key`.

Jalankan DALAM container app:
  docker exec -e PYTHONDONTWRITEBYTECODE=1 -w <repo>/backend ComputeHub-app \
      python -m unittest tests.test_ollama_gateway
"""

from __future__ import annotations

import asyncio
import datetime as dt
import tempfile
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routers import ollama_gateway as rr
from app.models.ollama_key import OllamaApiKey
from app.services import ollama_gateway as gw


def _run(coro):
    return asyncio.run(coro)


class OllamaKeyHelperTests(unittest.TestCase):
    def test_hash_prefix_unik(self) -> None:
        raw1, pfx1, h1 = gw.generate_key()
        raw2, _, h2 = gw.generate_key()
        self.assertTrue(raw1.startswith("ch-ollama-"))
        self.assertEqual(len(pfx1), len("ch-ollama-") + 6)
        self.assertNotEqual(h1, h2)
        self.assertEqual(gw.hash_key(raw1), h1)
        self.assertNotEqual(raw1, raw2)

    def test_models_list(self) -> None:
        k = OllamaApiKey(allowed_models="gemma3:27b\n  qwen2.5:7b  \n\n")
        self.assertEqual(k.models_list(), ["gemma3:27b", "qwen2.5:7b"])

    def test_enforce_model(self) -> None:
        k = OllamaApiKey(allowed_models="gemma3:27b")
        rr._enforce_model(k, "gemma3:27b")  # tidak melempar
        with self.assertRaises(HTTPException) as c1:
            rr._enforce_model(k, "qwen3.6:latest")
        self.assertEqual(c1.exception.status_code, 403)
        with self.assertRaises(HTTPException) as c2:
            rr._enforce_model(k, None)
        self.assertEqual(c2.exception.status_code, 400)

    def test_cap_tokens_openai(self) -> None:
        k = OllamaApiKey(max_tokens=100)
        b = {"max_tokens": 99999}
        rr._cap_tokens(k, b, True)
        self.assertEqual(b["max_tokens"], 100)
        b2: dict = {}
        rr._cap_tokens(k, b2, True)
        self.assertEqual(b2["max_tokens"], 100)
        b3 = {"max_tokens": 50}
        rr._cap_tokens(k, b3, True)
        self.assertEqual(b3["max_tokens"], 50)

    def test_cap_tokens_native_dan_tanpa_batas(self) -> None:
        k = OllamaApiKey(max_tokens=100)
        b: dict = {}
        rr._cap_tokens(k, b, False)
        self.assertEqual(b["options"]["num_predict"], 100)
        b2 = {"options": {"num_predict": 999}}
        rr._cap_tokens(k, b2, False)
        self.assertEqual(b2["options"]["num_predict"], 100)
        k0 = OllamaApiKey(max_tokens=0)
        b3 = {"max_tokens": 123}
        rr._cap_tokens(k0, b3, True)
        self.assertEqual(b3, {"max_tokens": 123})


class LimiterTests(unittest.TestCase):
    def test_batas_laju(self) -> None:
        lim = gw._Limiter()

        async def jalan():
            r1 = await lim.acquire(1, rate_per_min=1, max_concurrent=10)
            r2 = await lim.acquire(1, rate_per_min=1, max_concurrent=10)
            return r1, r2

        r1, r2 = _run(jalan())
        self.assertIsNone(r1)
        self.assertIsNotNone(r2)
        self.assertIn("permintaan/menit", r2)

    def test_batas_konkurensi(self) -> None:
        lim = gw._Limiter()

        async def jalan():
            r1 = await lim.acquire(5, rate_per_min=1000, max_concurrent=1)
            r2 = await lim.acquire(5, rate_per_min=1000, max_concurrent=1)
            await lim.release(5)
            r3 = await lim.acquire(5, rate_per_min=1000, max_concurrent=1)
            return r1, r2, r3

        r1, r2, r3 = _run(jalan())
        self.assertIsNone(r1)
        self.assertIn("bersamaan", r2)
        self.assertIsNone(r3)


class FindValidKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="ch-ollk-")
        self.addCleanup(tmp.cleanup)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/g.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def mk():
            async with self.engine.begin() as conn:
                await conn.run_sync(
                    lambda c: OllamaApiKey.metadata.create_all(c, tables=[OllamaApiKey.__table__])
                )

        _run(mk())

    def _tambah(self, raw: str, **kw) -> None:
        async def t():
            async with self.sessions() as s:
                s.add(OllamaApiKey(name="x", key_prefix=raw[:16], key_hash=gw.hash_key(raw), **kw))
                await s.commit()

        _run(t())

    def _cari(self, raw: str):
        async def c():
            async with self.sessions() as s:
                return await gw.find_valid_key(s, raw)

        return _run(c())

    def test_valid(self) -> None:
        raw, _, _ = gw.generate_key()
        self._tambah(raw, enabled=True, allowed_models="gemma3:27b")
        k = self._cari(raw)
        self.assertIsNotNone(k)
        self.assertEqual(k.models_list(), ["gemma3:27b"])

    def test_nonaktif(self) -> None:
        raw, _, _ = gw.generate_key()
        self._tambah(raw, enabled=False)
        self.assertIsNone(self._cari(raw))

    def test_kedaluwarsa(self) -> None:
        raw, _, _ = gw.generate_key()
        lampau = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        self._tambah(raw, enabled=True, expires_at=lampau)
        self.assertIsNone(self._cari(raw))

    def test_kunci_salah_dan_kosong(self) -> None:
        raw, _, _ = gw.generate_key()
        self._tambah(raw, enabled=True)
        self.assertIsNone(self._cari("ch-ollama-salah"))
        self.assertIsNone(self._cari(""))
        self.assertIsNone(self._cari("tanpa-prefix"))


class AdminCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import require_admin
        from app.api.routers import ollama_keys
        from app.core.database import get_db
        from app.models.audit import AuditLog

        tmp = tempfile.TemporaryDirectory(prefix="ch-ollk-crud-")
        self.addCleanup(tmp.cleanup)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}/g.db", poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def get_test_db():
            async with self.sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(ollama_keys.router, prefix="/admin/ollama-keys")
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1, role="admin", email="adm@x.id")
        app.dependency_overrides[get_db] = get_test_db
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        async def mk():
            async with self.engine.begin() as conn:
                await conn.run_sync(
                    lambda c: OllamaApiKey.metadata.create_all(
                        c, tables=[OllamaApiKey.__table__, AuditLog.__table__]
                    )
                )

        _run(mk())

    def test_buat_ubah_cabut(self) -> None:
        r = self.client.post(
            "/admin/ollama-keys",
            json={"name": "Teman A", "allowed_models": ["gemma3:27b"], "max_tokens": 100},
        )
        self.assertEqual(r.status_code, 201, r.text)
        data = r.json()
        self.assertTrue(data["key"].startswith("ch-ollama-"))
        kid = data["id"]

        lst = self.client.get("/admin/ollama-keys").json()
        self.assertEqual(len(lst), 1)
        self.assertNotIn("key", lst[0])
        self.assertEqual(lst[0]["allowed_models"], ["gemma3:27b"])

        u = self.client.patch(f"/admin/ollama-keys/{kid}", json={"enabled": False, "rate_per_min": 5})
        self.assertEqual(u.status_code, 200, u.text)
        self.assertFalse(u.json()["enabled"])
        self.assertEqual(u.json()["rate_per_min"], 5)

        d = self.client.delete(f"/admin/ollama-keys/{kid}")
        self.assertEqual(d.status_code, 204, d.text)
        self.assertEqual(self.client.get("/admin/ollama-keys").json(), [])

    def test_patch_404(self) -> None:
        self.assertEqual(self.client.patch("/admin/ollama-keys/999", json={"name": "x"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
