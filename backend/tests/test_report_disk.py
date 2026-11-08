"""Uji unit perilaku `report_svc.disk_usage(force=...)` (PR #4).

Fokus: memastikan parameter `force` memaksa recompute DI LATAR walau cache belum
basi, TANPA memblokir (data lama tetap dikembalikan + flag `computing`), dan tanpa
penjadwalan dobel saat recompute sudah berjalan.

Deterministik & terisolasi: `_compute_disk` di-mock (tidak menyentuh docker/`du`/disk
nyata). Melengkapi test E2E Playwright.

Cara menjalankan (dari folder backend/):
    .venv/bin/python -m tests.test_report_disk
Atau: .venv/bin/python -m pytest tests/test_report_disk.py -q
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.services import report as report_svc


def _reset_cache(data=None, ts=0.0, computing=False) -> None:
    report_svc._disk_cache["data"] = data
    report_svc._disk_cache["ts"] = ts
    report_svc._disk_cache["computing"] = computing


_SAMPLE = {
    "total_bytes": 100,
    "used_bytes": 40,
    "free_bytes": 60,
    "used_percent": 40.0,
    "users": [{"user": "a", "bytes": 10}],
    "computed_at": "2026-11-09T00:00:00+00:00",
}


def test_force_recompute_walau_cache_segar() -> None:
    """force=True menjadwalkan recompute walau cache masih segar; data lama tetap
    dikembalikan dengan computing=True (tidak memblokir, tidak mengosongkan)."""

    async def run() -> None:
        import time as _t

        fresh = {**_SAMPLE, "used_bytes": 40}
        _reset_cache(data=fresh, ts=_t.time(), computing=False)  # cache SANGAT segar

        baru = {**_SAMPLE, "used_bytes": 99, "used_percent": 99.0}

        async def fake_compute() -> dict:
            return baru

        with patch.object(report_svc, "_compute_disk", side_effect=fake_compute):
            # Tanpa force: cache segar -> TIDAK recompute, data lama apa adanya.
            r1 = await report_svc.disk_usage(force=False)
            assert r1["used_bytes"] == 40
            assert r1["computing"] is False

            # Dengan force: data lama tetap dikembalikan + computing True (non-blok).
            r2 = await report_svc.disk_usage(force=True)
            assert r2["used_bytes"] == 40, "data lama harus tetap tampil (tak kosong)"
            assert r2["computing"] is True, "harus menandai sedang menghitung"

            # Biarkan task latar selesai, lalu nilai ter-update DI TEMPAT.
            for _ in range(50):
                await asyncio.sleep(0.01)
                if not report_svc._disk_cache["computing"]:
                    break
            assert report_svc._disk_cache["computing"] is False
            r3 = await report_svc.disk_usage(force=False)
            assert r3["used_bytes"] == 99, "nilai harus diperbarui setelah recompute"

    asyncio.run(run())
    _reset_cache()


def test_force_tak_menjadwalkan_dobel() -> None:
    """Bila recompute sudah berjalan (computing=True), force kedua tidak memicu
    _compute_disk lagi (hindari dobel)."""

    async def run() -> None:
        import time as _t

        _reset_cache(data=dict(_SAMPLE), ts=_t.time(), computing=True)  # sedang hitung

        calls = {"n": 0}

        async def fake_compute() -> dict:
            calls["n"] += 1
            return dict(_SAMPLE)

        with patch.object(report_svc, "_compute_disk", side_effect=fake_compute):
            r = await report_svc.disk_usage(force=True)
            assert r["computing"] is True
            await asyncio.sleep(0.05)
            assert calls["n"] == 0, "tidak boleh menjadwalkan recompute dobel"

    asyncio.run(run())
    _reset_cache()


def test_tanpa_data_kembalikan_computing() -> None:
    """Cache kosong -> kembalikan kerangka kosong dgn computing=True + jadwalkan hitung."""

    async def run() -> None:
        _reset_cache(data=None, ts=0.0, computing=False)

        async def fake_compute() -> dict:
            return dict(_SAMPLE)

        with patch.object(report_svc, "_compute_disk", side_effect=fake_compute):
            r = await report_svc.disk_usage(force=False)
            assert r["users"] == []
            assert r["computing"] is True
            for _ in range(50):
                await asyncio.sleep(0.01)
                if not report_svc._disk_cache["computing"]:
                    break
            assert report_svc._disk_cache["data"] is not None

    asyncio.run(run())
    _reset_cache()


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
