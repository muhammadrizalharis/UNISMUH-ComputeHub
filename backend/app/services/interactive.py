"""Sesi INTERAKTIF (notebook/console ala Colab) dengan kernel Jupyter hidup.

Setiap sesi = 1 kernel IPython yang dipasang (pin) ke 1 GPU lewat
CUDA_VISIBLE_DEVICES, sehingga eksekusi sel tetap WAJIB di GPU. Kernel
mempertahankan state antar-sel (variabel tetap hidup) — seperti Google Colab.

Penjagaan server bersama:
  - GPU yang dipakai sesi di-RESERVE (lihat reservations.py) supaya job batch
    tidak memakai GPU yang sama.
  - Idle reaper mematikan kernel yang menganggur untuk membebaskan GPU.
  - Batas jumlah sesi serempak & batas waktu eksekusi per-sel (anti runaway).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import os
import shutil
import sys
import time
import uuid
import zipfile
from pathlib import Path
from queue import Empty
from typing import Awaitable, Callable

from jupyter_client.manager import AsyncKernelManager
import psutil
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import archive as archive_svc
from app.services import gpu as gpu_svc
from app.services import quota as quota_svc
from app.services import repo as repo_svc
from app.services import reservations
from app.services import user_policy as user_policy_svc

logger = get_logger(__name__)

KERNEL_NAME = "computehub"

# --- File explorer (poin 3 zip & poin 4 github) -----------------------------
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "_pydeps", ".ipynb_checkpoints",
    ".venv", "venv", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
}
_SKIP_FILES = {"_upload.zip", "_git.log"}
_MAX_TREE_ENTRIES = 2000          # batas jumlah node pohon (anti membludak)
_MAX_TEXT_FILE_BYTES = 1_000_000  # 1 MB: batas baca file teks ke editor

# Pemetaan ekstensi -> bahasa Monaco (untuk highlight saat buka file).
_LANG_BY_EXT = {
    ".py": "python", ".ipynb": "json", ".json": "json", ".js": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".md": "markdown", ".txt": "plaintext", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "ini", ".cfg": "ini", ".ini": "ini", ".sh": "shell",
    ".html": "html", ".css": "css", ".csv": "plaintext", ".sql": "sql",
    ".c": "c", ".cpp": "cpp", ".h": "cpp", ".java": "java", ".go": "go",
    ".rs": "rust", ".r": "r", ".xml": "xml",
}

# Setup kernel setelah project dimuat: pindah CWD + masukkan ke sys.path supaya
# `import modul_lokal` dan path file relatif bekerja seperti di project sungguhan.
_SETUP_CODE = (
    "import os as _os, sys as _sys\n"
    "_os.chdir({path!r})\n"
    "_p = _os.getcwd()\n"
    "if _p not in _sys.path:\n"
    "    _sys.path.insert(0, _p)\n"
    "del _os, _sys, _p\n"
)


def _lang_for(name: str) -> str:
    return _LANG_BY_EXT.get(Path(name).suffix.lower(), "plaintext")


def _scrub(text: str, secret: str) -> str:
    """Hapus token rahasia dari teks (pertahanan berlapis sebelum dikirim/dilog)."""
    return text.replace(secret, "***") if secret else text


def _zip_dir_to_bytes(root: Path) -> bytes:
    """Zip seluruh isi `root` (lewati folder berat/derivatif) -> bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                if fn in _SKIP_FILES:
                    continue
                fp = Path(dirpath) / fn
                if fp.is_symlink():
                    continue
                try:
                    zf.write(fp, fp.relative_to(root).as_posix())
                except OSError:
                    continue
    return buf.getvalue()


