"""Uji unit fitur baru backend yang TIDAK bisa diuji E2E dgn aman di server produksi
bersama: guard kuota disk /persist, reaper container job yatim, & alert per-user.

Semua deterministik & terisolasi (temp dir + mock) — TIDAK menyentuh DB live, docker,
email, atau GPU. Melengkapi suite Playwright (yang menguji jalur UI/API non-destruktif).

Cara menjalankan (dari folder backend/, tanpa perlu pytest):
    .venv/bin/python -m tests.test_storage_guard
Atau bila pytest tersedia:
    .venv/bin/python -m pytest tests/test_storage_guard.py -q
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.services import alerts as alerts_svc
from app.services import jobruntime
from app.services import storage_guard as sg


# ----------------------------------------------------------------- helpers uji
def _mk(root: Path, uid: str, size_bytes: int) -> None:
    d = root / uid
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.bin").write_bytes(b"\0" * size_bytes)


class _FakeUser:
    def __init__(self, uid: int, email: str, name: str, is_super: bool) -> None:
        self.id = uid
        self.email = email
        self.name = name
        self.is_superadmin = is_super


class _FakeEff:
    def __init__(self, quota_mb: float) -> None:
        self.max_storage_mb = quota_mb


class _FakeSession:
    """Pengganti AsyncSessionLocal() -> context manager async dgn .get(User, id)."""

    def __init__(self, users: dict[int, _FakeUser]) -> None:
        self._users = users

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_a) -> bool:
        return False

    async def get(self, _model, uid):  # noqa: ANN001
        return self._users.get(uid)


# ----------------------------------------------------------------- #1 kuota disk
def test_scan_disk_parsing() -> None:
    """`du -bd1` -> {user_id: bytes}; folder non-numerik & root diabaikan."""

    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "users"
            root.mkdir()
            _mk(root, "1", 3 * 1024 * 1024)   # ~3 MB
            _mk(root, "2", 1 * 1024 * 1024)   # ~1 MB
            (root / "notanumber").mkdir()      # harus diabaikan
            old = settings.DOCKER_USER_DATA_ROOT
            settings.DOCKER_USER_DATA_ROOT = str(root)
            try:
                res = await sg._scan_disk()
            finally:
                settings.DOCKER_USER_DATA_ROOT = old
        assert set(res.keys()) == {1, 2}, res
        assert res[1] >= 3 * 1024 * 1024, res
        assert 1 * 1024 * 1024 <= res[2] < 2 * 1024 * 1024, res

    asyncio.run(run())


def test_scan_disk_missing_root() -> None:
    """Root belum ada -> {} (tanpa error)."""

    async def run() -> None:
        old = settings.DOCKER_USER_DATA_ROOT
        settings.DOCKER_USER_DATA_ROOT = "/tmp/ch_tidak_ada_xyz_12345/users"
        try:
            assert await sg._scan_disk() == {}
        finally:
            settings.DOCKER_USER_DATA_ROOT = old

    asyncio.run(run())


def test_tick_over_warning_and_exemptions() -> None:
    """user over(>=100%) -> cache _over + enforce + alert PENUH; warning(>=90%) -> alert saja;
    kuota 0 -> diabaikan; super admin -> dikecualikan."""

    async def run() -> None:
        usage = {
            1: 120 * 1024 * 1024,  # 120MB / kuota 100 -> OVER
            2: 95 * 1024 * 1024,   # 95MB  / kuota 100 -> WARNING (>=90%)
            3: 500 * 1024 * 1024,  # kuota 0 -> tanpa batas (diabaikan)
            4: 999 * 1024 * 1024,  # super admin (dikecualikan)
            5: 10 * 1024 * 1024,   # 10MB / kuota 100 -> di bawah ambang (tak ada aksi)
        }
        quotas = {1: 100.0, 2: 100.0, 3: 0.0, 4: 100.0, 5: 100.0}
        users = {
            1: _FakeUser(1, "a@x.id", "A", False),
            2: _FakeUser(2, "b@x.id", "B", False),
            3: _FakeUser(3, "c@x.id", "C", False),
            4: _FakeUser(4, "super@x.id", "S", True),
            5: _FakeUser(5, "e@x.id", "E", False),
        }
        notified: list[dict] = []
        enforced: list[int] = []

        async def fake_effective(_db, uid):  # noqa: ANN001
            return _FakeEff(quotas[uid])

        async def fake_notify(_db, **kw):  # noqa: ANN001
            notified.append(kw)

        async def fake_enforce(uid):  # noqa: ANN001
            enforced.append(uid)

        sg._over.clear()
        sg._usage.clear()
        with patch.object(sg, "_scan_disk", return_value=usage), \
             patch.object(sg.user_policy_svc, "effective", side_effect=fake_effective), \
             patch.object(sg, "AsyncSessionLocal", lambda: _FakeSession(users)), \
             patch.object(alerts_svc, "notify", side_effect=fake_notify), \
             patch.object(sg, "_enforce_user", side_effect=fake_enforce), \
             patch.object(settings, "STORAGE_ENFORCE_ENABLED", True), \
             patch.object(settings, "STORAGE_ALERT_PERCENT", 90.0):
            await sg._tick()

        # Admission cache: hanya user 1 yang "over".
        assert sg.is_over_quota(1) is True, sg._over
        for uid in (2, 3, 4, 5):
            assert sg.is_over_quota(uid) is False, (uid, sg._over)
        # Enforcement hanya untuk user over.
        assert enforced == [1], enforced
        # Alert: user 1 (PENUH) & user 2 (warning); bukan 3/4/5.
        subjects = sorted(n["subject"] for n in notified)
        assert subjects == ["a@x.id", "b@x.id"], subjects
        flags = {n["subject"]: ("PENUH" in n["message"]) for n in notified}
        assert flags["a@x.id"] is True and flags["b@x.id"] is False, flags
        # Snapshot terisi & benar.
        snap = sg.usage_snapshot()
        assert snap[1]["quota_mb"] == 100.0 and snap[1]["used_mb"] >= 120.0, snap[1]

    asyncio.run(run())


def test_tick_enforce_disabled_no_kill() -> None:
    """STORAGE_ENFORCE_ENABLED=False -> tetap tandai over + alert, TAPI tak hentikan job/sesi."""

    async def run() -> None:
        usage = {7: 200 * 1024 * 1024}
        users = {7: _FakeUser(7, "g@x.id", "G", False)}
        enforced: list[int] = []

        async def fake_effective(_db, _uid):  # noqa: ANN001
            return _FakeEff(100.0)

        async def fake_notify(_db, **_kw):  # noqa: ANN001
            return None

        async def fake_enforce(uid):  # noqa: ANN001
            enforced.append(uid)

        sg._over.clear()
        sg._usage.clear()
        with patch.object(sg, "_scan_disk", return_value=usage), \
             patch.object(sg.user_policy_svc, "effective", side_effect=fake_effective), \
             patch.object(sg, "AsyncSessionLocal", lambda: _FakeSession(users)), \
             patch.object(alerts_svc, "notify", side_effect=fake_notify), \
             patch.object(sg, "_enforce_user", side_effect=fake_enforce), \
             patch.object(settings, "STORAGE_ENFORCE_ENABLED", False):
            await sg._tick()

        assert sg.is_over_quota(7) is True   # admission gate tetap aktif
        assert enforced == []                # tapi tak ada job/sesi yang dihentikan

    asyncio.run(run())


def test_tick_empty_scan_clears_cache() -> None:
    """Scan kosong -> cache over/usage dibersihkan (tak ada false-positive tertinggal)."""

    async def run() -> None:
        sg._over.add(999)
        sg._usage[999] = {"used_mb": 1.0, "quota_mb": 1.0, "ratio": 1.0}
        with patch.object(sg, "_scan_disk", return_value={}):
            await sg._tick()
        assert sg._over == set()
        assert sg._usage == {}

    asyncio.run(run())


# ----------------------------------------------------------------- #2 reaper
def test_job_container_name() -> None:
    assert jobruntime.job_container_name(42) == "ch-job-42"


def test_cleanup_orphan_noop_when_disabled() -> None:
    """Provision docker nonaktif -> reaper no-op & TIDAK memanggil docker (aman)."""

    async def run() -> None:
        called = {"n": 0}

        async def _boom(*_a, **_k):  # noqa: ANN001
            called["n"] += 1
            raise AssertionError("docker tak boleh dipanggil saat provision nonaktif")

        with patch.object(jobruntime.provision, "is_enabled", return_value=False), \
             patch("asyncio.create_subprocess_exec", side_effect=_boom):
            await jobruntime.cleanup_orphan_job_containers()  # tak boleh raise
        assert called["n"] == 0

    asyncio.run(run())


# ----------------------------------------------------------------- #3 alerts.notify
def test_notify_skips_when_alerts_disabled() -> None:
    """AlertConfig.enabled=False -> notify() return None & tak mengirim email."""

    async def run() -> None:
        class _Cfg:
            enabled = False
            cooldown_minutes = 60

        emitted: list = []

        async def fake_get_config(_s):  # noqa: ANN001
            return _Cfg()

        async def fake_emit(*_a, **_k):  # noqa: ANN001
            emitted.append(1)

        with patch.object(alerts_svc, "get_config", side_effect=fake_get_config), \
             patch.object(alerts_svc, "_emit", side_effect=fake_emit):
            res = await alerts_svc.notify(
                None, scope="persist_user", subject="a@x.id", metric="storage",
                value=1.0, threshold=1.0, message="x",
            )
        assert res is None and emitted == []

    asyncio.run(run())


def test_notify_skips_when_in_cooldown() -> None:
    """Masih dalam cooldown -> notify() return None (anti spam email)."""

    async def run() -> None:
        class _Cfg:
            enabled = True
            cooldown_minutes = 60

        emitted: list = []

        async def fake_get_config(_s):  # noqa: ANN001
            return _Cfg()

        async def fake_cooldown(_s, _subj, _metric, _min):  # noqa: ANN001
            return True

        async def fake_emit(*_a, **_k):  # noqa: ANN001
            emitted.append(1)

        with patch.object(alerts_svc, "get_config", side_effect=fake_get_config), \
             patch.object(alerts_svc, "_in_cooldown", side_effect=fake_cooldown), \
             patch.object(alerts_svc, "_emit", side_effect=fake_emit):
            res = await alerts_svc.notify(
                None, scope="persist_user", subject="a@x.id", metric="storage",
                value=1.0, threshold=1.0, message="x",
            )
        assert res is None and emitted == []

    asyncio.run(run())


def test_notify_emits_when_enabled_and_not_cooldown() -> None:
    """Alert aktif & tidak cooldown -> _emit dipanggil dgn breach yang benar."""

    async def run() -> None:
        class _Cfg:
            enabled = True
            cooldown_minutes = 60

        captured: dict = {}

        async def fake_get_config(_s):  # noqa: ANN001
            return _Cfg()

        async def fake_cooldown(_s, _subj, _metric, _min):  # noqa: ANN001
            return False

        async def fake_emit(_s, _cfg, breach):  # noqa: ANN001
            captured.update(breach)
            return "ALERT"

        with patch.object(alerts_svc, "get_config", side_effect=fake_get_config), \
             patch.object(alerts_svc, "_in_cooldown", side_effect=fake_cooldown), \
             patch.object(alerts_svc, "_emit", side_effect=fake_emit):
            res = await alerts_svc.notify(
                None, scope="persist_user", subject="a@x.id", metric="storage",
                value=120.0, threshold=100.0, message="penuh",
            )
        assert res == "ALERT"
        assert captured["scope"] == "persist_user"
        assert captured["subject"] == "a@x.id"
        assert captured["metric"] == "storage"
        assert captured["value"] == 120.0 and captured["threshold"] == 100.0

    asyncio.run(run())


# ----------------------------------------------------------------- runner standalone
def _run_all() -> int:
    tests = sorted(
        (name, fn)
        for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    )
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {exc!r}")
        else:
            passed += 1
            print(f"ok    {name}")
    print(f"\n{passed} lulus, {failed} gagal (total {len(tests)}).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
