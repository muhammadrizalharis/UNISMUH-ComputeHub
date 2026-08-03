"""Riwayat pemakaian resource PER USER OS (arsip harian).

Laporan "siapa memakai apa" sebelumnya hanya LANGSUNG (saat itu juga) — begitu
momennya lewat, datanya hilang. Modul ini menyimpan cuplikan berkala pemakaian
tiap user OS (termasuk AKUN LAYANAN seperti `ollama`, karena bebannya justru
sering jadi pertanyaan) sehingga riwayat harian bisa direkonstruksi kapan pun
diminta — mis. sebagai bukti untuk laporan/skripsi.

Selaras kebijakan arsip permanen: baris TIDAK pernah dihapus otomatis. Ukuran
tetap kecil: ~21 user x 1 cuplikan/5 menit ~ 6 ribu baris/hari (beberapa MB/tahun).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import Float, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.usage_history import OsUserSample
from app.services import report as report_svc

logger = get_logger(__name__)


class UsageHistoryRecorder:
    """Tugas latar: cuplik pemakaian per user OS lalu simpan ke DB."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def interval(self) -> float:
        return max(60.0, float(settings.USAGE_HISTORY_INTERVAL_SECONDS))

    async def start(self) -> None:
        if self._task is not None or settings.USAGE_HISTORY_INTERVAL_SECONDS <= 0:
            if settings.USAGE_HISTORY_INTERVAL_SECONDS <= 0:
                logger.info("UsageHistoryRecorder nonaktif (interval 0).")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="usage-history")
        logger.info("UsageHistoryRecorder jalan (tiap %.0f dtk).", self.interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.record_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Rekam riwayat pemakaian gagal: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    async def record_once(self) -> int:
        """Satu cuplikan; kembalikan jumlah baris tersimpan."""
        usage = await report_svc.os_usage()
        rows = usage.get("os_users") or []
        if not rows:
            return 0
        now = dt.datetime.now(dt.timezone.utc)
        async with AsyncSessionLocal() as session:
            for u in rows:
                session.add(
                    OsUserSample(
                        ts=now,
                        username=u["username"],
                        cpu_percent=float(u.get("cpu_percent") or 0.0),
                        memory_mb=float(u.get("memory_mb") or 0.0),
                        vram_mb=float(u.get("vram_mb") or 0.0),
                        processes=int(u.get("processes") or 0),
                        activity=str(u.get("activity") or "")[:64],
                        is_system=bool(u.get("is_system")),
                    )
                )
            await session.commit()
        return len(rows)


usage_history = UsageHistoryRecorder()


def _lokal(col):
    """Ubah timestamptz -> waktu LOKAL server agar batas tanggal & jam masuk akal.

    Sesi Postgres berjalan di UTC. Tanpa konversi ini, aktivitas pukul 00:00-08:00
    WITA tercatat pada TANGGAL SEBELUMNYA -> rekap harian menyesatkan.
    """
    if not settings.is_postgres:
        return col
    return func.timezone(settings.REPORT_TIMEZONE, col)


def _menit_per_cuplikan() -> float:
    return max(60.0, float(settings.USAGE_HISTORY_INTERVAL_SECONDS)) / 60.0


def _sejak(days: int) -> dt.datetime:
    """Batas awal rentang. `days <= 0` = "hari ini", yaitu sejak tengah malam LOKAL
    (bukan 24 jam terakhir, agar tidak tercampur data kemarin).
    """
    if days <= 0:
        kini = dt.datetime.now(ZoneInfo(settings.REPORT_TIMEZONE))
        awal = kini.replace(hour=0, minute=0, second=0, microsecond=0)
        return awal.astimezone(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)


def _cuplikan_aktif():
    return func.sum(
        func.cast(
            (OsUserSample.cpu_percent > 5.0) | (OsUserSample.vram_mb > 0.0), Integer
        )
    )


async def daftar_user(
    session: AsyncSession, *, days: int = 30, include_system: bool = True
) -> dict:
    """Daftar user yang PUNYA data pada rentang ini -> isi menu pilih user.

    Sengaja tidak ikut tersaring oleh pilihan user aktif, supaya menu tetap penuh
    setelah satu user dipilih.
    """
    from app.models.job import Job
    from app.models.user import User

    sejak = _sejak(days)
    q = (
        select(
            OsUserSample.username,
            func.bool_or(OsUserSample.is_system).label("is_system"),
        )
        .where(OsUserSample.ts >= sejak)
        .group_by(OsUserSample.username)
        .order_by(OsUserSample.username)
    )
    if not include_system:
        q = q.where(OsUserSample.is_system.is_(False))
    os_users = [
        {"username": r.username, "is_system": bool(r.is_system)}
        for r in (await session.execute(q)).all()
    ]

    q2 = (
        select(
            User.id,
            func.max(User.name).label("nama"),
            func.max(User.email).label("email"),
            func.count(Job.id).label("jobs"),
        )
        .select_from(Job)
        .join(User, Job.user_id == User.id)
        .where(Job.finished_at.is_not(None), Job.finished_at >= sejak)
        .group_by(User.id)
        .order_by(func.max(User.name))
    )
    ch_users = [
        {
            "user_id": r.id,
            "nama": r.nama or "",
            "email": r.email or "",
            "jobs": int(r.jobs or 0),
        }
        for r in (await session.execute(q2)).all()
    ]
    return {"os": os_users, "computehub": ch_users}


async def hourly_detail(
    session: AsyncSession, *, username: str, days: int = 7, limit: int = 720
) -> list[dict]:
    """Rincian PER JAM satu user OS (terbaru dulu) -> jawab "jam berapa dia pakai"."""
    sejak = _sejak(days)
    jam = func.date_trunc("hour", _lokal(OsUserSample.ts))
    q = (
        select(
            jam.label("jam"),
            func.count().label("cuplikan"),
            func.avg(OsUserSample.cpu_percent).label("cpu_avg"),
            func.max(OsUserSample.cpu_percent).label("cpu_max"),
            func.max(OsUserSample.memory_mb).label("ram_max"),
            func.max(OsUserSample.vram_mb).label("vram_max"),
            func.max(OsUserSample.processes).label("proses_max"),
            func.max(func.cast(OsUserSample.activity, String)).label("aktivitas"),
            _cuplikan_aktif().label("cuplikan_aktif"),
        )
        .where(OsUserSample.ts >= sejak, OsUserSample.username == username)
        .group_by(jam)
        .order_by(jam.desc())
        .limit(max(1, limit))
    )
    menit = _menit_per_cuplikan()
    hasil: list[dict] = []
    for r in (await session.execute(q)).all():
        t: dt.datetime = r.jam
        hasil.append(
            {
                "tanggal": f"{t:%Y-%m-%d}",
                "jam": f"{t:%H:00}",
                "rentang": f"{t:%H:00}–{t + dt.timedelta(hours=1):%H:00}",
                "cuplikan": int(r.cuplikan or 0),
                "cpu_avg_percent": round(float(r.cpu_avg or 0.0), 1),
                "cpu_max_percent": round(float(r.cpu_max or 0.0), 1),
                "cpu_cores_avg": round(float(r.cpu_avg or 0.0) / 100.0, 2),
                "ram_max_mb": round(float(r.ram_max or 0.0), 1),
                "vram_max_mb": round(float(r.vram_max or 0.0), 1),
                "proses_max": int(r.proses_max or 0),
                "aktivitas": r.aktivitas or "",
                "menit_aktif": round(float(r.cuplikan_aktif or 0) * menit, 1),
            }
        )
    return hasil


async def hourly_detail_computehub(
    session: AsyncSession, *, user_id: int, days: int = 7, limit: int = 720
) -> list[dict]:
    """Rincian PER JAM job ComputeHub satu user (dikelompokkan pada jam SELESAI)."""
    from app.models.job import Job, JobDevice, JobStatus

    sejak = _sejak(days)
    jam = func.date_trunc("hour", _lokal(Job.finished_at))
    q = (
        select(
            jam.label("jam"),
            func.count().label("jobs"),
            func.sum(func.cast(Job.status == JobStatus.succeeded, Integer)).label(
                "sukses"
            ),
            func.sum(func.cast(Job.status == JobStatus.failed, Integer)).label("gagal"),
            func.sum(
                func.cast(Job.device == JobDevice.gpu, Integer)
                * func.coalesce(Job.actual_runtime_seconds, 0.0)
            ).label("gpu_detik"),
            func.sum(func.coalesce(Job.actual_runtime_seconds, 0.0)).label("total_detik"),
            func.max(func.coalesce(Job.peak_vram_mb, 0.0)).label("vram_max"),
        )
        .where(
            Job.finished_at.is_not(None),
            Job.finished_at >= sejak,
            Job.user_id == user_id,
        )
        .group_by(jam)
        .order_by(jam.desc())
        .limit(max(1, limit))
    )
    hasil: list[dict] = []
    for r in (await session.execute(q)).all():
        t: dt.datetime = r.jam
        hasil.append(
            {
                "tanggal": f"{t:%Y-%m-%d}",
                "jam": f"{t:%H:00}",
                "rentang": f"{t:%H:00}–{t + dt.timedelta(hours=1):%H:00}",
                "jobs": int(r.jobs or 0),
                "sukses": int(r.sukses or 0),
                "gagal": int(r.gagal or 0),
                "gpu_detik": round(float(r.gpu_detik or 0.0), 1),
                "total_detik": round(float(r.total_detik or 0.0), 1),
                "vram_max_mb": round(float(r.vram_max or 0.0), 1),
            }
        )
    return hasil


async def daily_summary(
    session: AsyncSession,
    *,
    days: int = 30,
    username: str | None = None,
    include_system: bool = True,
) -> list[dict]:
    """Rekap harian per user OS dari cuplikan tersimpan (terbaru dulu).

    `menit_aktif` = jumlah cuplikan yang menunjukkan aktivitas nyata dikali
    interval cuplik -> perkiraan lama user memakai server pada hari itu.
    """
    sejak = _sejak(days)
    hari = func.date(_lokal(OsUserSample.ts))
    aktif = _cuplikan_aktif()
    q = (
        select(
            hari.label("tanggal"),
            OsUserSample.username,
            func.bool_or(OsUserSample.is_system).label("is_system"),
            func.count().label("cuplikan"),
            func.avg(OsUserSample.cpu_percent).label("cpu_avg"),
            func.max(OsUserSample.cpu_percent).label("cpu_max"),
            func.avg(OsUserSample.memory_mb).label("ram_avg"),
            func.max(OsUserSample.memory_mb).label("ram_max"),
            func.max(OsUserSample.vram_mb).label("vram_max"),
            func.max(OsUserSample.processes).label("proses_max"),
            func.max(func.cast(OsUserSample.activity, String)).label("aktivitas"),
            aktif.label("cuplikan_aktif"),
        )
        .where(OsUserSample.ts >= sejak)
        .group_by(hari, OsUserSample.username)
        .order_by(hari.desc(), func.max(OsUserSample.vram_mb).desc())
    )
    if username:
        q = q.where(OsUserSample.username == username)
    if not include_system:
        q = q.where(OsUserSample.is_system.is_(False))

    menit_per_cuplikan = _menit_per_cuplikan()
    hasil: list[dict] = []
    for r in (await session.execute(q)).all():
        hasil.append(
            {
                "tanggal": str(r.tanggal),
                "username": r.username,
                "is_system": bool(r.is_system),
                "cuplikan": int(r.cuplikan or 0),
                "cpu_avg_percent": round(float(r.cpu_avg or 0.0), 1),
                "cpu_max_percent": round(float(r.cpu_max or 0.0), 1),
                "cpu_cores_avg": round(float(r.cpu_avg or 0.0) / 100.0, 2),
                "ram_avg_mb": round(float(r.ram_avg or 0.0), 1),
                "ram_max_mb": round(float(r.ram_max or 0.0), 1),
                "vram_max_mb": round(float(r.vram_max or 0.0), 1),
                "proses_max": int(r.proses_max or 0),
                "aktivitas": r.aktivitas or "",
                "menit_aktif": round(float(r.cuplikan_aktif or 0) * menit_per_cuplikan, 1),
            }
        )
    return hasil


async def daily_summary_computehub(
    session: AsyncSession, *, days: int = 30, user_id: int | None = None
) -> list[dict]:
    """Rekap harian job ComputeHub per user (pelengkap sisi platform)."""
    from app.models.job import Job, JobDevice, JobStatus
    from app.models.user import User

    sejak = _sejak(days)
    hari = func.date(_lokal(Job.finished_at))
    q = (
        select(
            hari.label("tanggal"),
            Job.user_id,
            func.max(User.name).label("nama"),
            func.max(User.email).label("email"),
            func.count().label("jobs"),
            func.sum(
                func.cast(Job.status == JobStatus.succeeded, Integer)
            ).label("sukses"),
            func.sum(func.cast(Job.status == JobStatus.failed, Integer)).label("gagal"),
            func.sum(
                func.cast(Job.device == JobDevice.gpu, Integer)
                * func.coalesce(Job.actual_runtime_seconds, 0.0)
            ).label("gpu_detik"),
            func.sum(func.coalesce(Job.actual_runtime_seconds, 0.0)).label("total_detik"),
            func.max(func.coalesce(Job.peak_vram_mb, 0.0)).label("vram_max"),
            func.max(func.coalesce(Job.peak_ram_mb, 0.0)).label("ram_max"),
        )
        .select_from(Job)
        .join(User, Job.user_id == User.id)
        .where(Job.finished_at.is_not(None), Job.finished_at >= sejak)
        .group_by(hari, Job.user_id)
        .order_by(hari.desc(), func.count().desc())
    )
    if user_id:
        q = q.where(Job.user_id == user_id)
    return [
        {
            "tanggal": str(r.tanggal),
            "user_id": r.user_id,
            "nama": r.nama or "",
            "email": r.email or "",
            "jobs": int(r.jobs or 0),
            "sukses": int(r.sukses or 0),
            "gagal": int(r.gagal or 0),
            "gpu_detik": round(float(r.gpu_detik or 0.0), 1),
            "total_detik": round(float(r.total_detik or 0.0), 1),
            "vram_max_mb": round(float(r.vram_max or 0.0), 1),
            "ram_max_mb": round(float(r.ram_max or 0.0), 1),
        }
        for r in (await session.execute(q)).all()
    ]


# Diimpor di modul ini agar tipe Float ikut terpakai saat mapping kolom baru.
_ = Float