async def _run_git(
    args: list[str], env: dict | None = None, timeout: int = 120
) -> tuple[int, str]:
    """Jalankan git (TANPA shell), kembalikan (exit_code, output gabungan)."""
    git = shutil.which("git")
    if not git:
        return 127, "git tidak tersedia di server."
    proc = await asyncio.create_subprocess_exec(
        git, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, "Timeout menjalankan git."
    return (proc.returncode or 0), (out or b"").decode("utf-8", "replace")


# --- Catat sesi interaktif sebagai Job (muncul di Daftar Job + waktu GPU dihitung) ---
_SOURCE_MAP = {
    "paste": JobSource.paste,
    "notebook": JobSource.notebook,
    "zip": JobSource.upload,
    "github": JobSource.git,
}


async def _create_interactive_job(sess: "KernelSession") -> int | None:
    """Catat sesi sebagai Job status running (best-effort; gagal catat != gagal sesi)."""
    try:
        async with AsyncSessionLocal() as db:
            job = Job(
                name="Notebook interaktif",
                source_type=_SOURCE_MAP.get(sess.source, JobSource.paste),
                is_interactive=True,
                status=JobStatus.running,
                user_id=sess.user_id,
                gpu_index=sess.gpu_index,
                working_dir=str(sess.workdir),
                started_at=dt.datetime.now(dt.timezone.utc),
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return job.id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal mencatat job sesi interaktif: %s", exc)
        return None


async def _close_interactive_job(job_id: int) -> None:
    """Tandai Job sesi interaktif selesai + hitung runtime (best-effort)."""
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
                job.actual_runtime_seconds = max(0.0, (now - started).total_seconds())
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal menutup job sesi interaktif %s: %s", job_id, exc)


async def _check_role_limits(user_id: int) -> tuple[int, float, float]:
    """Tegakkan batas peran untuk sesi interaktif & kembalikan plafon resource.

    Sesi interaktif dihitung sebagai 1 job berjalan (lihat Part A), jadi batas
    konkurensi & kuota GPU harian ditegakkan juga di sini. Super admin BEBAS;
    admin biasa, dosen, mahasiswa dibatasi. RuntimeError -> 409 di router.

    Return: (cpu_threads, cap_ram_mb, cap_vram_mb) untuk diterapkan ke kernel.
    """
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or user.is_superadmin:
            return (0, 0.0, 0.0)
        running = await db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user_id, Job.status == JobStatus.running)
        )
        running = int(running or 0)
        # Policy efektif: override per-user -> default peran. Berlaku semua peran.
        eff = await user_policy_svc.effective(db, user_id)
        concurrency = eff.max_concurrent_jobs
        quota = eff.daily_gpu_seconds_quota
        cpu_threads = eff.max_cpu_threads
        cap_ram = eff.max_ram_mb
        cap_vram = eff.max_gpu_memory_mb
        if concurrency > 0 and running >= concurrency:
            raise RuntimeError(
                f"Batas job/sesi GPU paralel tercapai ({running}/{concurrency}). "
                "Tutup job atau sesi lain dulu."
            )
        if quota > 0:
            used = await quota_svc.gpu_seconds_used(db, user_id)
            if used >= quota:
                raise RuntimeError(
                    "Kuota GPU harian Anda sudah habis. Coba lagi nanti."
                )
        return (cpu_threads, cap_ram, cap_vram)


def _effective_root(base: Path) -> Path:
    """Bila isi `base` hanya satu folder (pola repo/zip umum), pakai folder itu
    sebagai root project agar CWD & file tree langsung pas."""
    try:
        entries = [e for e in base.iterdir() if e.name not in _SKIP_DIRS]
    except OSError:
        return base
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return base


