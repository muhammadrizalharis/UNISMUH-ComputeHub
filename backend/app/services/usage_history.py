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
from app.models.llm_conn import LlmConnSample
from app.models.usage_history import OsUserSample
from app.services import llm_attrib
from app.services import report as report_svc

logger = get_logger(__name__)


class UsageHistoryRecorder:
    """Tugas latar: cuplik pemakaian per user OS lalu simpan ke DB."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._task_llm: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # {uid: {"nama", "koneksi_max", "detik_aktif"}} sejak penulisan terakhir.
        self._akt_llm: dict[int, dict] = {}

    @property
    def interval(self) -> float:
        return max(60.0, float(settings.USAGE_HISTORY_INTERVAL_SECONDS))

    @property
    def interval_llm(self) -> float:
        return max(5.0, float(settings.LLM_SUBSAMPLE_SECONDS))

    async def start(self) -> None:
        if self._task is not None or settings.USAGE_HISTORY_INTERVAL_SECONDS <= 0:
            if settings.USAGE_HISTORY_INTERVAL_SECONDS <= 0:
                logger.info("UsageHistoryRecorder nonaktif (interval 0).")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="usage-history")
        self._task_llm = asyncio.create_task(self._loop_llm(), name="llm-subsample")
        logger.info(
            "UsageHistoryRecorder jalan (tiap %.0f dtk; cuplik LLM tiap %.0f dtk).",
            self.interval,
            self.interval_llm,
        )

    async def stop(self) -> None:
        self._stop.set()
        for nama in ("_task", "_task_llm"):
            t: asyncio.Task | None = getattr(self, nama)
            if t is not None:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                setattr(self, nama, None)

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

    async def _loop_llm(self) -> None:
        """Cuplik socket LLM secara rapat -> ukur LAMA pemakaian tiap pihak.

        Satu permintaan LLM sering hanya beberapa detik; cuplikan 5 menit akan
        melewatkannya. Loop ini murah (baca satu berkas /proc) dan hanya menumpuk
        angka di memori -- penulisan ke DB tetap sekali per periode utama.
        """
        det = self.interval_llm
        while not self._stop.is_set():
            try:
                peta = await asyncio.to_thread(llm_attrib.aktivitas)
                for uid, v in peta.items():
                    e = self._akt_llm.setdefault(
                        uid, {"koneksi_max": 0, "detik_aktif": 0.0}
                    )
                    e["koneksi_max"] = max(e["koneksi_max"], int(v["koneksi"]))
                    if int(v["aktif"]) > 0:
                        e["detik_aktif"] += det
            except Exception as exc:  # noqa: BLE001
                logger.debug("Cuplik LLM gagal: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=det)
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
        await self._rekam_llm(now, rows)
        return len(rows)

    async def _rekam_llm(self, now: dt.datetime, os_rows: list[dict]) -> None:
        """Cuplik koneksi ke layanan LLM + beban layanannya. Best-effort."""
        try:
            peta = await asyncio.to_thread(llm_attrib.peta_koneksi)
            klien = peta.get("klien", [])
            masuk = peta.get("server", [])
            # Ambil & kosongkan akumulator: angkanya milik periode yang baru lewat.
            akt, self._akt_llm = self._akt_llm, {}
            if not klien and not masuk and not akt:
                return

            # Beban layanan diambil dari akun OS yang menjalankannya (mis. `ollama`).
            akun = peta.get("layanan_user") or ""
            beban = next((u for u in os_rows if u.get("username") == akun), {})
            vram = float(beban.get("vram_mb") or 0.0)
            cpu = float(beban.get("cpu_percent") or 0.0)
            ram = float(beban.get("memory_mb") or 0.0)

            # Dasar pembagian: LAMA pemakaian nyata. Koneksi menganggur tidak
            # membebani GPU, jadi menghitung koneksi saja menyesatkan. Jatuh ke
            # porsi koneksi hanya bila tak ada aktivitas terukur sama sekali.
            total_aktif = sum(float(v["detik_aktif"]) for v in akt.values())
            total_kon = sum(int(k["koneksi"]) for k in klien) + sum(
                int(s["koneksi"]) for s in masuk
            )

            def _pangsa(uid: int, kon: int) -> float:
                if total_aktif > 0:
                    return float(akt.get(uid, {}).get("detik_aktif", 0.0)) / total_aktif
                return (kon / total_kon) if total_kon else 0.0

            def _baris(
                nama: str, uid: int, sumber: str, kon: int, detik: float
            ) -> LlmConnSample:
                return LlmConnSample(
                    ts=now,
                    nama=str(nama)[:64],
                    uid=uid,
                    sumber=sumber,
                    koneksi=kon,
                    layanan_vram_mb=vram,
                    layanan_cpu_percent=cpu,
                    layanan_ram_mb=ram,
                    pangsa=_pangsa(uid, kon),
                    detik_aktif=detik,
                )

            baris = [
                _baris(
                    k["user"],
                    int(k["uid"]),
                    "klien",
                    max(int(k["koneksi"]), int(akt.get(int(k["uid"]), {}).get("koneksi_max", 0))),
                    float(akt.get(int(k["uid"]), {}).get("detik_aktif", 0.0)),
                )
                for k in klien
            ] + [
                _baris(s["asal"], -1, "masuk", int(s["koneksi"]), 0.0) for s in masuk
            ]
            async with AsyncSessionLocal() as session:
                session.add_all(baris)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rekam koneksi LLM gagal: %s", exc)


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
            func.max(func.coalesce(Job.peak_cpu_percent, 0.0)).label("cpu_max"),
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
            "cpu_max_percent": round(float(r.cpu_max or 0.0), 1),
        }
        for r in (await session.execute(q)).all()
    ]


async def daily_summary_llm(
    session: AsyncSession, *, days: int = 30, nama: str | None = None
) -> list[dict]:
    """Rekap HARIAN koneksi ke layanan LLM per pihak (terbaru dulu).

    `menit_aktif` = jumlah cuplikan yang menunjukkan ada koneksi dikali interval
    cuplik -> perkiraan lama pihak itu memakai layanan pada hari tersebut.

    Kolom `layanan_*` = beban NYATA layanan saat cuplikan (hasil ukur).
    Kolom `est_*` = PERKIRAAN bagian pihak ini, dihitung dari porsi koneksinya.
    Perkiraan karena Ollama satu proses: VRAM/CPU/RAM-nya tak bisa dipecah
    per klien oleh sistem operasi.
    """
    sejak = _sejak(days)
    hari = func.date(_lokal(LlmConnSample.ts))
    aktif = func.sum(func.cast(LlmConnSample.koneksi > 0, Integer))
    bagian_vram = LlmConnSample.layanan_vram_mb * LlmConnSample.pangsa
    bagian_cpu = LlmConnSample.layanan_cpu_percent * LlmConnSample.pangsa
    bagian_ram = LlmConnSample.layanan_ram_mb * LlmConnSample.pangsa
    q = (
        select(
            hari.label("tanggal"),
            LlmConnSample.nama,
            func.max(func.cast(LlmConnSample.sumber, String)).label("sumber"),
            func.max(LlmConnSample.uid).label("uid"),
            func.count().label("cuplikan"),
            func.avg(LlmConnSample.koneksi).label("kon_avg"),
            func.max(LlmConnSample.koneksi).label("kon_max"),
            func.avg(LlmConnSample.pangsa).label("pangsa_avg"),
            func.sum(LlmConnSample.detik_aktif).label("detik_aktif"),
            func.max(LlmConnSample.layanan_vram_mb).label("layanan_vram_max"),
            func.avg(LlmConnSample.layanan_cpu_percent).label("layanan_cpu_avg"),
            func.max(LlmConnSample.layanan_ram_mb).label("layanan_ram_max"),
            func.max(bagian_vram).label("est_vram_max"),
            func.avg(bagian_cpu).label("est_cpu_avg"),
            func.max(bagian_ram).label("est_ram_max"),
            aktif.label("cuplikan_aktif"),
        )
        .where(LlmConnSample.ts >= sejak)
        .group_by(hari, LlmConnSample.nama)
        .order_by(hari.desc(), func.max(bagian_vram).desc())
    )
    if nama:
        q = q.where(LlmConnSample.nama == nama)

    menit = _menit_per_cuplikan()
    return [
        {
            "tanggal": str(r.tanggal),
            "nama": r.nama,
            "sumber": r.sumber or "klien",
            "uid": int(r.uid if r.uid is not None else -1),
            "cuplikan": int(r.cuplikan or 0),
            "koneksi_avg": round(float(r.kon_avg or 0.0), 1),
            "koneksi_max": int(r.kon_max or 0),
            "pangsa_avg": round(float(r.pangsa_avg or 0.0), 3),
            "detik_aktif": round(float(r.detik_aktif or 0.0), 1),
            "layanan_vram_max_mb": round(float(r.layanan_vram_max or 0.0), 1),
            "layanan_cpu_avg_percent": round(float(r.layanan_cpu_avg or 0.0), 1),
            "layanan_ram_max_mb": round(float(r.layanan_ram_max or 0.0), 1),
            "est_vram_max_mb": round(float(r.est_vram_max or 0.0), 1),
            "est_cpu_avg_percent": round(float(r.est_cpu_avg or 0.0), 1),
            "est_ram_max_mb": round(float(r.est_ram_max or 0.0), 1),
            "menit_aktif": round(float(r.cuplikan_aktif or 0) * menit, 1),
        }
        for r in (await session.execute(q)).all()
    ]


async def daftar_pihak_llm(session: AsyncSession, *, days: int = 30) -> list[dict]:
    """Daftar pihak yang punya cuplikan LLM pada rentang ini -> isi menu pilih."""
    sejak = _sejak(days)
    q = (
        select(
            LlmConnSample.nama,
            func.max(func.cast(LlmConnSample.sumber, String)).label("sumber"),
        )
        .where(LlmConnSample.ts >= sejak)
        .group_by(LlmConnSample.nama)
        .order_by(LlmConnSample.nama)
    )
    return [
        {"nama": r.nama, "sumber": r.sumber or "klien"}
        for r in (await session.execute(q)).all()
    ]


# Diimpor di modul ini agar tipe Float ikut terpakai saat mapping kolom baru.
_ = Float
