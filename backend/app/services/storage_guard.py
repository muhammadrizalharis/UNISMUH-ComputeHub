"""Guard kuota disk /persist per-user — pantau, peringatkan (email), & tegakkan.

Kenapa: disk server bersama bisa penuh oleh workspace persisten (/persist) mahasiswa.
Kuota unggah (max_storage_mb) sudah ditegakkan saat UPLOAD, tetapi job/kernel bisa MENULIS
file besar SAAT EKSEKUSI (di luar jalur upload). Guard ini menutup celah itu.

Alur — dua jalur pemindaian, hasil diterapkan PER USER begitu selesai:
  * Jalur penuh (tiap STORAGE_GUARD_INTERVAL_SECONDS): `du -sb` tiap folder user, paralel
    terbatas. Satu folder yang gagal/timeout TIDAK mengosongkan snapshot user lain.
  * Jalur cepat (tiap beberapa detik): user yang baru mengubah berkas lewat web
    (mark_dirty) atau sedang punya job/sesi/devbox berjalan dipindai ulang segera.
    Hapus permanen lewat web langsung mengurangi angka (adjust_usage) sebelum `du` selesai.
  1. Hitung pemakaian /persist tiap user (TANPA sudo — folder dimiliki user host sejak
     hardening T3).
  2. Bandingkan dgn kuota efektif (user_policy.effective -> max_storage_mb; 0 = tanpa batas
     -> user itu TIDAK dipantau).
  3. >= STORAGE_ALERT_PERCENT% kuota  -> peringatan email lewat pipeline Alerts (cooldown).
  4. >= 100% kuota (over)            -> (a) tandai user "over" agar job/sesi BARU ditolak
     (admission gate di scheduler & interactive), (b) bila STORAGE_ENFORCE_ENABLED: hentikan
     job & sesi yang sedang berjalan milik user itu supaya berhenti menulis (bebaskan resource).

AMAN & berlingkup: hanya menyentuh folder data KITA (~/.computehub/users/<id>) dan job/sesi
MILIK user bersangkutan. Super admin dikecualikan. Inert secara default: tanpa kuota
(max_storage_mb = 0 di semua peran/override) guard tak melakukan aksi apa pun.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import shutil
import time
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.notification import Notification
from app.models.user import User
from app.services import user_policy as user_policy_svc

logger = get_logger(__name__)

# Cache (in-memory) hasil scan terakhir — dibaca oleh admission gate (sinkron, murah).
_usage: dict[int, dict] = {}   # user_id -> {"used_mb", "quota_mb", "ratio"}
_over: set[int] = set()        # user_id yang pemakaiannya >= 100% kuota
_stage_notified: dict[int, int] = {}  # user_id -> tahap (% kuota) terakhir yang diberi notifikasi lonceng

# Pemindaian per user. Data di VM penyimpanan (NFS): folder ratusan ribu berkas bisa
# butuh 1-3 menit, sedangkan folder kecil < 3 detik.
_FULL_CONCURRENCY = 3
_FAST_CONCURRENCY = 3
_USER_SCAN_TIMEOUT = 900.0
_FAST_INTERVAL = 5.0       # jalur cepat bangun minimal tiap 5 dtk
_ACTIVE_MIN_GAP = 15.0     # jeda minimum antar-pindai user aktif
_scan_meta: dict[int, dict] = {}   # user_id -> {"scanned_at": epoch, "duration": dtk}
_scanning: set[int] = set()        # user yang sedang di-du (hindari dobel)
_dirty: dict[int, float] = {}      # user_id -> waktu ditandai berubah
_full: dict = {"running": False, "started_at": None, "finished_at": None}
_wake: asyncio.Event | None = None
_sems: dict[str, asyncio.Semaphore] = {}
_fast_tasks: dict[int, asyncio.Task] = {}


def blocks_new_work() -> bool:
    """True bila kuota penyimpanan 100% harus MENOLAK pekerjaan/unggahan baru.

    Mode penuh-keras (SOFT_LIMIT_ENABLED=false) ATAU mode keras khusus penyimpanan
    (STORAGE_HARD_LIMIT=true, RAM/VRAM tetap lunak).
    """
    return (not settings.SOFT_LIMIT_ENABLED) or bool(settings.STORAGE_HARD_LIMIT)


def is_over_quota(user_id: int) -> bool:
    """True bila user melampaui kuota /persist (dipakai untuk menolak job/sesi baru)."""
    return int(user_id) in _over


def clear_over(user_id: int, quota_mb: float | None = None) -> None:
    """Lepaskan status 'over' seketika (mis. setelah admin menaikkan kuota) tanpa
    menunggu tick berikutnya; snapshot kuota ikut diperbarui bila diberikan."""
    _over.discard(int(user_id))
    _stage_notified.pop(int(user_id), None)
    snap = _usage.get(int(user_id))
    if snap is not None and quota_mb is not None:
        snap["quota_mb"] = round(float(quota_mb), 1)
        snap["ratio"] = round(snap["used_mb"] / quota_mb, 3) if quota_mb > 0 else 0.0


def user_status(user_id: int) -> dict | None:
    """Snapshot pemakaian satu user (None = belum dipindai / folder belum ada)."""
    snap = _usage.get(int(user_id))
    return dict(snap) if snap is not None else None


def notify_stages() -> list[int]:
    out: list[int] = []
    for part in str(settings.STORAGE_NOTIFY_STAGES or "").split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 100:
            out.append(int(part))
    return sorted(set(out))


def usage_snapshot() -> dict[int, dict]:
    """Salinan snapshot pemakaian terakhir per user (untuk diagnostik/tampilan)."""
    return {k: dict(v) for k, v in _usage.items()}


def scan_status() -> dict:
    """Status pemindai untuk tampilan: siklus penuh & user yang sedang dipindai."""
    return {
        "full_running": bool(_full["running"]),
        "full_started_at": _full["started_at"],
        "full_finished_at": _full["finished_at"],
        "folders": _full.get("folders"),
        "scanning": sorted(_scanning),
        "pending": sorted(_dirty),
    }


def is_scanning(user_id: int) -> bool:
    return int(user_id) in _scanning or int(user_id) in _dirty


def mark_dirty(user_id: int) -> None:
    """Tandai folder user berubah -> dipindai ulang SEGERA oleh jalur cepat."""
    _dirty[int(user_id)] = time.time()
    if _wake is not None:
        _wake.set()


def adjust_usage(user_id: int, delta_bytes: int) -> None:
    """Terapkan perubahan yang ukurannya SUDAH diketahui (mis. hapus permanen lewat web)
    ke snapshot seketika, lalu jadwalkan `du` untuk memastikan angka pastinya."""
    uid = int(user_id)
    snap = _usage.get(uid)
    if snap is not None and delta_bytes:
        nbytes = max(0, int(snap.get("bytes", snap["used_mb"] * _MB)) + int(delta_bytes))
        quota_mb = float(snap.get("quota_mb") or 0.0)
        used_mb = nbytes / _MB
        snap["bytes"] = nbytes
        snap["used_mb"] = round(used_mb, 1)
        snap["ratio"] = round(used_mb / quota_mb, 3) if quota_mb > 0 else 0.0
        if snap["ratio"] < 1.0:
            _over.discard(uid)
    mark_dirty(uid)


def _sem(name: str, size: int) -> asyncio.Semaphore:
    key = f"{name}:{id(asyncio.get_running_loop())}"
    sem = _sems.get(key)
    if sem is None:
        sem = _sems[key] = asyncio.Semaphore(size)
    return sem


_MB = 1024 * 1024


async def _du_bytes(path, timeout: float = _USER_SCAN_TIMEOUT) -> int | None:
    """`du -sb <path>` -> bytes; None bila gagal/timeout (nilai lama dipertahankan)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nice", "-n", "15", "du", "-sb", str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None
    # du keluar rc=1 bila ada berkas lenyap saat dipindai; totalnya tetap valid.
    first = (out or b"").split(b"\t", 1)[0].strip()
    return int(first) if first.isdigit() else None