def _build_tree(path: Path, root: Path, budget: list[int]) -> dict:
    node: dict = {
        "name": path.name or path.as_posix(),
        "path": "" if path == root else path.relative_to(root).as_posix(),
        "type": "dir",
        "children": [],
    }
    try:
        entries = sorted(
            path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
    except OSError:
        return node
    for child in entries:
        if budget[0] <= 0:
            break
        if child.name in _SKIP_DIRS or child.name in _SKIP_FILES:
            continue
        if child.is_symlink():
            continue
        budget[0] -= 1
        if child.is_dir():
            node["children"].append(_build_tree(child, root, budget))
        else:
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            node["children"].append({
                "name": child.name,
                "path": child.relative_to(root).as_posix(),
                "type": "file",
                "size": size,
            })
    return node
_ALLOWED_MIMES = (
    "text/plain",
    "text/html",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "image/svg+xml",
    "application/json",
)
_MAX_STREAM_CHARS = 200_000  # batasi 1 pesan output agar WS tidak kebanjiran

OnMsg = Callable[[dict], Awaitable[None]]


def _clean_data(data: dict) -> dict:
    out: dict = {}
    for mime in _ALLOWED_MIMES:
        if mime in data:
            val = data[mime]
            if isinstance(val, str) and len(val) > _MAX_STREAM_CHARS:
                val = val[:_MAX_STREAM_CHARS] + "\n…(dipotong)"
            out[mime] = val
    return out


def _kernel_env(gpu_index: int, cpu_threads: int = 0) -> dict[str, str]:
    """Environment kernel: GPU dipaksa + thread CPU dibatasi per peran."""
    env = os.environ.copy()
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    env["NVIDIA_VISIBLE_DEVICES"] = str(gpu_index)
    env["GPU_DEVICE_ORDINAL"] = str(gpu_index)
    threads = cpu_threads if cpu_threads and cpu_threads > 0 else settings.JOB_DEFAULT_CPU_THREADS
    threads = str(max(1, int(threads)))
    env["OMP_NUM_THREADS"] = threads
    env["MKL_NUM_THREADS"] = threads
    env["OPENBLAS_NUM_THREADS"] = threads
    env["NUMEXPR_NUM_THREADS"] = threads
    env["VECLIB_MAXIMUM_THREADS"] = threads
    env["PYTHONUNBUFFERED"] = "1"
    return env


class KernelSession:
    """Satu kernel IPython hidup, ter-pin ke satu GPU."""

    def __init__(self, user_id: int, gpu_index: int, source: str = "paste") -> None:
        self.id = uuid.uuid4().hex
        self.user_id = user_id
        self.gpu_index = gpu_index
        self.source = source
        self.job_id: int | None = None
        # Plafon resource peran (diisi manager.create; 0 = tanpa batas).
        self.cpu_threads = 0
        self.cap_ram_mb = 0.0
        self.cap_vram_mb = 0.0
        self.created_at = time.time()
        self.last_active = time.time()
        self.busy = False
        self.exec_count = 0
        self._km: AsyncKernelManager | None = None
        self._kc = None
        self._lock = asyncio.Lock()
        self._workdir = (settings.jobs_path / "_interactive" / self.id)
        self._root: Path | None = None  # root project (zip/github) bila ada
        self._git_url: str | None = None  # URL repo bila sesi dari GitHub

    # ----------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._workdir.mkdir(parents=True, exist_ok=True)
        self._km = AsyncKernelManager(kernel_name=KERNEL_NAME)
        await self._km.start_kernel(
            env=_kernel_env(self.gpu_index, self.cpu_threads), cwd=str(self._workdir)
        )
        self._kc = self._km.client()
        self._kc.start_channels()
        await self._kc.wait_for_ready(
            timeout=settings.INTERACTIVE_STARTUP_TIMEOUT_SECONDS
        )
        logger.info(
            "Kernel interaktif %s siap (user=%s, GPU=%s).",
            self.id, self.user_id, self.gpu_index,
        )

    async def shutdown(self) -> None:
        try:
            if self._kc is not None:
                self._kc.stop_channels()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._km is not None:
                await self._km.shutdown_kernel(now=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal shutdown kernel %s: %s", self.id, exc)
        finally:
            reservations.release(self.gpu_index)
            logger.info("Kernel interaktif %s dimatikan (GPU %s bebas).", self.id, self.gpu_index)

    async def interrupt(self) -> None:
        if self._km is not None:
            await self._km.interrupt_kernel()

    async def restart(self) -> None:
        async with self._lock:
            if self._km is not None:
                await self._km.restart_kernel(now=True)
                await self._kc.wait_for_ready(
                    timeout=settings.INTERACTIVE_STARTUP_TIMEOUT_SECONDS
                )
                self.exec_count = 0
                self.last_active = time.time()

    @property
    def is_alive(self) -> bool:
        return self._km is not None

    def _kernel_pid(self) -> int | None:
        km = self._km
        if km is None:
            return None
        prov = getattr(km, "provisioner", None)
        proc = getattr(prov, "process", None) if prov is not None else None
        pid = getattr(proc, "pid", None)
        if not pid:
            kern = getattr(km, "kernel", None)
            pid = getattr(kern, "pid", None)
        try:
            return int(pid) if pid else None
        except (TypeError, ValueError):
            return None

    def resource_breach(self) -> str | None:
        """Alasan bila sesi melewati plafon RAM/VRAM peran (None = aman)."""
        if self.cap_ram_mb <= 0 and self.cap_vram_mb <= 0:
            return None
        pid = self._kernel_pid()
        if not pid:
            return None
        try:
            p = psutil.Process(pid)
            pids = {pr.pid for pr in [p, *p.children(recursive=True)] if pr.is_running()}
        except psutil.Error:
            return None
        if not pids:
            return None
        if self.cap_ram_mb > 0:
            ram = 0
            for q in pids:
                try:
                    ram += psutil.Process(q).memory_info().rss
                except psutil.Error:
                    continue
            ram_mb = ram / (1024 * 1024)
            if ram_mb > self.cap_ram_mb:
                return f"RAM {ram_mb:.0f} MB melebihi plafon {self.cap_ram_mb:.0f} MB"
        if self.cap_vram_mb > 0:
            vram = gpu_svc.gpu_process_memory_mb(self.gpu_index, pids)
            if vram > self.cap_vram_mb:
                return f"VRAM {vram:.0f} MB melebihi plafon {self.cap_vram_mb:.0f} MB"
        return None

    def info(self) -> dict:
        return {
            "session_id": self.id,
            "gpu_index": self.gpu_index,
            "busy": self.busy,
            "execution_count": self.exec_count,
            "idle_seconds": round(time.time() - self.last_active, 1),
        }

    # ----------------------------------------------------------- project files
    @property
    def workdir(self) -> Path:
        return self._workdir

    @property
    def root(self) -> Path:
        return self._root or self._workdir

    async def run_setup(self, code: str) -> None:
        """Jalankan kode setup TANPA menambah exec_count / menampilkan output
        (silent + store_history=False). Dipakai untuk chdir + sys.path saat
        project (zip/github) selesai dimuat."""
        kc = self._kc
        if kc is None:
            return
        async with self._lock:
            msg_id = kc.execute(
                code, allow_stdin=False, store_history=False, silent=True
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    msg = await kc.get_iopub_msg(timeout=1.0)
                except (Empty, asyncio.TimeoutError):
                    continue
                if msg.get("parent_header", {}).get("msg_id") != msg_id:
                    continue
                if (
                    msg["header"]["msg_type"] == "status"
                    and msg["content"].get("execution_state") == "idle"
                ):
                    break
            try:
                while True:
                    reply = await kc.get_shell_msg(timeout=0.5)
                    if reply.get("parent_header", {}).get("msg_id") == msg_id:
                        break
            except (Empty, asyncio.TimeoutError):
                pass

    async def load_zip(self, data: bytes) -> dict:
        """Ekstrak project (.zip) ke workdir lalu pindahkan CWD kernel ke sana."""
        limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(data) > limit:
            raise ValueError(f"Arsip melebihi {settings.MAX_UPLOAD_SIZE_MB} MB.")
        proj = self._workdir / "project"
        if proj.exists():
            shutil.rmtree(proj, ignore_errors=True)
        proj.mkdir(parents=True, exist_ok=True)
        tmp = self._workdir / "_upload.zip"
        tmp.write_bytes(data)
        log = io.BytesIO()
        ok = await asyncio.to_thread(archive_svc.safe_extract, tmp, proj, log)
        tmp.unlink(missing_ok=True)
        if not ok:
            msg = log.getvalue().decode("utf-8", "replace").strip()
            raise ValueError(msg or "Gagal mengekstrak ZIP.")
        self._root = _effective_root(proj)
        await self.run_setup(_SETUP_CODE.format(path=str(self._root)))
        self.last_active = time.time()
        return self.file_tree()

    async def load_git(self, url: str, ref: str | None) -> dict:
        """Clone repo GitHub ke workdir lalu pindahkan CWD kernel ke repo."""
        err = repo_svc.validate_repo_url(url) or repo_svc.validate_ref(ref)
        if err:
            raise ValueError(err)
        dest = self._workdir / "repo"
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        log_path = self._workdir / "_git.log"
        with open(log_path, "wb") as logf:
            ok = await repo_svc.clone_repo(
                url=url, ref=(ref or None), dest=dest, log=logf
            )
        if not ok:
            tail = ""
            try:
                lines = log_path.read_text("utf-8", "replace").strip().splitlines()
                tail = lines[-1] if lines else ""
            except Exception:  # noqa: BLE001
                pass
            raise ValueError(tail or "Gagal clone repo.")
        self._root = dest
        self._git_url = url
        await self.run_setup(_SETUP_CODE.format(path=str(dest)))
        self.last_active = time.time()
        return self.file_tree()

    def file_tree(self) -> dict:
        root = self.root
        if not root.exists():
            return {"name": "project", "path": "", "type": "dir", "children": []}
        tree = _build_tree(root, root, [_MAX_TREE_ENTRIES])
        if not tree.get("name"):
            tree["name"] = "project"
        return tree

    def read_text_file(self, rel: str) -> dict:
        """Baca file teks DI DALAM root project (anti path traversal, batas ukuran)."""
        root = self.root.resolve()
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            raise ValueError("Path di luar project.")
        if not target.is_file():
            raise FileNotFoundError("File tidak ditemukan.")
        size = target.stat().st_size
        raw = target.read_bytes()[: _MAX_TEXT_FILE_BYTES + 1]
        truncated = size > _MAX_TEXT_FILE_BYTES
        raw = raw[:_MAX_TEXT_FILE_BYTES]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("File biner — tidak bisa ditampilkan di editor.")
        return {
            "path": rel,
            "content": text,
            "language": _lang_for(target.name),
            "truncated": truncated,
        }

    @property
    def is_git(self) -> bool:
        return bool(self._git_url and self._root and (self._root / ".git").is_dir())

    async def zip_project(self) -> tuple[str, bytes]:
        """Zip seluruh project (untuk diunduh)."""
        root = self.root
        if not root.exists():
            raise FileNotFoundError("Belum ada project untuk diunduh.")
        data = await asyncio.to_thread(_zip_dir_to_bytes, root)
        name = f"{root.name or 'project'}.zip"
        return name, data

    async def git_push(
        self, message: str, token: str, author_name: str, author_email: str
    ) -> dict:
        """Commit semua perubahan & push ke origin (khusus sesi GitHub).

        Token DIKIRIM via ENV (credential helper), TIDAK pernah masuk argv/log.
        """
        root = self._root
        if not self.is_git:
            raise ValueError("Sesi ini bukan dari GitHub repo, tidak bisa push.")
        if not (token or "").strip():
            raise ValueError("Token GitHub kosong.")
        assert root is not None
        msg = (message or "").strip() or "Update from ComputeHub"

        code, branch = await _run_git(["-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch.strip()
        if code != 0 or not branch or branch == "HEAD":
            raise ValueError(
                "Repo dalam keadaan detached HEAD (clone via commit/tag) — tak bisa push."
            )

        await _run_git(["-C", str(root), "add", "-A"])
        name = (author_name or "ComputeHub").replace("\n", " ")[:80]
        email = (author_email or "computehub@local").replace("\n", " ")[:120]
        code, out = await _run_git([
            "-C", str(root),
            "-c", f"user.name={name}",
            "-c", f"user.email={email}",
            "commit", "-m", msg,
        ])
        nothing = "nothing to commit" in out.lower()
        if code != 0 and not nothing:
            raise ValueError("Gagal commit: " + out.strip()[-300:])

        # Token via env -> tidak tampil di `ps`/log. Reset helper global dulu.
        helper = '!f() { echo username=x-access-token; echo "password=$CH_GIT_TOKEN"; }; f'
        env = {**os.environ, "CH_GIT_TOKEN": token, "GIT_TERMINAL_PROMPT": "0"}
        code, out = await _run_git(
            [
                "-C", str(root),
                "-c", "credential.helper=",
                "-c", f"credential.helper={helper}",
                "push", "origin", branch,
            ],
            env=env,
            timeout=settings.GIT_CLONE_TIMEOUT_SECONDS,
        )
        clean = _scrub(out, token).strip()
        if code != 0:
            raise ValueError("Gagal push: " + (clean[-300:] or "lihat akses/token."))
        self.last_active = time.time()
        return {
            "branch": branch,
            "committed": not nothing,
            "detail": clean[-300:] or "Push berhasil.",
        }

    # ----------------------------------------------------------- execute
    async def execute(self, code: str, on_msg: OnMsg) -> dict:
        """Jalankan satu sel; streaming output via on_msg(...) (awaitable)."""
        max_seconds = max(5, settings.INTERACTIVE_MAX_EXEC_SECONDS)
        async with self._lock:
            self.busy = True
            self.last_active = time.time()
            kc = self._kc
            status = "ok"
            try:
                msg_id = kc.execute(code, allow_stdin=False, store_history=True)
                deadline = time.monotonic() + max_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        await self.interrupt()
                        await on_msg({
                            "type": "error",
                            "ename": "TimeoutError",
                            "evalue": f"Eksekusi melebihi {max_seconds}s — dihentikan.",
                            "traceback": [],
                        })
                        status = "error"
                        break
                    try:
                        msg = await kc.get_iopub_msg(timeout=min(remaining, 1.0))
                    except (Empty, asyncio.TimeoutError):
                        continue
                    if msg.get("parent_header", {}).get("msg_id") != msg_id:
                        continue
                    mtype = msg["header"]["msg_type"]
                    content = msg["content"]
                    if mtype == "status":
                        if content.get("execution_state") == "idle":
                            break
                    elif mtype == "stream":
                        text = content.get("text", "")
                        if len(text) > _MAX_STREAM_CHARS:
                            text = text[:_MAX_STREAM_CHARS] + "\n…(dipotong)"
                        await on_msg({
                            "type": "stream",
                            "name": content.get("name", "stdout"),
                            "text": text,
                        })
                    elif mtype in ("execute_result", "display_data"):
                        await on_msg({
                            "type": "result",
                            "data": _clean_data(content.get("data", {})),
                            "execution_count": content.get("execution_count"),
                        })
                    elif mtype == "execute_input":
                        self.exec_count = content.get("execution_count", self.exec_count)
                    elif mtype == "error":
                        status = "error"
                        await on_msg({
                            "type": "error",
                            "ename": content.get("ename", ""),
                            "evalue": content.get("evalue", ""),
                            "traceback": content.get("traceback", []),
                        })
                # ambil balasan shell (status final) tanpa menggantung lama
                try:
                    while True:
                        reply = await kc.get_shell_msg(timeout=0.5)
                        if reply.get("parent_header", {}).get("msg_id") == msg_id:
                            self.exec_count = reply["content"].get(
                                "execution_count", self.exec_count
                            )
                            break
                except (Empty, asyncio.TimeoutError):
                    pass
            finally:
                self.busy = False
                self.last_active = time.time()
            return {"status": status, "execution_count": self.exec_count}


class KernelSessionManager:
    """Mengelola seluruh sesi interaktif + reaper idle."""

    def __init__(self) -> None:
        self._sessions: dict[str, KernelSession] = {}
        self._reaper: asyncio.Task | None = None
        self._spec_ready = False
        self._create_lock = asyncio.Lock()

    def _ensure_kernelspec(self) -> None:
        if self._spec_ready:
            return
        base = Path("_jkernel").resolve()
        kdir = base / "kernels" / KERNEL_NAME
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "kernel.json").write_text(
            json.dumps({
                "argv": [
                    sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}",
                ],
                "display_name": "ComputeHub",
                "language": "python",
            }),
            encoding="utf-8",
        )
        os.environ["JUPYTER_PATH"] = str(base) + os.pathsep + os.environ.get("JUPYTER_PATH", "")
        self._spec_ready = True

    async def start(self) -> None:
        self._ensure_kernelspec()
        self._reaper = asyncio.create_task(self._reap_loop(), name="kernel-reaper")
        logger.info(
            "KernelSessionManager siap (maks %d sesi, idle timeout %ds).",
            settings.INTERACTIVE_MAX_SESSIONS,
            settings.INTERACTIVE_IDLE_TIMEOUT_SECONDS,
        )

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reaper = None
        for sess in list(self._sessions.values()):
            await self._drop(sess)

    @property
    def reserved_gpus(self) -> set[int]:
        return {s.gpu_index for s in self._sessions.values()}

    def get(self, session_id: str, user_id: int) -> KernelSession | None:
        sess = self._sessions.get(session_id)
        if sess is not None and sess.user_id == user_id:
            return sess
        return None

    def list_for(self, user_id: int) -> list[dict]:
        return [s.info() for s in self._sessions.values() if s.user_id == user_id]

    def list_all(self) -> list[dict]:
        """Semua sesi aktif (untuk monitoring admin)."""
        out: list[dict] = []
        for s in self._sessions.values():
            info = s.info()
            info["user_id"] = s.user_id
            info["created_at"] = s.created_at
            info["has_project"] = s._root is not None
            out.append(info)
        return out

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    async def create(self, user_id: int, source: str = "paste") -> KernelSession:
        if not settings.INTERACTIVE_ENABLED:
            raise RuntimeError("Sesi interaktif dinonaktifkan.")
        async with self._create_lock:
            # Pakai ulang sesi milik user bila masih hidup (1 kernel per user).
            for sess in self._sessions.values():
                if sess.user_id == user_id and sess.is_alive:
                    sess.last_active = time.time()
                    return sess
            cpu_threads, cap_ram_mb, cap_vram_mb = await _check_role_limits(user_id)
            if len(self._sessions) >= settings.INTERACTIVE_MAX_SESSIONS:
                raise RuntimeError(
                    "Semua slot sesi interaktif sedang dipakai. Coba lagi sebentar lagi."
                )
            busy = reservations.reserved_indices()
            try:
                from app.services.scheduler import scheduler

                busy = busy | set(scheduler.busy_gpus)
            except Exception:  # noqa: BLE001
                pass
            gpu_index = gpu_svc.pick_free_gpu(
                min_free_mb=settings.GPU_MIN_FREE_MEMORY_MB, busy_indices=busy
            )
            if gpu_index is None:
                raise RuntimeError(
                    "Tidak ada GPU bebas untuk sesi interaktif (semua sedang dipakai)."
                )
            reservations.reserve(gpu_index)
            sess = KernelSession(user_id=user_id, gpu_index=gpu_index, source=source)
            sess.cpu_threads = cpu_threads
            sess.cap_ram_mb = cap_ram_mb
            sess.cap_vram_mb = cap_vram_mb
            try:
                await sess.start()
            except Exception:
                # start() bisa gagal SETELAH kernel spawn (mis. wait_for_ready
                # timeout). shutdown() membersihkan proses kernel + melepas reservasi
                # GPU -> cegah kernel yatim & GPU bocor.
                await sess.shutdown()
                raise
            self._sessions[sess.id] = sess
            sess.job_id = await _create_interactive_job(sess)
            return sess

    async def shutdown_session(self, session_id: str, user_id: int) -> bool:
        sess = self.get(session_id, user_id)
        if sess is None:
            return False
        await self._drop(sess)
        return True

    async def _drop(self, sess: KernelSession) -> None:
        self._sessions.pop(sess.id, None)
        if sess.job_id is not None:
            await _close_interactive_job(sess.job_id)
        try:
            await sess.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal menutup sesi %s: %s", sess.id, exc)

    async def shutdown_by_job_id(self, job_id: int) -> bool:
        """Hentikan sesi yang terkait Job tertentu (dipakai saat job di-cancel)."""
        for sess in list(self._sessions.values()):
            if sess.job_id == job_id:
                await self._drop(sess)
                return True
        return False

    async def _reap_loop(self) -> None:
        # Cek pelanggaran RAM/VRAM sering (samakan dengan sampler job batch) supaya
        # sesi boros resource cepat dihentikan; idle reaper pakai timeout terpisah.
        interval = max(1.0, float(settings.JOB_SAMPLE_INTERVAL_SECONDS))
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            timeout = settings.INTERACTIVE_IDLE_TIMEOUT_SECONDS
            now = time.time()
            for sess in list(self._sessions.values()):
                if timeout > 0 and not sess.busy and (now - sess.last_active) > timeout:
                    logger.info("Sesi %s idle > %ds -> dimatikan.", sess.id, timeout)
                    await self._drop(sess)
                    continue
                try:
                    reason = sess.resource_breach()
                except Exception:  # noqa: BLE001
                    reason = None
                if reason:
                    logger.warning(
                        "Sesi %s dihentikan otomatis: %s", sess.id, reason
                    )
                    await self._drop(sess)


# Instance global (dipakai lifespan & router).
kernel_manager = KernelSessionManager()
