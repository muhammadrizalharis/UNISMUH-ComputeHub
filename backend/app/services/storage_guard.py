"""Guard kuota disk /persist per-user — pantau, peringatkan (email), & tegakkan.

Kenapa: disk server bersama bisa penuh oleh workspace persisten (/persist) mahasiswa.
Kuota unggah (max_storage_mb) sudah ditegakkan saat UPLOAD, tetapi job/kernel bisa MENULIS
file besar SAAT EKSEKUSI (di luar jalur upload). Guard ini menutup celah itu.

Alur (loop tiap STORAGE_GUARD_INTERVAL_SECONDS):
  1. Hitung pemakaian /persist tiap user: `du -bd1 <data_root>` (cepat, TANPA sudo — folder
     dimiliki user host sejak hardening T3).
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
import shutil

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.user import User
from app.services import user_policy as user_policy_svc

logger = get_logger(__name__)

# Cache (in-memory) hasil scan terakhir — dibaca oleh admission gate (sinkron, murah).
_usage: dict[int, dict] = {}   # user_id -> {"used_mb", "quota_mb", "ratio"}
_over: set[int] = set()        # user_id yang pemakaiannya >= 100% kuota


def is_over_quota(user_id: int) -> bool:
    """True bila user melampaui kuota /persist (dipakai untuk menolak job/sesi baru)."""
    return int(user_id) in _over


def usage_snapshot() -> dict[int, dict]:
    """Salinan snapshot pemakaian terakhir per user (untuk diagnostik/tampilan)."""
    return {k: dict(v) for k, v in _usage.items()}


_MB = 1024 * 1024


async def user_disk_used_bytes(user_id: int) -> int:
    """Ukuran folder /persist milik user (bytes) via `du -sb`. 0 bila belum ada.

    Folder dimiliki user host (hardening T3) -> tanpa sudo.
    """
    p = settings.docker_user_data_root / str(int(user_id))
    if not p.exists():
        return 0
    try:
        proc = await asyncio.create_subprocess_exec(
            "du", "-sb", str(p),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        first = (out or b"").split(b"\t", 1)[0].strip()
        return int(first) if first.isdigit() else 0
    except Exception:  # noqa: BLE001 — best-effort
        return 0


async def upload_limit_bytes(user_id: int, quota_mb: float) -> int:
    """Batas unggah (bytes) = SISA kuota disk user (kuota - terpakai).

    Bila user TANPA kuota (max_storage_mb <= 0) -> dibatasi disk fisik dikurangi
    cadangan (UPLOAD_DISK_HEADROOM_MB) agar disk server bersama tak terisi penuh.
    Selalu >= 0.
    """
    # Mode LUNAK: abaikan kuota PER-USER utk unggahan (user minta tak ditolak saat lewat
    # batas), TAPI tetap jaga disk FISIK (headroom) agar disk server bersama tak penuh.
    if settings.SOFT_LIMIT_ENABLED:
        quota_mb = 0.0
    if quota_mb and quota_mb > 0:
        used = await user_disk_used_bytes(user_id)
        return max(0, int(quota_mb * _MB) - used)
    try:
        free = shutil.disk_usage(str(settings.docker_user_data_root)).free
    except Exception:  # noqa: BLE001
        free = shutil.disk_usage("/").free
    return max(0, int(free) - int(settings.UPLOAD_DISK_HEADROOM_MB * _MB))


async def _scan_disk() -> dict[int, int]:
    """`du -bd1 <data_root>` -> {user_id: bytes}. Folder milik user host (tanpa sudo)."""
    root = settings.docker_user_data_root
    if not root.exists():
        return {}
    argv = ["du", "-bd1", str(root)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
    except Exception as exc:  # noqa: BLE001 — best-effort, jangan ganggu loop
        logger.warning("Scan disk /persist gagal: %s", exc)
        return {}
    result: dict[int, int] = {}
    root_str = str(root).rstrip("/")
    for line in (out or b"").decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0].strip().isdigit():
            continue
        path = parts[1].rstrip("/")
        if path == root_str:
            continue
        name = path.rsplit("/", 1)[-1]
        if not name.isdigit():
            continue
        result[int(name)] = int(parts[0])
    return result


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


async def _tick() -> None:
    usage_bytes = await _scan_disk()
    if not usage_bytes:
        _over.clear()
        _usage.clear()
        return

    alert_ratio = max(1.0, float(settings.STORAGE_ALERT_PERCENT)) / 100.0
    new_over: set[int] = set()
    snap: dict[int, dict] = {}
    breaches: list[dict] = []  # nilai POLOS (bukan ORM) untuk di-email setelah scan

    async with AsyncSessionLocal() as db:
        for uid, nbytes in usage_bytes.items():
            eff = await user_policy_svc.effective(db, uid)
            quota_mb = float(getattr(eff, "max_storage_mb", 0.0) or 0.0)
            used_mb = nbytes / 1024 / 1024
            ratio = (used_mb / quota_mb) if quota_mb > 0 else 0.0
            snap[uid] = {
                "used_mb": round(used_mb, 1),
                "quota_mb": round(quota_mb, 1),
                "ratio": round(ratio, 3),
            }
            if quota_mb <= 0:
                continue  # tanpa batas -> tak dipantau
            user = await db.get(User, uid)
            if user is None or user.is_superadmin:
                continue  # super admin bebas
            over = ratio >= 1.0
            if not over and ratio < alert_ratio:
                continue
            if over:
                new_over.add(uid)
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
                if b["over"] and not settings.SOFT_LIMIT_ENABLED:
                    extra = " Job/sesi yang berjalan dihentikan."
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

    _over.clear()
    _over.update(new_over)
    _usage.clear()
    _usage.update(snap)

    # Mode LUNAK: JANGAN hentikan job/sesi berjalan saat 100% (user minta tak dihentikan;
    # storage = kapasitas, tak bisa di-throttle -> cukup alert. Job lanjut; tulis gagal
    # sendiri bila disk fisik benar-benar habis).
    if new_over and settings.STORAGE_ENFORCE_ENABLED and not settings.SOFT_LIMIT_ENABLED:
        for uid in new_over:
            await _enforce_user(uid)


class StorageGuard:
    """Loop latar belakang yang memantau & menegakkan kuota disk /persist per-user."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="storage-guard")
        logger.info(
            "StorageGuard jalan (interval %ss, enforce=%s, alert>=%.0f%%).",
            int(settings.STORAGE_GUARD_INTERVAL_SECONDS),
            settings.STORAGE_ENFORCE_ENABLED,
            settings.STORAGE_ALERT_PERCENT,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

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


# Instance global (dipakai lifespan & admission gate).
storage_guard = StorageGuard()