async def user_disk_used_bytes(user_id: int) -> int:
    """Ukuran folder /persist milik user (bytes) via `du -sb`. 0 bila belum ada.

    Folder dimiliki user host (hardening T3) -> tanpa sudo.
    """
    p = settings.docker_user_data_root / str(int(user_id))
    if not p.exists():
        return 0
    return await _du_bytes(p, timeout=120) or 0


async def upload_limit_bytes(user_id: int, quota_mb: float) -> int:
    """Batas unggah (bytes) = SISA kuota disk user (kuota - terpakai).

    Bila user TANPA kuota (max_storage_mb <= 0) -> dibatasi disk fisik dikurangi
    cadangan (UPLOAD_DISK_HEADROOM_MB) agar disk server bersama tak terisi penuh.
    Selalu >= 0.
    """
    # Mode LUNAK penuh: abaikan kuota PER-USER utk unggahan, TAPI tetap jaga disk FISIK
    # (headroom). Mode keras penyimpanan (STORAGE_HARD_LIMIT) menegakkan kuota lagi.
    if settings.SOFT_LIMIT_ENABLED and not settings.STORAGE_HARD_LIMIT:
        quota_mb = 0.0
    if quota_mb and quota_mb > 0:
        used = await user_disk_used_bytes(user_id)
        return max(0, int(quota_mb * _MB) - used)
    try:
        free = shutil.disk_usage(str(settings.docker_user_data_root)).free
    except Exception:  # noqa: BLE001
        free = shutil.disk_usage("/").free
    return max(0, int(free) - int(settings.UPLOAD_DISK_HEADROOM_MB * _MB))


