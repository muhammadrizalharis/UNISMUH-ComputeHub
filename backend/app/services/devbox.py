"""Devbox — ngoding di VS Code sendiri, sumber daya dari server (ala Codespaces).

User membuka VS Code miliknya (desktop Windows/macOS/Linux ATAU browser vscode.dev),
lalu menempel ke container ComputeHub lewat VS Code Remote Tunnel. Editor, terminal,
debugger, dan extension berjalan DI SERVER: CPU/RAM/GPU + berkas /persist milik kampus,
laptop user hanya jadi layar.

ATURAN (semuanya tetap di tangan super admin, memakai kebijakan yang SUDAH ADA):
  - Plafon CPU/RAM/VRAM diambil dari `user_policy.effective()` (override per-user -> peran).
  - Devbox ber-GPU dihitung sebagai job berjalan: kena batas konkurensi + kuota GPU harian
    dan tercatat di tabel `jobs` (ikut masuk laporan bulanan).
  - Devbox CPU TIDAK memotong kuota GPU (selaras perlakuan job CPU).
  - Reaper mematikan devbox yang menganggur (GPU lebih ketat) & yang melewati umur maks.
  - Satu devbox per user; jumlah devbox menyala serempak dibatasi DEVBOX_MAX_RUNNING.

CATATAN DESAIN — container PERSISTEN (dibuat sekali, start/stop), bukan efemeral:
  1. Paket yang dipasang user (pip/apt --user) & extension VS Code tetap awet.
  2. Kredensial `code tunnel` disimpan TERENKRIPSI oleh CLI dengan kunci yang terikat
     identitas mesin; container efemeral selalu berganti hostname sehingga kredensial
     gagal didekripsi ("not logged in"). Container tetap + `--hostname` tetap = login
     cukup SEKALI per user.

Semua operasi HANYA menyentuh container bernama persis f"ch-devbox-{user_id}" (tak pernah
pola lebar, tak pernah `prune`) — sejalan aturan services/provision.py.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.job import Job, JobDevice, JobSource, JobStatus
from app.models.notification import Notification
from app.models.user import User
from app.services import gpu as gpu_svc
from app.services import provision
from app.services import quota as quota_svc
from app.services import reservations
from app.services import storage_guard
from app.services import user_policy as user_policy_svc
from app.services import workspace as workspace_svc

logger = get_logger(__name__)

CONTAINER_PREFIX = "ch-devbox-"
# Nama Job penanda devbox. Dipakai scheduler untuk MELEWATI job ini saat memulihkan
# job yatim: beda dgn job batch/kernel, container devbox sengaja tetap hidup melewati
# restart backend sehingga jobnya bukan yatim (direkonsiliasi _adopt_jobs di bawah).
DEVBOX_JOB_NAME = "Devbox VS Code"
_CLI_MOUNT = "/opt/vscode-cli"
# Folder data internal VS Code (server ~700MB + extension + kredensial). SENGAJA di
# luar /persist supaya tidak memakan kuota penyimpanan user & tak mengotori berkasnya.
_DATA_MOUNT = "/home/dev"
_HOME_MOUNT = _DATA_MOUNT  # kompatibilitas nama lama
_CLI_DATA = f"{_DATA_MOUNT}/cli"
_SERVER_DATA = f"{_DATA_MOUNT}/server"
_EXT_DIR = f"{_DATA_MOUNT}/extensions"
# HOME diarahkan ke ruang kerja user: dialog "Open Folder" VS Code langsung membuka
# foldernya, dan konfigurasi git/pip menyatu dengan kernel notebook (HOME-nya /persist).
# Folder yang SAMA di-mount dua kali: /persist (agar path absolut di notebook & saran
# asisten tetap berlaku) dan /CH-<nama> (nama ramah yang dilihat user di VS Code).
_USER_HOME = "/persist"
# Dinaikkan bila spesifikasi container berubah -> container lama dibuat ulang otomatis.
_SPEC_VERSION = "4"
_LOG_NAME = "tunnel.log"
# Penanda khas perintah SERVE (tak ada pada `code tunnel user login`).
_SERVE_MARKER = "--accept-server-license-terms"
# Pola pencarian proses. Kurung siku [-] membuat pola TIDAK cocok dengan teks
# skrip pengecek itu sendiri (cmdline `sh -c ...` juga terlihat di /proc).
_SERVE_GREP = "accept-server-license[-]terms"
# Server VS Code baru diunduh & dijalankan saat ADA klien menyambung -> keberadaannya
# dipakai reaper untuk membedakan "ditinggal" vs "dipakai tapi sedang dibaca".
_SERVER_GREP = "cli/servers/Stable[-]"

# Kode device-login GitHub, mis. "use code B3DA-AE2F".
_DEVICE_CODE_RE = re.compile(r"use code\s+([A-Za-z0-9]{4}-[A-Za-z0-9]{4})")
_TUNNEL_URL_RE = re.compile(r"https://vscode\.dev/tunnel/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~/-]*)?")

# Status devbox yang dilihat frontend.
STATE_STOPPED = "stopped"        # container ada/tidak, tapi tidak menyala
STATE_STARTING = "starting"      # container dinyalakan / tunnel disiapkan
STATE_NEEDS_LOGIN = "needs_login"  # menunggu user memasukkan kode di github.com/login/device
STATE_RUNNING = "running"        # tunnel hidup, siap ditempel VS Code
STATE_QUEUED = "queued"          # kapasitas devbox penuh, user menunggu giliran
STATE_ERROR = "error"


class DevboxError(RuntimeError):
    """Kegagalan yang layak ditampilkan ke user (router -> 409/503)."""


class QuotaExhausted(DevboxError):
    """Jatah GPU harian habis: devbox TIDAK dinyalakan sampai kuota kembali besok."""


def container_name(user_id: int) -> str:
    return f"{CONTAINER_PREFIX}{int(user_id)}"


def tunnel_name(user_id: int) -> str:
    prefix = (settings.DEVBOX_TUNNEL_PREFIX or "computehub").strip().lower()
    return f"{prefix}-{int(user_id)}"


def home_dir(user_id: int) -> Path:
    return settings.devbox_home_root / str(int(user_id))


def folder_label(nama: str | None, username: str | None, user_id: int) -> str:
    """Nama folder ramah yang dilihat user di VS Code, mis. CH-muhammadrizalharis.

    Hanya huruf & angka yang dipertahankan sehingga hasilnya selalu aman dipakai
    sebagai path (tak mungkin mengandung spasi, '/', atau '..').
    """
    for sumber in (nama, username):
        bersih = re.sub(r"[^a-z0-9]", "", (sumber or "").lower())
        if bersih:
            return f"CH-{bersih[:40]}"
    return f"CH-user{int(user_id)}"


async def _folder_for(user_id: int) -> str:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, int(user_id))
        return folder_label(
            getattr(user, "name", None), getattr(user, "username", None), user_id
        )


def _docker_argv(*args: str) -> list[str]:
    return [*settings.DOCKER_CMD.split(), *args]


async def _run(argv: list[str], timeout: float | None = None) -> tuple[int, str]:
    """Jalankan perintah TANPA shell. Return (rc, output gabungan). Tidak melempar."""
    limit = timeout if timeout is not None else settings.DOCKER_CMD_TIMEOUT_SECONDS
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return 127, str(exc)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=limit)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, "Timeout menjalankan docker."
    return (proc.returncode or 0), (out or b"").decode("utf-8", "replace")


@dataclass
class Devbox:
    """Satu devbox milik user (in-memory; container-nya yang durable)."""

    user_id: int
    gpu_index: int | None = None
    cpu_threads: int = 0
    cap_ram_mb: float = 0.0
    budget_vram_mb: float = 0.0
    state: str = STATE_STOPPED
    folder: str = ""
    device_code: str = ""
    verification_url: str = "https://github.com/login/device"
    tunnel_url: str = ""
    message: str = ""
    job_id: int | None = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    # Detik saat GPU BENAR-BENAR dipakai (ada proses CUDA), bukan lama devbox menyala.
    # Mengetik/membaca kode tidak menambah angka ini sehingga tidak memotong kuota.
    gpu_seconds: float = 0.0
    warned: bool = False
    _log_mtime: float = 0.0
    _task: asyncio.Task | None = None

    @property
    def container(self) -> str:
        return container_name(self.user_id)

    @property
    def log_path(self) -> Path:
        return home_dir(self.user_id) / _LOG_NAME

    @property
    def idle_timeout(self) -> int:
        if self.gpu_index is not None:
            return int(settings.DEVBOX_GPU_IDLE_TIMEOUT_SECONDS)
        return int(settings.DEVBOX_IDLE_TIMEOUT_SECONDS)

    def info(self) -> dict:
        idle = max(0.0, time.time() - self.last_active)
        timeout = self.idle_timeout
        return {
            "user_id": self.user_id,
            "state": self.state,
            "container": self.container,
            "tunnel_name": tunnel_name(self.user_id),
            "tunnel_url": self.tunnel_url,
            "folder": self.folder,
            "device_code": self.device_code,
            "verification_url": self.verification_url if self.device_code else "",
            "message": self.message,
            "device": "gpu" if self.gpu_index is not None else "cpu",
            "gpu_index": self.gpu_index,
            "cpu_threads": self.cpu_threads,
            "ram_mb": self.cap_ram_mb,
            "vram_mb": self.budget_vram_mb,
            "job_id": self.job_id,
            "gpu_seconds_used": round(self.gpu_seconds, 1),
            "uptime_seconds": max(0.0, time.time() - self.created_at),
            "idle_seconds": idle,
            "idle_timeout_seconds": timeout,
            "max_lifetime_seconds": int(settings.DEVBOX_MAX_LIFETIME_SECONDS),
        }


@dataclass
class _Ticket:
    """Antrian giliran devbox saat kapasitas penuh (FIFO, mirip sesi interaktif)."""

    user_id: int
    want_gpu: bool | None
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    granted_at: float | None = None


async def _kirim_notifikasi(user_id: int, tipe: str, judul: str, isi: str) -> None:
    """Notifikasi in-app (ikon lonceng). Best-effort — tak pernah melempar."""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                Notification(
                    user_id=int(user_id),
                    type=tipe,
                    title=judul[:200],
                    body=isi[:400],
                    link="/devbox",
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal membuat notifikasi devbox user #%s: %s", user_id, exc)


async def _check_limits(user_id: int, want_gpu: bool) -> tuple[int, float, float, bool]:
    """Tegakkan kebijakan super admin. Return (cpu, ram_mb, vram_mb, is_super).

    Devbox GPU diperlakukan seperti sesi interaktif (kena konkurensi + kuota GPU harian);
    devbox CPU hanya dibatasi plafon resource + jumlah devbox global.
    """
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise DevboxError("Pengguna tidak ditemukan.")
        if user.is_superadmin:
            return (0, 0.0, 0.0, True)

        eff = await user_policy_svc.effective(db, user_id)
        if want_gpu:
            running = int(
                await db.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.user_id == user_id, Job.status == JobStatus.running)
                )
                or 0
            )
            if eff.max_concurrent_jobs > 0 and running >= eff.max_concurrent_jobs:
                raise DevboxError(
                    f"Batas job/sesi GPU paralel tercapai ({running}/{eff.max_concurrent_jobs}). "
                    "Hentikan job atau notebook yang berjalan, atau pakai devbox mode CPU."
                )
            if eff.daily_gpu_seconds_quota > 0:
                used = await quota_svc.gpu_seconds_used(db, user_id)
                if used >= eff.daily_gpu_seconds_quota:
                    raise QuotaExhausted(
                        "Kuota GPU harian Anda sudah habis. Devbox tidak bisa dinyalakan "
                        "sampai kuota kembali penuh besok."
                    )
        return (eff.max_cpu_threads, eff.max_ram_mb, eff.max_gpu_memory_mb, False)


async def _create_devbox_job(box: Devbox) -> int | None:
    """Catat devbox sebagai Job berjalan (best-effort) agar terlihat di laporan & kuota."""
    try:
        async with AsyncSessionLocal() as db:
            job = Job(
                name=DEVBOX_JOB_NAME,
                source_type=JobSource.paste,
                is_interactive=True,
                status=JobStatus.running,
                user_id=box.user_id,
                device=JobDevice.gpu if box.gpu_index is not None else JobDevice.cpu,
                gpu_index=box.gpu_index,
                working_dir=str(workspace_svc.user_root(box.user_id)),
                started_at=dt.datetime.now(dt.timezone.utc),
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return job.id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal mencatat job devbox user #%s: %s", box.user_id, exc)
        return None


async def _close_devbox_job(job_id: int, gpu_seconds: float | None = None) -> None:
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            if job is None or job.status != JobStatus.running:
                return
            now = dt.datetime.now(dt.timezone.utc)
            job.status = JobStatus.succeeded
            job.finished_at = now
            started = job.started_at
            if started is not None:
                if started.tzinfo is None:
                    started = started.replace(tzinfo=dt.timezone.utc)
                lama = max(0.0, (now - started).total_seconds())
            else:
                lama = 0.0
            # Devbox GPU dicatat sebesar waktu GPU BENAR-BENAR dipakai (bukan lama
            # menyala) karena kolom inilah yang dijumlahkan sebagai kuota GPU harian.
            job.actual_runtime_seconds = (
                float(gpu_seconds) if gpu_seconds is not None else lama
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal menutup job devbox %s: %s", job_id, exc)


async def _adopt_jobs(alive: dict[int, "Devbox"]) -> None:
    """Selaraskan catatan Job devbox dengan container yang BENAR-BENAR hidup.

    Dipanggil saat backend baru menyala: job milik devbox yang masih hidup dipakai
    ulang (waktu pemakaian tetap menyambung), sisanya ditutup rapi sebagai selesai
    (bukan 'gagal' — devbox tidak pernah dipaksa berhenti oleh restart).
    """
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Job).where(
                        Job.status == JobStatus.running, Job.name == DEVBOX_JOB_NAME
                    )
                )
            ).scalars().all()
            now = dt.datetime.now(dt.timezone.utc)
            taken: set[int] = set()
            for job in rows:
                box = alive.get(job.user_id)
                if box is not None and job.user_id not in taken:
                    box.job_id = job.id
                    taken.add(job.user_id)
                    continue
                job.status = JobStatus.succeeded
                job.finished_at = now
                started = job.started_at
                if started is not None:
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=dt.timezone.utc)
                    lama = max(0.0, (now - started).total_seconds())
                else:
                    lama = 0.0
                # Job GPU yang ditutup tanpa pengukuran (container hilang) dicatat 0:
                # kuota GPU hanya boleh memotong waktu yang TERBUKTI dipakai.
                job.actual_runtime_seconds = 0.0 if job.gpu_index is not None else lama
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal menyelaraskan job devbox: %s", exc)
    for uid, box in alive.items():
        if box.job_id is None:
            box.job_id = await _create_devbox_job(box)


class DevboxManager:
    """Kelola seluruh devbox + reaper idle/umur. Satu instance global."""

    def __init__(self) -> None:
        self._boxes: dict[int, Devbox] = {}
        self._queue: list[_Ticket] = []
        self._last_sweep: float = 0.0
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None
        self._stopping = False

    # ---------- daur hidup service ----------

    async def start(self) -> None:
        if not settings.DEVBOX_ENABLED:
            logger.info("Devbox nonaktif (DEVBOX_ENABLED=false).")
            return
        self._stopping = False
        await self._adopt_running()
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_loop())
        logger.info("Devbox aktif (maks %d menyala).", settings.DEVBOX_MAX_RUNNING)

    async def stop(self) -> None:
        """Hentikan reaper. Container SENGAJA dibiarkan hidup (restart backend != usir user)."""
        self._stopping = True
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reaper = None

    async def _adopt_running(self) -> None:
        """Pungut kembali devbox yang masih menyala setelah backend restart."""
        rc, out = await _run(
            _docker_argv(
                "ps", "--filter", f"name=^{CONTAINER_PREFIX}", "--format", "{{.Names}}"
            )
        )
        if rc != 0:
            return
        for name in [n.strip() for n in out.splitlines() if n.strip()]:
            if not name.startswith(CONTAINER_PREFIX):
                continue
            try:
                uid = int(name[len(CONTAINER_PREFIX) :])
            except ValueError:
                continue
            gpu_index = await self._inspect_gpu(name)
            box = Devbox(user_id=uid, gpu_index=gpu_index, state=STATE_RUNNING)
            box.folder = await _folder_for(uid)
            box.tunnel_url = self._read_tunnel_url(box)
            if gpu_index is not None:
                box.budget_vram_mb = settings.INTERACTIVE_DEFAULT_VRAM_MB
                reservations.reserve(
                    f"devbox:{uid}", gpu_index, box.budget_vram_mb, kind="interactive"
                )
            self._boxes[uid] = box
            # Container hidup tapi tunnel mati (mis. backend restart lama) -> pulihkan.
            if not await self._tunnel_running(box):
                box.state = STATE_STARTING
                box._task = asyncio.create_task(self._bring_up_tunnel(box))
            logger.info("Devbox user #%d dipungut kembali (container %s).", uid, name)
        await _adopt_jobs(self._boxes)

    async def _inspect_gpu(self, name: str) -> int | None:
        """Baca indeks GPU container dari env NVIDIA_VISIBLE_DEVICES (bila ada)."""
        rc, out = await _run(
            _docker_argv("inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", name)
        )
        if rc != 0:
            return None
        for line in out.splitlines():
            if line.startswith("NVIDIA_VISIBLE_DEVICES="):
                val = line.split("=", 1)[1].strip()
                if val and val not in {"void", "none", "all"}:
                    try:
                        return int(val.split(",")[0])
                    except ValueError:
                        return None
        return None

    # ---------- query ----------

    def get(self, user_id: int) -> Devbox | None:
        return self._boxes.get(int(user_id))

    def list_all(self) -> list[dict]:
        return [b.info() for b in self._boxes.values()]

    def disk_usage(self) -> dict:
        """Ringkasan disk HOME devbox (server VS Code + extension per user).

        Tidak dihitung dalam kuota /persist user, jadi perlu terlihat admin: satu user
        yang sudah pernah menyambung memakai ratusan MB.
        """
        root = settings.devbox_home_root
        total = 0
        per_user: list[dict] = []
        try:
            anak = sorted(root.iterdir()) if root.exists() else []
        except OSError:
            anak = []
        for d in anak:
            if not d.is_dir() or not d.name.isdigit():
                continue
            besar = 0
            for f in d.rglob("*"):
                try:
                    if f.is_file() and not f.is_symlink():
                        besar += f.stat().st_size
                except OSError:
                    continue
            total += besar
            per_user.append({"user_id": int(d.name), "bytes": besar})
        per_user.sort(key=lambda x: x["bytes"], reverse=True)
        return {
            "total_bytes": total,
            "users": per_user,
            "retention_days": int(settings.DEVBOX_HOME_RETENTION_DAYS),
        }

    def running_count(self) -> int:
        # needs_login IKUT dihitung: containernya sudah menyala & memakai resource.
        return sum(
            1
            for b in self._boxes.values()
            if b.state in (STATE_RUNNING, STATE_STARTING, STATE_NEEDS_LOGIN)
        )

    # ---------- antrian giliran ----------

    def _ticket_for(self, user_id: int) -> _Ticket | None:
        for t in self._queue:
            if t.user_id == user_id:
                return t
        return None

    def _ensure_ticket(self, user_id: int, want_gpu: bool | None) -> _Ticket:
        t = self._ticket_for(user_id)
        if t is not None:
            t.last_seen = time.time()
            t.want_gpu = want_gpu
            return t
        t = _Ticket(user_id=user_id, want_gpu=want_gpu)
        self._queue.append(t)
        logger.info("Devbox: user #%d masuk antrian.", user_id)
        return t

    def _drop_ticket(self, user_id: int) -> None:
        self._queue = [t for t in self._queue if t.user_id != user_id]

    def _waiting_position(self, ticket: _Ticket) -> int:
        waiting = [t for t in self._queue if t.granted_at is None]
        return (waiting.index(ticket) + 1) if ticket in waiting else 1

    def _queue_info(self, t: _Ticket) -> dict:
        return {
            "user_id": t.user_id,
            "state": STATE_QUEUED,
            "enabled": True,
            "allow_gpu": bool(settings.DEVBOX_ALLOW_GPU),
            "device": "gpu" if t.want_gpu else "cpu",
            "queue_position": self._waiting_position(t),
            "queue_waiting": sum(1 for x in self._queue if x.granted_at is None),
            "queue_ready": t.granted_at is not None,
            "message": (
                "Giliran Anda sudah tiba — devbox sedang dinyalakan."
                if t.granted_at is not None
                else "Kapasitas devbox sedang penuh. Anda dalam antrian dan akan otomatis "
                "mendapat giliran begitu ada yang selesai."
            ),
            "idle_timeout_seconds": int(settings.DEVBOX_IDLE_TIMEOUT_SECONDS),
            "max_lifetime_seconds": int(settings.DEVBOX_MAX_LIFETIME_SECONDS),
        }

    def _promote(self) -> None:
        """Beri giliran ke tiket terdepan saat ada slot kosong."""
        libre = max(1, int(settings.DEVBOX_MAX_RUNNING)) - self.running_count()
        if libre <= 0:
            return
        for t in self._queue:
            if libre <= 0:
                break
            if t.granted_at is None:
                t.granted_at = time.time()
                libre -= 1
                logger.info("Devbox: user #%d dapat giliran.", t.user_id)
                asyncio.create_task(
                    _kirim_notifikasi(
                        t.user_id,
                        "devbox_ready",
                        "Giliran devbox Anda tiba",
                        "Kapasitas sudah tersedia. Buka menu Devbox untuk menyalakannya "
                        "sekarang sebelum giliran diberikan ke pengguna lain.",
                    )
                )

    def _expire_tickets(self, now: float) -> None:
        grant_ttl = int(settings.DEVBOX_GRANT_TTL_SECONDS)
        queue_ttl = int(settings.DEVBOX_QUEUE_TTL_SECONDS)
        sisa: list[_Ticket] = []
        for t in self._queue:
            basi = (
                grant_ttl > 0 and (now - t.granted_at) > grant_ttl
                if t.granted_at is not None
                else queue_ttl > 0 and (now - t.last_seen) > queue_ttl
            )
            if basi:
                logger.info("Devbox: tiket user #%d kedaluwarsa.", t.user_id)
            else:
                sisa.append(t)
        self._queue = sisa

    async def status(self, user_id: int) -> dict:
        """Status devbox user (sinkron dgn kondisi container sebenarnya)."""
        box = self._boxes.get(int(user_id))
        if box is None:
            tiket = self._ticket_for(int(user_id))
            if tiket is not None:
                tiket.last_seen = time.time()
                return self._queue_info(tiket)
            # Batas waktu tetap dikirim walau devbox mati: dipakai UI untuk menjelaskan
            # aturan SEBELUM user menyalakannya.
            return {
                "user_id": int(user_id),
                "state": STATE_STOPPED,
                "enabled": bool(settings.DEVBOX_ENABLED),
                "allow_gpu": bool(settings.DEVBOX_ALLOW_GPU),
                "idle_timeout_seconds": int(settings.DEVBOX_IDLE_TIMEOUT_SECONDS),
                "max_lifetime_seconds": int(settings.DEVBOX_MAX_LIFETIME_SECONDS),
            }
        if box.state in (STATE_RUNNING, STATE_NEEDS_LOGIN):
            if not await self._is_container_running(box.container):
                await self._forget(box, "Container berhenti.")
            elif box.state == STATE_RUNNING and not box.tunnel_url:
                box.tunnel_url = self._read_tunnel_url(box)
        info = box.info()
        info["enabled"] = bool(settings.DEVBOX_ENABLED)
        info["allow_gpu"] = bool(settings.DEVBOX_ALLOW_GPU)
        return info

    # ---------- operasi utama ----------

    async def ensure(self, user_id: int, want_gpu: bool | None = None) -> dict:
        """Nyalakan devbox user (buat container bila perlu) lalu siapkan tunnel.

        want_gpu=None (default) = OTOMATIS: GPU diberikan bila masih ada kapasitas dan
        kuota harian belum habis; kalau tidak, devbox tetap menyala dengan CPU. Pengguna
        tidak perlu memilih dan tidak pernah gagal menyalakan hanya karena GPU penuh.
        """
        if not settings.DEVBOX_ENABLED:
            raise DevboxError("Fitur devbox belum diaktifkan super admin.")
        if want_gpu and not settings.DEVBOX_ALLOW_GPU:
            raise DevboxError("Devbox mode GPU dinonaktifkan super admin.")
        if not settings.devbox_cli_dir.joinpath("code").exists():
            raise DevboxError(
                "CLI VS Code belum terpasang di server. Hubungi admin "
                "(jalankan scripts/setup_devbox_cli.sh)."
            )
        user_id = int(user_id)

        async with self._lock:
            box = self._boxes.get(user_id)
            if box is not None and box.state in (STATE_RUNNING, STATE_STARTING, STATE_NEEDS_LOGIN):
                if await self._is_container_running(box.container):
                    if want_gpu is not None and want_gpu != (box.gpu_index is not None):
                        diminta = "GPU" if want_gpu else "CPU"
                        aktif = "GPU" if box.gpu_index is not None else "CPU"
                        raise DevboxError(
                            f"Devbox Anda sedang berjalan dalam mode {aktif}. "
                            f"Hentikan dulu, lalu nyalakan ulang untuk pindah ke mode {diminta}."
                        )
                    box.last_active = time.time()
                    return box.info()
                await self._forget(box, "")

            if storage_guard.is_over_quota(user_id):
                raise DevboxError(
                    "Kuota penyimpanan Anda penuh. Rapikan berkas di menu Penyimpanan dulu."
                )
            if self.running_count() >= max(1, int(settings.DEVBOX_MAX_RUNNING)):
                # Kapasitas penuh -> masuk antrian FIFO (bukan sekadar ditolak).
                t = self._ensure_ticket(user_id, want_gpu)
                if t.granted_at is None:
                    return self._queue_info(t)

            # Mode OTOMATIS: coba GPU dulu, tetapi jangan pernah menggagalkan devbox
            # hanya karena GPU penuh / kuota GPU habis -> turun ke CPU dengan alasan
            # yang bisa ditampilkan ke pengguna.
            otomatis = want_gpu is None
            coba_gpu = bool(want_gpu) or (otomatis and settings.DEVBOX_ALLOW_GPU)
            alasan = ""
            try:
                cpu_threads, cap_ram_mb, cap_vram_mb, is_super = await _check_limits(
                    user_id, coba_gpu
                )
            except QuotaExhausted:
                # Kuota habis = berhenti total sampai besok (selaras notebook & job),
                # BUKAN diturunkan diam-diam ke CPU.
                raise
            except DevboxError:
                if not otomatis:
                    raise
                coba_gpu = False
                alasan = "Batas sesi paralel tercapai, jadi devbox berjalan dengan CPU."
                cpu_threads, cap_ram_mb, cap_vram_mb, is_super = await _check_limits(
                    user_id, False
                )

            gpu_index: int | None = None
            budget = 0.0
            if coba_gpu:
                budget = cap_vram_mb if cap_vram_mb > 0 else settings.INTERACTIVE_DEFAULT_VRAM_MB
                gpu_index = gpu_svc.pick_gpu_for(budget)
                if gpu_index is None:
                    if not otomatis:
                        raise DevboxError(
                            "Semua GPU sedang penuh. Coba mode CPU dulu, atau ulangi nanti."
                        )
                    budget = 0.0
                    alasan = "Semua GPU sedang dipakai, jadi devbox berjalan dengan CPU."

            box = Devbox(
                user_id=user_id,
                gpu_index=gpu_index,
                cpu_threads=cpu_threads,
                cap_ram_mb=cap_ram_mb,
                budget_vram_mb=budget,
                state=STATE_STARTING,
                folder=await _folder_for(user_id),
                message=alasan,
            )
            self._boxes[user_id] = box
            if gpu_index is not None:
                reservations.reserve(f"devbox:{user_id}", gpu_index, budget, kind="interactive")

            try:
                await self._ensure_container(box)
            except Exception:
                await self._forget(box, "Gagal menyiapkan container.")
                raise

            box.job_id = await _create_devbox_job(box)
            box._task = asyncio.create_task(self._bring_up_tunnel(box))
            self._drop_ticket(user_id)  # giliran sudah dipakai
            return box.info()

    async def shutdown_user(self, user_id: int, remove: bool = False) -> bool:
        """Matikan devbox user. remove=True juga menghapus container (login ikut hilang)."""
        async with self._lock:
            box = self._boxes.get(int(user_id))
            name = container_name(user_id)
            existed = box is not None or await self._container_exists(name)
            if box is not None:
                await self._forget(box, "Dihentikan.")
            await _run(_docker_argv("stop", "-t", "10", name), timeout=30.0)
            if remove:
                await _run(_docker_argv("rm", "-f", name))
            return existed

    # ---------- container ----------

    async def _container_exists(self, name: str) -> bool:
        rc, out = await _run(
            _docker_argv("ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}")
        )
        return rc == 0 and name in out.split()

    async def _is_container_running(self, name: str) -> bool:
        rc, out = await _run(
            _docker_argv("ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}")
        )
        return rc == 0 and name in out.split()

    def _prepare_dirs(self, user_id: int) -> tuple[Path, Path]:
        home = home_dir(user_id)
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(home, 0o700)
        for sub in ("cli", "server", "extensions"):
            (home / sub).mkdir(exist_ok=True)
        # Kredensial dari tata letak lama ($HOME/.vscode/cli) -> lokasi baru, supaya
        # user yang sudah pernah login tidak diminta otorisasi ulang.
        lama = home / ".vscode" / "cli" / "token.json"
        baru = home / "cli" / "token.json"
        if lama.exists() and not baru.exists():
            try:
                shutil.copy2(lama, baru)
            except OSError as exc:
                logger.warning("Gagal memindahkan kredensial devbox #%d: %s", user_id, exc)
        persist = workspace_svc.ensure_root(user_id)
        return home, persist

    def _create_argv(self, box: Devbox, home: Path, persist: Path) -> list[str]:
        """Argumen `docker create` untuk devbox (batas resource + hardening)."""
        name = box.container
        kerja = f"/{box.folder}" if box.folder else _USER_HOME
        threads = box.cpu_threads if box.cpu_threads > 0 else settings.JOB_DEFAULT_CPU_THREADS
        threads = max(1, int(threads))
        args = [
            "create",
            "--name", name,
            "--hostname", name,          # identitas mesin TETAP -> kredensial tunnel awet
            "--restart", "no",
            "--init",
            "-w", kerja,
            "-e", f"HOME={kerja}",
            "--label", f"ch-devbox-spec={_SPEC_VERSION}:{box.folder}",
            "-e", "PYTHONUNBUFFERED=1",
            "-e", f"OMP_NUM_THREADS={threads}",
            "-e", f"MKL_NUM_THREADS={threads}",
            "-e", f"OPENBLAS_NUM_THREADS={threads}",
            "-e", f"NUMEXPR_NUM_THREADS={threads}",
            "--cpus", str(threads),
            "-v", f"{settings.devbox_cli_dir}:{_CLI_MOUNT}:ro",
            "-v", f"{home}:{_HOME_MOUNT}",
            "-v", f"{persist}:{_USER_HOME}",
        ]
        # Folder yang sama juga tampil dengan nama ramah (yang dibuka user di VS Code).
        if kerja != _USER_HOME:
            args += ["-v", f"{persist}:{kerja}"]
        args += provision.hardening_argv()
        pids = int(settings.DOCKER_USER_PIDS_LIMIT or 0)
        if pids > 0:
            args += ["--pids-limit", str(pids)]
        if box.cap_ram_mb and box.cap_ram_mb > 0:
            if settings.SOFT_LIMIT_ENABLED:
                mult = float(settings.SOFT_LIMIT_RAM_HARD_MULT)
                args += ["--memory-reservation", f"{int(box.cap_ram_mb)}m"]
                if mult > 0:
                    args += ["--memory", f"{int(box.cap_ram_mb * mult)}m"]
            else:
                args += ["--memory", f"{int(box.cap_ram_mb)}m"]
        if box.gpu_index is not None:
            if (settings.DOCKER_GPU_MODE or "gpus").strip().lower() == "legacy":
                args += [
                    "--runtime", "nvidia",
                    "-e", f"NVIDIA_VISIBLE_DEVICES={box.gpu_index}",
                ]
            else:
                args += ["--gpus", f"device={box.gpu_index}"]
            args += [
                "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
                "-e", "CUDA_DEVICE_ORDER=PCI_BUS_ID",
            ]
            # JANGAN set CUDA_VISIBLE_DEVICES ke indeks GPU host: container hanya
            # melihat satu GPU dan di dalamnya selalu bernomor 0, sehingga menyetel
            # indeks host (mis. 1) membuat torch.cuda.is_available() False.
        models = settings.shared_models_path
        if models.exists():
            args += [
                "-v", f"{models}:/opt/ch-models:ro",
                "-e", "CH_SHARED_MODELS=/opt/ch-models",
            ]
        args += [settings.DOCKER_USER_IMAGE, "sleep", "infinity"]
        return _docker_argv(*args)

    async def _ensure_container(self, box: Devbox) -> None:
        """Buat container bila belum ada (atau spesifikasinya berubah) lalu nyalakan."""
        name = box.container
        home, persist = await asyncio.to_thread(self._prepare_dirs, box.user_id)

        if await self._container_exists(name):
            current_gpu = await self._inspect_gpu(name)
            rc_spec, spec = await _run(
                _docker_argv(
                    "inspect", "-f",
                    '{{index .Config.Labels "ch-devbox-spec"}}', name,
                )
            )
            spec_lama = spec.strip() if rc_spec == 0 else ""
            if current_gpu != box.gpu_index or spec_lama != f"{_SPEC_VERSION}:{box.folder}":
                # Mode perangkat / spesifikasi berubah -> container harus dibuat ulang.
                # Aman: kode & data user ada di volume /persist + data devbox.
                logger.info("Devbox #%d dibuat ulang (spesifikasi berubah).", box.user_id)
                await _run(_docker_argv("rm", "-f", name))
            elif not await self._is_container_running(name):
                rc, out = await _run(_docker_argv("start", name), timeout=60.0)
                if rc != 0:
                    raise DevboxError(f"Gagal menyalakan devbox: {out.strip()[:200]}")
                return
            else:
                return

        rc, out = await _run(self._create_argv(box, home, persist), timeout=120.0)
        if rc != 0:
            raise DevboxError(f"Gagal membuat devbox: {out.strip()[:200]}")
        rc, out = await _run(_docker_argv("start", name), timeout=60.0)
        if rc != 0:
            raise DevboxError(f"Gagal menyalakan devbox: {out.strip()[:200]}")

    # ---------- tunnel ----------

    async def _is_logged_in(self, box: Devbox) -> bool:
        rc, out = await _run(
            _docker_argv(
                "exec", box.container, f"{_CLI_MOUNT}/code",
                "tunnel", "--cli-data-dir", _CLI_DATA, "user", "show",
            ),
            timeout=30.0,
        )
        return rc == 0 and "not logged in" not in out.lower()

    async def _tunnel_running(self, box: Devbox) -> bool:
        """Cek proses `code tunnel` yang MELAYANI di dalam container.

        Penanda `--accept-server-license-terms` hanya dipakai perintah serve, sehingga
        proses `code tunnel user login` (yang juga mengandung "code tunnel") tidak
        salah dikira tunnel siap.
        """
        script = (
            'for p in /proc/[0-9]*; do '
            'tr "\\0" " " < "$p/cmdline" 2>/dev/null '
            f'| grep -qE "{_SERVE_GREP}" && exit 0; '
            'done; exit 1'
        )
        rc, _ = await _run(
            _docker_argv("exec", box.container, "sh", "-c", script), timeout=30.0
        )
        return rc == 0

    def _read_tunnel_url(self, box: Devbox) -> str:
        try:
            text = box.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        found = _TUNNEL_URL_RE.findall(text)
        return found[-1] if found else ""

    async def _bring_up_tunnel(self, box: Devbox) -> None:
        """Latar: pastikan login (device code) lalu jalankan `code tunnel`."""
        try:
            if not await self._is_logged_in(box):
                box.state = STATE_NEEDS_LOGIN
                box.message = "Menunggu otorisasi akun GitHub Anda."
                ok = await self._device_login(box)
                if not ok:
                    box.state = STATE_ERROR
                    box.message = box.message or "Login GitHub gagal / kedaluwarsa."
                    return
            box.device_code = ""
            box.message = ""
            await self._launch_tunnel(box)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Devbox #%d gagal menyalakan tunnel: %s", box.user_id, exc)
            box.state = STATE_ERROR
            box.message = str(exc)[:200]

    async def _device_login(self, box: Devbox) -> bool:
        """Jalankan device-login GitHub; publikasikan kodenya ke frontend."""
        argv = _docker_argv(
            "exec", box.container,
            f"{_CLI_MOUNT}/code", "tunnel", "--cli-data-dir", _CLI_DATA,
            "user", "login", "--provider", "github",
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
        except Exception as exc:  # noqa: BLE001
            box.message = f"Gagal memulai login: {exc}"
            return False

        deadline = time.time() + float(settings.DEVBOX_LOGIN_TIMEOUT_SECONDS)
        assert proc.stdout is not None
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                line_b = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                if not line_b:
                    break
                line = line_b.decode("utf-8", "replace")
                m = _DEVICE_CODE_RE.search(line)
                if m:
                    box.device_code = m.group(1).upper()
                    box.message = "Buka github.com/login/device lalu masukkan kode ini."
                    logger.info("Devbox #%d menunggu otorisasi GitHub.", box.user_id)
            await asyncio.wait_for(proc.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            box.message = "Waktu otorisasi habis. Klik Mulai lagi untuk kode baru."
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return False
        finally:
            box.device_code = box.device_code if proc.returncode is None else ""
        return proc.returncode == 0

    async def _launch_tunnel(self, box: Devbox) -> None:
        """Jalankan `code tunnel` terlepas (detached) + tulis log ke HOME devbox."""
        if await self._tunnel_running(box):
            box.state = STATE_RUNNING
            box.message = ""
            box.tunnel_url = self._read_tunnel_url(box)
            return
        log_in_container = f"{_DATA_MOUNT}/{_LOG_NAME}"
        cmd = (
            f"exec {_CLI_MOUNT}/code tunnel {_SERVE_MARKER} "
            f"--cli-data-dir {_CLI_DATA} --server-data-dir {_SERVER_DATA} "
            f"--extensions-dir {_EXT_DIR} "
            f"--name {tunnel_name(box.user_id)} > {log_in_container} 2>&1"
        )
        rc, out = await _run(
            _docker_argv("exec", "-d", box.container, "sh", "-c", cmd), timeout=30.0
        )
        if rc != 0:
            raise DevboxError(f"Gagal menjalankan tunnel: {out.strip()[:200]}")

        deadline = time.time() + float(settings.DEVBOX_START_TIMEOUT_SECONDS)
        while time.time() < deadline:
            await asyncio.sleep(2.0)
            url = self._read_tunnel_url(box)
            if url:
                box.tunnel_url = url
                box.state = STATE_RUNNING
                box.message = ""
                box.last_active = time.time()
                logger.info("Devbox #%d siap: %s", box.user_id, url)
                return
        raise DevboxError("Tunnel tidak siap tepat waktu. Coba mulai ulang devbox.")

    # ---------- reaper ----------

    async def _forget(self, box: Devbox, message: str) -> None:
        """Lepas state + reservasi GPU + tutup job (TIDAK menghapus container)."""
        self._boxes.pop(box.user_id, None)
        reservations.release(f"devbox:{box.user_id}")
        if box._task is not None and not box._task.done():
            box._task.cancel()
        if box.job_id is not None:
            await _close_devbox_job(
                box.job_id, box.gpu_seconds if box.gpu_index is not None else None
            )
            box.job_id = None
        box.state = STATE_STOPPED
        box.message = message

    async def _cpu_percent(self, names: list[str]) -> dict[str, float]:
        if not names:
            return {}
        rc, out = await _run(
            _docker_argv("stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}", *names),
            timeout=45.0,
        )
        if rc != 0:
            return {}
        result: dict[str, float] = {}
        for line in out.splitlines():
            parts = line.strip().split("\t")
            if len(parts) != 2:
                continue
            try:
                result[parts[0].strip()] = float(parts[1].strip().rstrip("%"))
            except ValueError:
                continue
        return result

    def _log_touched(self, box: Devbox) -> bool:
        """True bila log tunnel berubah sejak cek terakhir (indikasi klien menyambung)."""
        try:
            mtime = box.log_path.stat().st_mtime
        except OSError:
            return False
        changed = mtime > box._log_mtime
        box._log_mtime = mtime
        return changed

    async def _client_connected(self, box: Devbox) -> bool:
        """True bila server VS Code hidup — artinya ada klien yang menyambung.

        Server hanya diunduh & dijalankan saat klien pertama menempel, jadi ini
        membedakan devbox yang DITINGGAL dari yang sedang dipakai (walau penggunanya
        cuma membaca kode sehingga CPU nyaris nol).
        """
        script = (
            'for p in /proc/[0-9]*; do '
            'tr "\\0" " " < "$p/cmdline" 2>/dev/null '
            f'| grep -qE "{_SERVER_GREP}" && exit 0; '
            'done; exit 1'
        )
        rc, _ = await _run(
            _docker_argv("exec", box.container, "sh", "-c", script), timeout=30.0
        )
        return rc == 0

    async def _sweep_stale(self) -> None:
        """Bersihkan container & HOME devbox yang lama tidak dipakai (hemat disk)."""
        hari_c = int(settings.DEVBOX_CONTAINER_RETENTION_DAYS)
        hari_h = int(settings.DEVBOX_HOME_RETENTION_DAYS)
        batas_c = hari_c * 86400
        batas_h = hari_h * 86400
        now = time.time()

        if hari_c > 0:
            rc, out = await _run(
                _docker_argv(
                    "ps", "-a", "--filter", f"name=^{CONTAINER_PREFIX}",
                    "--filter", "status=exited", "--format", "{{.Names}}",
                )
            )
            if rc == 0:
                for name in [n.strip() for n in out.splitlines() if n.strip()]:
                    rc2, finished = await _run(
                        _docker_argv("inspect", "-f", "{{.State.FinishedAt}}", name)
                    )
                    if rc2 != 0:
                        continue
                    try:
                        selesai = dt.datetime.fromisoformat(
                            finished.strip().replace("Z", "+00:00")
                        ).timestamp()
                    except ValueError:
                        continue
                    if (now - selesai) > batas_c:
                        await _run(_docker_argv("rm", "-f", name))
                        logger.info("Devbox: container lama %s dihapus (hemat disk).", name)

        if hari_h > 0:
            root = settings.devbox_home_root
            try:
                anak = list(root.iterdir()) if root.exists() else []
            except OSError:
                anak = []
            for d in anak:
                if not d.is_dir() or not d.name.isdigit():
                    continue
                uid = int(d.name)
                if uid in self._boxes:
                    continue
                try:
                    if (now - d.stat().st_mtime) <= batas_h:
                        continue
                except OSError:
                    continue
                if await self._container_exists(container_name(uid)):
                    continue  # container masih ada -> HOME-nya masih terpakai
                try:
                    await asyncio.to_thread(shutil.rmtree, d, True)
                    logger.info("Devbox: HOME user #%d dibersihkan (lama tak dipakai).", uid)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Gagal membersihkan HOME devbox #%d: %s", uid, exc)

    async def _container_pids(self, name: str) -> set[int]:
        """PID (namespace HOST) semua proses di dalam container.

        Memakai `docker top` — bukan pohon proses dari State.Pid — karena proses yang
        dijalankan lewat `docker exec` (termasuk tunnel & perintah pengguna) BUKAN anak
        dari PID utama container sehingga tak akan terjaring bila ditelusuri lewat induk.
        """
        rc, out = await _run(_docker_argv("top", name, "-eo", "pid"))
        if rc != 0:
            return set()
        pids: set[int] = set()
        for baris in out.splitlines():
            s = baris.strip()
            if s.isdigit():
                pids.add(int(s))
        return pids

    async def _gpu_busy(self, box: Devbox) -> bool:
        """True bila ada proses di dalam devbox yang benar-benar memakai GPU.

        Dipakai agar kuota GPU hanya berkurang saat komputasi berjalan. Mengetik,
        membaca kode, atau menjalankan perintah CPU tidak menyentuh GPU sehingga
        tidak memotong jatah harian pengguna.
        """
        if box.gpu_index is None:
            return False
        pids = await self._container_pids(box.container)
        if not pids:
            return False
        # Proses tanpa konteks CUDA tidak muncul di daftar pemakai memori GPU.
        return gpu_svc.gpu_process_memory_mb(box.gpu_index, pids) > 0.0

    async def _quota_habis(self, box: Devbox) -> bool:
        """True bila jatah GPU harian user sudah tercapai (termasuk pemakaian berjalan)."""
        if box.gpu_index is None:
            return False
        async with AsyncSessionLocal() as db:
            user = await db.get(User, box.user_id)
            if user is None or user.is_superadmin:
                return False
            eff = await user_policy_svc.effective(db, box.user_id)
            if eff.daily_gpu_seconds_quota <= 0:
                return False
            terpakai = await quota_svc.gpu_seconds_used(db, box.user_id)
        return (terpakai + box.gpu_seconds) >= eff.daily_gpu_seconds_quota

    async def _reap_loop(self) -> None:
        interval = max(10.0, float(settings.DEVBOX_SAMPLE_INTERVAL_SECONDS))
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            if self._stopping:
                break
            try:
                boxes = [b for b in self._boxes.values() if b.state == STATE_RUNNING]
                stats = await self._cpu_percent([b.container for b in boxes])
                now = time.time()
                life = int(settings.DEVBOX_MAX_LIFETIME_SECONDS)
                warn = int(settings.DEVBOX_IDLE_WARN_SECONDS)

                # Devbox yang mandek sebelum siap (otorisasi tak pernah selesai / gagal)
                # tetap memegang container & slot -> bebaskan supaya antrian jalan.
                batas_siap = float(settings.DEVBOX_LOGIN_TIMEOUT_SECONDS) + 120.0
                for box in [
                    b
                    for b in self._boxes.values()
                    if b.state in (STATE_STARTING, STATE_NEEDS_LOGIN, STATE_ERROR)
                ]:
                    if (now - box.created_at) > batas_siap:
                        logger.info(
                            "Devbox #%d tak kunjung siap (%s) -> dibebaskan.",
                            box.user_id,
                            box.state,
                        )
                        await self._stop_and_notify(
                            box,
                            "Devbox dibatalkan",
                            "Otorisasi tidak selesai tepat waktu sehingga devbox dilepas "
                            "agar bisa dipakai pengguna lain. Silakan mulai lagi.",
                        )

                # Kuota GPU dihitung untuk SEMUA devbox yang memegang GPU (termasuk yang
                # masih menunggu otorisasi), karena GPU sudah dipesan atas nama mereka.
                # Yang ditambahkan hanya detik saat GPU BENAR-BENAR dipakai.
                for box in [
                    b
                    for b in self._boxes.values()
                    if b.gpu_index is not None
                    and b.state in (STATE_RUNNING, STATE_STARTING, STATE_NEEDS_LOGIN)
                ]:
                    if not await self._gpu_busy(box):
                        continue
                    box.gpu_seconds += interval
                    if await self._quota_habis(box):
                        logger.info("Devbox #%d kuota GPU habis -> dihentikan.", box.user_id)
                        await self._stop_and_notify(
                            box,
                            "Kuota GPU harian habis",
                            "Devbox dihentikan karena jatah GPU harian Anda sudah terpakai. "
                            "Kuota penuh lagi besok. Berkas Anda aman di Penyimpanan.",
                        )

                for box in boxes:
                    if not await self._is_container_running(box.container):
                        await self._forget(box, "Container berhenti di luar aplikasi.")
                        continue
                    # Ambang "sibuk" dilonggarkan saat klien VS Code tersambung supaya
                    # pengguna yang sedang MEMBACA kode tidak dikira menganggur.
                    tersambung = await self._client_connected(box)
                    ambang = (
                        float(settings.DEVBOX_BUSY_CPU_CONNECTED_PERCENT)
                        if tersambung
                        else float(settings.DEVBOX_BUSY_CPU_PERCENT)
                    )
                    if stats.get(box.container, 0.0) >= ambang or self._log_touched(box):
                        box.last_active = now
                        box.warned = False
                    if life > 0 and (now - box.created_at) > life:
                        logger.info("Devbox #%d melewati umur maks -> dimatikan.", box.user_id)
                        await self._stop_and_notify(
                            box,
                            "Devbox dihentikan (batas waktu)",
                            "Devbox Anda sudah menyala melewati batas maksimum. Berkas Anda "
                            "aman di Penyimpanan — silakan nyalakan lagi bila masih diperlukan.",
                        )
                        continue
                    timeout = box.idle_timeout
                    if timeout <= 0:
                        continue
                    menganggur = now - box.last_active
                    if menganggur > timeout:
                        logger.info("Devbox #%d menganggur -> dimatikan.", box.user_id)
                        await self._stop_and_notify(
                            box,
                            "Devbox dihentikan (tidak aktif)",
                            "Devbox Anda dimatikan karena lama tidak dipakai agar sumber daya "
                            "bisa dipakai pengguna lain. Berkas Anda aman di Penyimpanan.",
                        )
                    elif warn > 0 and not box.warned and menganggur > (timeout - warn):
                        box.warned = True
                        sisa = max(1, int((timeout - menganggur) // 60))
                        await _kirim_notifikasi(
                            box.user_id,
                            "devbox_idle_warning",
                            "Devbox akan dimatikan sebentar lagi",
                            f"Tidak ada aktivitas terdeteksi. Devbox dimatikan dalam sekitar "
                            f"{sisa} menit. Kembali ke VS Code Anda untuk membatalkannya.",
                        )

                self._expire_tickets(now)
                self._promote()

                # Selaraskan catatan job dgn devbox yang benar-benar hidup. Tanpa ini,
                # job devbox yatim (container hilang di luar aplikasi) akan menggantung
                # 'running' selamanya dan mengunci batas sesi paralel pemiliknya --
                # scheduler sengaja TIDAK menyentuh job devbox.
                await _adopt_jobs(self._boxes)

                # Pembersihan disk cukup sekali per jam (operasi docker/berkas mahal).
                if (now - self._last_sweep) > 3600:
                    self._last_sweep = now
                    await self._sweep_stale()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Devbox reaper error: %s", exc)

    async def _stop_and_notify(self, box: Devbox, judul: str, isi: str) -> None:
        uid = box.user_id
        await self.shutdown_user(uid)
        await _kirim_notifikasi(uid, "devbox_stopped", judul, isi)


devbox_manager = DevboxManager()