def _list_user_ids() -> list[int] | None:
    """ID user yang punya folder /persist; None bila root data belum ada."""
    root = settings.docker_user_data_root
    if not root.is_dir():
        return None
    try:
        return sorted(int(p.name) for p in root.iterdir() if p.name.isdigit() and p.is_dir())
    except OSError:
        return None


async def _scan_ids(
    uids: Iterable[int],
    lane: str,
    on_result: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict[int, int]:
    """`du` tiap folder user secara paralel terbatas. User yang gagal/timeout tidak
    dimasukkan (snapshot lamanya dipertahankan). on_result dipanggil per user begitu
    selesai, sehingga tampilan terisi bertahap tanpa menunggu folder terbesar."""
    root = settings.docker_user_data_root
    sem = _sem(lane, _FULL_CONCURRENCY if lane == "full" else _FAST_CONCURRENCY)
    result: dict[int, int] = {}

    async def one(uid: int) -> None:
        if uid in _scanning:
            return
        async with sem:
            if uid in _scanning:
                return
            _scanning.add(uid)
            t0 = time.time()
            try:
                p = root / str(uid)
                nbytes = await _du_bytes(p) if p.exists() else 0
            finally:
                _scanning.discard(uid)
            if nbytes is None:
                logger.warning("Pindai /persist user %d gagal/timeout; nilai lama dipakai.", uid)
                return
            _scan_meta[uid] = {"scanned_at": time.time(), "duration": time.time() - t0}
            if _dirty.get(uid, float("inf")) <= t0:
                _dirty.pop(uid, None)
            result[uid] = nbytes
            if on_result is not None:
                try:
                    await on_result(uid, nbytes)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Terapkan hasil pindai user %d gagal: %s", uid, exc)

    await asyncio.gather(*(one(int(u)) for u in uids))
    return result


async def _scan_disk(
    on_result: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict[int, int]:
    """Pindai SEMUA folder user -> {user_id: bytes} (hanya yang berhasil)."""
    uids = _list_user_ids()
    if not uids:
        return {}
    return await _scan_ids(uids, "full", on_result)


async def _enforce_user(user_id: int) -> None:
    """Hentikan job & sesi berjalan milik user (agar berhenti menulis). Best-effort.

    Import di dalam fungsi (lazy) untuk menghindari import melingkar
    (scheduler & interactive tidak boleh mengimpor modul ini di tingkat atas).
    """
    from app.models.job import Job, JobStatus
    from app.services.interactive import kernel_manager
    from app.services.scheduler import scheduler

    reason = (
        "Dihentikan otomatis: kuota penyimpanan (/persist) Anda penuh. "
        "Hapus file di menu Penyimpanan lalu jalankan lagi."
    )
    async with AsyncSessionLocal() as db:
        job_ids = (
            await db.execute(
                select(Job.id).where(
                    Job.user_id == user_id, Job.status == JobStatus.running
                )
            )
        ).scalars().all()
    for jid in job_ids:
        try:
            await scheduler.cancel_job(jid, reason=reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal hentikan job #%d (kuota disk): %s", jid, exc)
    try:
        dropped = await kernel_manager.drop_user_sessions(user_id)
        if dropped:
            logger.info("Kuota disk: %d sesi user %d dihentikan.", dropped, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal hentikan sesi user %d (kuota disk): %s", user_id, exc)


async def _notify_stage(db, uid: int, stage: int, used_mb: float, quota_mb: float) -> None:
    """Notifikasi lonceng sekali per tahap (80/90/100%). Tahan restart: bila notifikasi
    tahap yang sama sudah ada <3 hari, tidak dikirim ulang."""
    tipe = "storage_full" if stage >= 100 else "storage_warning"
    terbaru = await db.scalar(
        select(Notification)
        .where(Notification.user_id == uid, Notification.type.in_(["storage_warning", "storage_full"]))
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    if terbaru is not None and terbaru.body.startswith(f"[{stage}%]"):
        umur = dt.datetime.now(dt.timezone.utc) - (
            terbaru.created_at if terbaru.created_at.tzinfo else terbaru.created_at.replace(tzinfo=dt.timezone.utc)
        )
        if umur < dt.timedelta(days=3):
            return
    sisa_mb = max(0.0, quota_mb - used_mb)
    if stage >= 100:
        judul = "Penyimpanan penuh — unggahan & job baru ditolak" if blocks_new_work() else "Penyimpanan penuh"
        isi = (
            f"[{stage}%] Terpakai {used_mb / 1024:.1f} GB dari kuota {quota_mb / 1024:.1f} GB. "
            "Hapus berkas yang tidak terpakai di menu Penyimpanan, atau ajukan tambahan kuota ke admin."
        )
    else:
        judul = f"Penyimpanan {stage}% terpakai"
        isi = (
            f"[{stage}%] Sisa {sisa_mb / 1024:.1f} GB dari kuota {quota_mb / 1024:.1f} GB. "
            "Rapikan berkas atau ajukan tambahan kuota sebelum penuh."
        )
    db.add(Notification(user_id=uid, type=tipe, title=judul, body=isi, link="/storage"))
    await db.commit()


async def _apply(usage_bytes: dict[int, int]) -> None:
    """Terapkan hasil pindai SEBAGIAN user ke snapshot + kuota/alert/penegakan.
    User lain di snapshot tidak disentuh."""
    if not usage_bytes:
        return
    alert_ratio = max(1.0, float(settings.STORAGE_ALERT_PERCENT)) / 100.0
    stages = notify_stages()
    new_over: set[int] = set()
    breaches: list[dict] = []  # nilai POLOS (bukan ORM) untuk di-email setelah scan

    async with AsyncSessionLocal() as db:
        for uid, nbytes in usage_bytes.items():
            eff = await user_policy_svc.effective(db, uid)
            quota_mb = float(getattr(eff, "max_storage_mb", 0.0) or 0.0)
            used_mb = nbytes / 1024 / 1024
            ratio = (used_mb / quota_mb) if quota_mb > 0 else 0.0
            meta = _scan_meta.get(uid) or {}
            _usage[uid] = {
                "used_mb": round(used_mb, 1),
                "quota_mb": round(quota_mb, 1),
                "ratio": round(ratio, 3),
                "bytes": int(nbytes),
                "scanned_at": meta.get("scanned_at") or time.time(),
            }
            _over.discard(uid)
            if quota_mb <= 0:
                _stage_notified.pop(uid, None)
                continue  # tanpa batas -> tak dipantau
            user = await db.get(User, uid)
            if user is None or user.is_superadmin:
                continue  # super admin bebas
            # Notifikasi lonceng bertahap; turun di bawah tahap = boleh diberi tahu lagi nanti.
            pct = ratio * 100.0
            tahap = max((s for s in stages if pct >= s), default=0)
            if tahap and tahap > _stage_notified.get(uid, 0):
                try:
                    await _notify_stage(db, uid, tahap, used_mb, quota_mb)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Notifikasi kuota disk user %d gagal: %s", uid, exc)
            _stage_notified[uid] = tahap
            over = ratio >= 1.0
            if over:
                new_over.add(uid)
                _over.add(uid)
            if not over and ratio < alert_ratio:
                continue
            breaches.append({
                "email": user.email,
                "name": user.name,
                "used_mb": used_mb,
                "quota_mb": quota_mb,
                "pct": ratio * 100.0,
                "over": over,
            })

        # Email peringatan lewat pipeline Alerts (hormati enabled/cooldown/SMTP).
        if breaches:
            from app.services import alerts as alerts_svc

            for b in breaches:
                level = "PENUH" if b["over"] else "hampir penuh"
                extra = ""
                if b["over"] and settings.STORAGE_ENFORCE_ENABLED and not settings.SOFT_LIMIT_ENABLED:
                    extra = " Job/sesi yang berjalan dihentikan."
                elif b["over"] and blocks_new_work():
                    extra = " Unggahan dan job/sesi baru ditolak sampai ada ruang atau kuota ditambah."
                msg = (
                    f"Penyimpanan /persist {b['name']} ({b['email']}) {level}: "
                    f"{b['used_mb']:.0f} MB dari kuota {b['quota_mb']:.0f} MB "
                    f"({b['pct']:.0f}%).{extra}"
                )
                try:
                    await alerts_svc.notify(
                        db,
                        scope="persist_user",
                        subject=b["email"],
                        metric="storage",
                        value=round(b["used_mb"], 1),
                        threshold=round(b["quota_mb"], 1),
                        message=msg,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Alert kuota disk gagal (%s): %s", b["email"], exc)

    # Mode LUNAK: JANGAN hentikan job/sesi berjalan saat 100% (user minta tak dihentikan;
    # storage = kapasitas, tak bisa di-throttle -> cukup alert. Job lanjut; tulis gagal
    # sendiri bila disk fisik benar-benar habis).
    if new_over and settings.STORAGE_ENFORCE_ENABLED and not settings.SOFT_LIMIT_ENABLED:
        for uid in new_over:
            await _enforce_user(uid)


async def _tick() -> None:
    """Satu siklus penuh: pindai semua folder user, terapkan bertahap."""
    _full["running"] = True
    _full["started_at"] = time.time()
    try:
        applied: set[int] = set()

        async def on_result(uid: int, nbytes: int) -> None:
            await _apply({uid: nbytes})
            applied.add(uid)

        usage_bytes = await _scan_disk(on_result=on_result)
        rest = {u: n for u, n in usage_bytes.items() if u not in applied}
        await _apply(rest)

        present = _list_user_ids()
        if present is None and not usage_bytes:
            # Root data tidak ada sama sekali -> tak ada yang bisa dipantau.
            _over.clear()
            _usage.clear()
        else:
            _full["folders"] = len(present or usage_bytes)
            keep = set(present or []) | set(usage_bytes)
            for uid in [u for u in _usage if u not in keep]:
                _usage.pop(uid, None)
                _over.discard(uid)
    finally:
        _full["running"] = False
        _full["finished_at"] = time.time()


async def _active_user_ids() -> set[int]:
    """User yang punya job/sesi/devbox berjalan (bisa menulis ke /persist kapan saja)."""
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(Job.user_id).where(Job.status == JobStatus.running).distinct())
        return {int(u) for u in rows.scalars().all() if u is not None}


async def _fast_pass() -> None:
    """Pindai ulang user yang ditandai berubah atau sedang aktif."""
    try:
        active = await _active_user_ids()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Ambil user aktif gagal: %s", exc)
        active = set()
    now = time.time()
    for uid in set(_dirty) | active:
        task = _fast_tasks.get(uid)
        if uid in _scanning or (task is not None and not task.done()):
            continue
        meta = _scan_meta.get(uid)
        if uid in _dirty or meta is None or (
            now - meta["scanned_at"] >= max(_ACTIVE_MIN_GAP, meta["duration"])
        ):
            # Task terpisah per user: folder besar tidak menahan user lain.
            _fast_tasks[uid] = asyncio.create_task(
                _scan_ids([uid], "fast", lambda u, n: _apply({u: n}))
            )
    for uid in [u for u, t in _fast_tasks.items() if t.done()]:
        _fast_tasks.pop(uid, None)


class StorageGuard:
    """Loop latar belakang yang memantau & menegakkan kuota disk /persist per-user."""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        global _wake
        if self._tasks:
            return
        self._stop.clear()
        _wake = asyncio.Event()
        self._tasks = [
            asyncio.create_task(self._loop(), name="storage-guard"),
            asyncio.create_task(self._fast_loop(), name="storage-guard-fast"),
        ]
        logger.info(
            "StorageGuard jalan (siklus penuh %ss, jalur cepat %ss, enforce=%s, alert>=%.0f%%).",
            int(settings.STORAGE_GUARD_INTERVAL_SECONDS),
            int(_FAST_INTERVAL),
            settings.STORAGE_ENFORCE_ENABLED,
            settings.STORAGE_ALERT_PERCENT,
        )

    async def stop(self) -> None:
        self._stop.set()
        if _wake is not None:
            _wake.set()
        for task in self._tasks:
            task.cancel()
        for task in _fast_tasks.values():
            task.cancel()
        _fast_tasks.clear()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []

    async def _loop(self) -> None:
        interval = max(30, int(settings.STORAGE_GUARD_INTERVAL_SECONDS))
        while not self._stop.is_set():
            try:
                await _tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("StorageGuard tick gagal: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _fast_loop(self) -> None:
        while not self._stop.is_set():
            if _wake is not None:
                _wake.clear()
            try:
                await _fast_pass()
            except Exception as exc:  # noqa: BLE001
                logger.warning("StorageGuard jalur cepat gagal: %s", exc)
            if _wake is None:
                await asyncio.sleep(_FAST_INTERVAL)
                continue
            try:
                await asyncio.wait_for(_wake.wait(), timeout=_FAST_INTERVAL)
            except asyncio.TimeoutError:
                pass


# Instance global (dipakai lifespan & admission gate).
storage_guard = StorageGuard()
