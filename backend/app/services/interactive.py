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
from dataclasses import dataclass
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
from app.services import sandbox
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
    "_jkernel",
}
# Berkas artefak sistem (bukan milik user) -> disembunyikan dari explorer project.
_SKIP_FILES = {"_upload.zip", "_git.log", "_run_notebook.py"}
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


async def _check_role_limits(user_id: int) -> tuple[int, float, float, bool]:
    """Tegakkan batas peran untuk sesi interaktif & kembalikan plafon resource.

    Sesi interaktif dihitung sebagai 1 job berjalan (lihat Part A), jadi batas
    konkurensi & kuota GPU harian ditegakkan juga di sini. Super admin BEBAS;
    admin biasa, dosen, mahasiswa dibatasi. RuntimeError -> 409 di router.

    Return: (cpu_threads, cap_ram_mb, cap_vram_mb, is_superadmin).
    """
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or user.is_superadmin:
            return (0, 0.0, 0.0, True)
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
        # Kuota disk /persist penuh -> tolak sesi baru (agar tak makin penuh).
        from app.services import storage_guard  # lazy: hindari import melingkar

        # Mode LUNAK: JANGAN tolak sesi baru (user minta tak dihentikan) -> biar jalan.
        if not settings.SOFT_LIMIT_ENABLED and storage_guard.is_over_quota(user_id):
            raise RuntimeError(
                "Kuota penyimpanan (/persist) Anda penuh. Hapus file di menu "
                "Penyimpanan dulu, lalu coba lagi."
            )
        return (cpu_threads, cap_ram, cap_vram, False)


class SessionQueued(Exception):
    """Tak ada kapasitas GPU sekarang -> user masuk antrian (auto-mulai nanti).

    Membawa info posisi & perkiraan tunggu agar router bisa membalas 202.
    """

    def __init__(self, ticket_id: str, position: int, eta_seconds: float | None) -> None:
        self.ticket_id = ticket_id
        self.position = position
        self.eta_seconds = eta_seconds
        super().__init__("Antrian sesi interaktif.")


@dataclass
class _Ticket:
    """Tiket antrian sesi interaktif (1 per user yang menunggu giliran)."""

    ticket_id: str
    user_id: int
    source: str
    budget_mb: float
    created_at: float
    last_seen: float
    granted_at: float | None = None  # waktu diberi giliran (None = masih menunggu)
    gpu_index: int | None = None     # GPU yang ditahankan saat giliran tiba


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
# Batas jumlah pesan output yang di-BUFFER per sel berjalan (untuk replay saat user
# kembali dari menu lain). Cukup besar utk progress bar panjang, tetap hemat memori.
_MAX_BUFFER_MSGS = 1200
# Batas total karakter SATU pesan stream yang digabung di buffer (progress bar / log
# training panjang) -> jaga memori tapi cukup besar utk replay banyak epoch saat reconnect.
_MAX_BUFFER_STREAM_CHARS = 1_000_000


def _apply_cr(s: str) -> str:
    """Terapkan carriage-return (\\r) ala terminal: teks setelah \\r menimpa dari awal
    baris -> progress bar (tqdm) jadi SATU baris yang berubah, bukan ribuan baris.

    PENTING: \\r di UJUNG string DIPERTAHANKAN. Pola `print(..., end="\\r")` menaruh
    CR di akhir tiap chunk; tanpa ini CR ekor hilang saat digabung -> chunk berikut
    TERSAMBUNG bukannya MENIMPA."""
    if "\r" not in s:
        return s
    tail_cr = s.endswith("\r")
    out: list[str] = []
    for line in s.split("\n"):
        if "\r" not in line:
            out.append(line)
            continue
        buf = ""
        col = 0
        for ch in line:
            if ch == "\r":
                col = 0
            else:
                buf = buf[:col] + ch + buf[col + 1:]
                col += 1
        out.append(buf)
    res = "\n".join(out)
    return res + "\r" if tail_cr else res


OnMsg = Callable[[dict], Awaitable[None]]

# MIME yang berupa TEKS -> boleh dipotong bila kelewat panjang (jaga WS tetap ringan).
# Gambar (base64/SVG) TIDAK termasuk: memotongnya membuat data rusak & gagal tampil.
_TEXT_MIMES = ("text/plain", "text/html", "text/markdown", "application/json")
# Batas ukuran gambar/SVG yang dikirim (base64). ~9 MB. Di atas ini kita TIDAK mengirim
# data terpotong (yang pasti rusak) melainkan catatan teks agar user tahu.
_MAX_IMAGE_CHARS = 12_000_000


def _clean_data(data: dict) -> dict:
    out: dict = {}
    for mime in _ALLOWED_MIMES:
        if mime not in data:
            continue
        val = data[mime]
        if mime in _TEXT_MIMES:
            if isinstance(val, str) and len(val) > _MAX_STREAM_CHARS:
                val = val[:_MAX_STREAM_CHARS] + "\n…(dipotong)"
            out[mime] = val
            continue
        # Gambar (image/png, image/jpeg, image/svg+xml): JANGAN dipotong.
        if isinstance(val, list):  # kernel kadang mengirim base64 sbg list baris
            val = "".join(str(x) for x in val)
        if isinstance(val, str) and mime in ("image/png", "image/jpeg"):
            val = "".join(val.split())  # rapatkan base64 (buang newline/spasi)
        if isinstance(val, str) and len(val) > _MAX_IMAGE_CHARS:
            out["text/plain"] = (
                f"[{mime} ~{len(val) // 1024} KB terlalu besar untuk ditampilkan]"
            )
            continue
        out[mime] = val
    return out


def _interactive_use_docker() -> bool:
    """True bila kernel interaktif harus jalan di container (butuh akses docker)."""
    from app.services import provision  # lazy: hindari siklus impor

    return (
        (settings.INTERACTIVE_RUNTIME or "unshare").strip().lower() == "docker"
        and provision.is_enabled()
    )


def _write_docker_launcher(base: Path) -> str:
    """Tulis skrip launcher kernel di container ch-compute; return path.

    Kernel jalan DI DALAM container (isolasi): mount connection-file & workdir di path
    sama. GPU di-pin + batas RAM/CPU per-sesi (via env CH_K_*). Pakai DOCKER_CMD.

    Jaringan (settings.INTERACTIVE_KERNEL_NET):
      - "bridge" (default, TERISOLASI): kernel bind 0.0.0.0 di DALAM container, 5 port
        ZMQ di-publish HANYA ke 127.0.0.1 host -> klien (jupyter_client) tetap terhubung,
        TAPI kode mahasiswa TIDAK bisa menjangkau layanan localhost server bersama
        (backend 8088, Postgres/MinIO orang lain, dll). Internet (pip) tetap via NAT.
        Bila parsing port gagal -> fallback aman ke --network host (kernel tetap hidup).
      - "host": --network host (lama; kernel berbagi namespace jaringan host).
    """
    docker_cmd = settings.DOCKER_CMD
    image = settings.DOCKER_USER_IMAGE
    pids = settings.DOCKER_USER_PIDS_LIMIT
    py = sys.executable  # python host untuk baca/ubah connection-file (JSON)
    from app.services import provision  # lazy: hindari siklus impor
    harden = " ".join(provision.hardening_argv())  # --cap-drop/no-new-priv/--user (non-root)
    bridge = (settings.INTERACTIVE_KERNEL_NET or "bridge").strip().lower() != "host"
    # Perintah python host (tanpa kutip tunggal -> aman dibungkus '...' di shell).
    _ports_py = (
        "import json,sys; d=json.load(open(sys.argv[1])); "
        'print(" ".join(str(d[k]) for k in '
        '("shell_port","iopub_port","stdin_port","control_port","hb_port")))'
    )
    _bind_py = (
        "import json,sys; d=json.load(open(sys.argv[1])); "
        'd["ip"]="0.0.0.0"; json.dump(d, open(sys.argv[2],"w"))'
    )
    # Cara request GPU ke `docker run` kernel: "gpus" (--gpus device=<idx>, default) atau
    # "legacy" (--runtime nvidia -e NVIDIA_VISIBLE_DEVICES=<idx>; bypass CDI basi).
    if (settings.DOCKER_GPU_MODE or "gpus").strip().lower() == "legacy":
        gpu_line = (
            '[ -n "$CUDA_VISIBLE_DEVICES" ] && '
            'GPUARG="--runtime nvidia -e NVIDIA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"\n'
        )
    else:
        gpu_line = '[ -n "$CUDA_VISIBLE_DEVICES" ] && GPUARG="--gpus device=$CUDA_VISIBLE_DEVICES"\n'
    head = (
        "#!/bin/sh\n"
        "# Launcher kernel interaktif ComputeHub di DALAM container (isolasi penuh).\n"
        'CONN="$1"\n'
        'CONNDIR=$(dirname "$CONN")\n'
        'CONNRUN="$CONN"\n'
        # Image per-sesi (pilihan versi Python) via env; fallback image default.
        f'IMG="${{CH_K_IMAGE:-{image}}}"\n'
        'GPUARG=""\n'
        + gpu_line +
        'MEMARG=""\n'
        'if [ -n "$CH_K_MEM" ] && [ "$CH_K_MEM" -gt 0 ] 2>/dev/null; then MEMARG="--memory ${CH_K_MEM}m"; fi\n'
        'if [ -n "$CH_K_MEM_RES" ] && [ "$CH_K_MEM_RES" -gt 0 ] 2>/dev/null; then MEMARG="--memory-reservation ${CH_K_MEM_RES}m $MEMARG"; fi\n'
        'CPUARG=""\n'
        '[ -n "$CH_K_CPUS" ] && CPUARG="--cpus $CH_K_CPUS"\n'
        'NAMEARG=""\n'
        '[ -n "$CH_K_NAME" ] && NAMEARG="--name $CH_K_NAME"\n'
        'PERSISTARG=""\n'
        '[ -n "$CH_K_PERSIST" ] && PERSISTARG="-v $CH_K_PERSIST:/persist -e HOME=/persist"\n'
        'SHAREDARG=""\n'
        '[ -n "$CH_K_SHARED" ] && SHAREDARG="-v $CH_K_SHARED:/opt/ch-shared:ro -e PYTHONPATH=/opt/ch-shared"\n'
        'MODELSARG=""\n'
        '[ -n "$CH_K_MODELS" ] && MODELSARG="-v $CH_K_MODELS:/opt/ch-models:ro -e CH_SHARED_MODELS=/opt/ch-models"\n'
    )
    if bridge:
        netblock = (
            "# Isolasi jaringan (bridge): publish 5 port ZMQ ke 127.0.0.1; kernel bind 0.0.0.0.\n"
            "# Fallback aman ke --network host bila parsing port gagal (kernel tetap hidup).\n"
            'NETARG="--network host"\n'
            f"""PORTS=$("{py}" -c '{_ports_py}' "$CONN" 2>/dev/null)\n"""
            'if [ -n "$PORTS" ]; then\n'
            '  PUBLISH=""\n'
            '  for p in $PORTS; do PUBLISH="$PUBLISH -p 127.0.0.1:$p:$p"; done\n'
            f"""  if "{py}" -c '{_bind_py}' "$CONN" "$CONN.bind" 2>/dev/null; then\n"""
            '    NETARG="$PUBLISH"; CONNRUN="$CONN.bind"\n'
            "  fi\n"
            "fi\n"
        )
    else:
        netblock = 'NETARG="--network host"\n'
    tail = (
        f'exec {docker_cmd} run --rm $NAMEARG $PERSISTARG $SHAREDARG $MODELSARG $NETARG {harden} $GPUARG $MEMARG $CPUARG --pids-limit {pids} \\\n'
        '  -e OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}" -e MKL_NUM_THREADS="${MKL_NUM_THREADS:-2}" \\\n'
        '  -e OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-2}" -e PYTHONUNBUFFERED=1 \\\n'
        '  -v "$CONNDIR":"$CONNDIR" -v "$PWD":/work -w /work \\\n'
        '  "$IMG" python -m ipykernel_launcher -f "$CONNRUN"\n'
    )
    path = base / "launch_kernel_docker.sh"
    path.write_text(head + netblock + tail, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


async def _docker_rm_kernel(session_id: str) -> None:
    """Hapus paksa container kernel (ch-kernel-<id>) bila masih hidup. Best-effort."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *settings.DOCKER_CMD.split(), "rm", "-f", f"ch-kernel-{session_id}",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=settings.DOCKER_CMD_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001
        pass


async def _cleanup_orphan_kernels() -> None:
    """Hapus container kernel YATIM (ch-kernel-*) sisa proses sebelumnya (by-name milik kita)."""
    cmd = settings.DOCKER_CMD.split()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, "ps", "-aq", "--filter", "name=ch-kernel-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(
            proc.communicate(), timeout=settings.DOCKER_CMD_TIMEOUT_SECONDS
        )
        ids = [x for x in (out or b"").decode().split() if x]
        if ids:
            rm = await asyncio.create_subprocess_exec(
                *cmd, "rm", "-f", *ids,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(rm.wait(), timeout=settings.DOCKER_CMD_TIMEOUT_SECONDS)
            logger.info("Bersihkan %d container kernel yatim (ch-kernel-*).", len(ids))
    except Exception as exc:  # noqa: BLE001
        logger.debug("cleanup orphan kernels error: %s", exc)


def _kernel_env(
    gpu_index: int, cpu_threads: int = 0, cap_ram_mb: float = 0.0, container_name: str = "", persist_dir: str = "", image: str = "", use_shared: bool = True
) -> dict[str, str]:
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
    # Runtime docker interaktif: teruskan batas per-sesi & nama container ke launcher.
    env["CH_K_CPUS"] = threads
    if cap_ram_mb and cap_ram_mb > 0:
        if settings.SOFT_LIMIT_ENABLED:
            # Mode LUNAK: soft target (reservation=cap) + plafon KERAS (cap*mult) -> kernel
            # MELAR melewati cap tanpa OOM-kill; hanya dibatasi plafon keras utk jaga node.
            env["CH_K_MEM_RES"] = str(int(cap_ram_mb))
            mult = float(settings.SOFT_LIMIT_RAM_HARD_MULT)
            env["CH_K_MEM"] = str(int(cap_ram_mb * mult)) if mult > 0 else ""
        else:
            env["CH_K_MEM"] = str(int(cap_ram_mb))
    if container_name:
        env["CH_K_NAME"] = container_name
    if persist_dir:
        env["CH_K_PERSIST"] = persist_dir
    if image:
        env["CH_K_IMAGE"] = image
    # Overlay shared_pydeps HANYA utk image Python default (paket cp310; merusak 3.11+).
    shared = settings.shared_pydeps_path
    if use_shared and shared.exists():
        env["CH_K_SHARED"] = str(shared)
    # Model pre-trained bersama (read-only) — SEMUA versi Python (file model, bukan paket).
    models = settings.shared_models_path
    if models.exists():
        env["CH_K_MODELS"] = str(models)
    return env


class KernelSession:
    """Satu kernel IPython hidup, ter-pin ke satu GPU."""

    def __init__(
        self,
        user_id: int,
        gpu_index: int,
        source: str = "paste",
        python_version: str | None = None,
    ) -> None:
        self.id = uuid.uuid4().hex
        self.user_id = user_id
        self.gpu_index = gpu_index
        self.source = source
        # Versi Python pilihan user (mode docker) -> menentukan image kernel.
        self.python_version = python_version
        self.job_id: int | None = None
        # Plafon resource peran (diisi manager.create; 0 = tanpa batas).
        self.cpu_threads = 0
        self.cap_ram_mb = 0.0
        self.cap_vram_mb = 0.0
        # Anggaran VRAM (dipesan di registry untuk GPU-sharing) + ukuran nyata terakhir.
        self.budget_vram_mb = 0.0
        self.last_ram_mb = 0.0
        self.last_vram_mb = 0.0
        self.created_at = time.time()
        self.last_active = time.time()
        self.busy = False
        self.exec_count = 0
        # --- Eksekusi MILIK SESI (bertahan lintas koneksi WS) + buffer output utk
        # replay saat user kembali. Pindah menu -> WS putus TIDAK menghentikan kode;
        # output ditumpuk di _buffer lalu diputar ulang saat WS terhubung lagi. ---
        self._sink: OnMsg | None = None        # tujuan output WS aktif (None = terputus)
        self._exec_task: asyncio.Task | None = None
        self._run_cell_id: str | None = None   # sel yang sedang berjalan
        self._buffer: list[dict] = []          # log output sel berjalan (untuk replay)
        self._folder_bytes = 0                 # akumulasi ukuran upload FOLDER (chunked)
        self._folder_max = 0                   # batas ukuran upload folder (sisa kuota disk)
        self._km: AsyncKernelManager | None = None
        self._kc = None
        self._lock = asyncio.Lock()
        self._workdir = (settings.jobs_path / "_interactive" / self.id)
        self._root: Path | None = None  # root project (zip/github) bila ada
        self._git_url: str | None = None  # URL repo bila sesi dari GitHub

    # ----------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._workdir.mkdir(parents=True, exist_ok=True)
        persist = ""
        if _interactive_use_docker():
            pdir = settings.docker_user_data_root / str(self.user_id)
            try:
                pdir.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
            persist = str(pdir)
        self._km = AsyncKernelManager(kernel_name=KERNEL_NAME)
        await self._km.start_kernel(
            env=_kernel_env(
                self.gpu_index, self.cpu_threads, self.cap_ram_mb,
                f"ch-kernel-{self.id}", persist,
                settings.image_for_python(self.python_version),
                use_shared=settings.is_default_python(self.python_version),
            ),
            cwd=str(self._workdir),
            preexec_fn=None if _interactive_use_docker() else sandbox.apply_rlimits,
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
            reservations.release(self.id)
            if _interactive_use_docker():
                await _docker_rm_kernel(self.id)  # jaga-jaga bila container masih hidup
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

    def observe(self) -> str | None:
        """Ukur RAM/VRAM kernel SEKARANG, simpan (untuk tampilan + registry),
        kembalikan alasan bila melewati plafon peran (None = aman).

        Dipanggil reaper tiap ~JOB_SAMPLE_INTERVAL. Inilah cara sistem "membaca"
        berapa banyak resource yang benar-benar dipakai tiap sesi.
        """
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
        ram = 0
        for q in pids:
            try:
                ram += psutil.Process(q).memory_info().rss
            except psutil.Error:
                continue
        ram_mb = ram / (1024 * 1024)
        vram_mb = gpu_svc.gpu_process_memory_mb(self.gpu_index, pids)
        self.last_ram_mb = ram_mb
        self.last_vram_mb = vram_mb
        # Mode LUNAK: JANGAN jatuhkan sesi karena RAM/VRAM (user minta melar/melambat,
        # bukan dihentikan). Plafon keras RAM (docker) tetap jaga node; VRAM ke CUDA.
        if settings.SOFT_LIMIT_ENABLED:
            return None
        if self.cap_ram_mb > 0 and ram_mb > self.cap_ram_mb:
            return f"RAM {ram_mb:.0f} MB melebihi plafon {self.cap_ram_mb:.0f} MB"
        if self.cap_vram_mb > 0 and vram_mb > self.cap_vram_mb:
            return f"VRAM {vram_mb:.0f} MB melebihi plafon {self.cap_vram_mb:.0f} MB"
        return None

    def _expires_in(self, now: float | None = None) -> float | None:
        """Detik tersisa sebelum sesi dihentikan otomatis (umur maks / idle).

        None bila tak ada batas. Dipakai utk tampilan 'sisa waktu' & estimasi
        kapan slot interaktif kosong.
        """
        now = now if now is not None else time.time()
        deadlines: list[float] = []
        life = settings.INTERACTIVE_MAX_SESSION_SECONDS
        if life > 0:
            deadlines.append(self.created_at + life)
        idle = settings.INTERACTIVE_IDLE_TIMEOUT_SECONDS
        if idle > 0 and not self.busy:
            deadlines.append(self.last_active + idle)
        if not deadlines:
            return None
        return max(0.0, round(min(deadlines) - now, 1))

    def info(self) -> dict:
        now = time.time()
        return {
            "session_id": self.id,
            "gpu_index": self.gpu_index,
            "python_version": self.python_version or settings.DOCKER_PYTHON_DEFAULT,
            "busy": self.busy,
            "execution_count": self.exec_count,
            "idle_seconds": round(now - self.last_active, 1),
            "age_seconds": round(now - self.created_at, 1),
            "expires_in_seconds": self._expires_in(now),
            "vram_used_mb": round(self.last_vram_mb, 1),
            "vram_budget_mb": round(self.budget_vram_mb, 1),
            "ram_used_mb": round(self.last_ram_mb, 1),
        }

    # ----------------------------------------------------------- project files
    @property
    def workdir(self) -> Path:
        return self._workdir

    @property
    def root(self) -> Path:
        return self._root or self._workdir

    def _kernel_cwd(self) -> str:
        """Path CWD kernel yang BENAR untuk chdir. Di mode DOCKER, _workdir di-mount ke
        /work di dalam container -> CWD = /work/<rel> (BUKAN path host yang TAK ADA di
        container; kalau host, chdir GAGAL & file/output nyasar ke luar project). Mode
        non-docker (host): pakai path host langsung.
        """
        root = self._root or self._workdir
        if _interactive_use_docker():
            try:
                rel = root.relative_to(self._workdir).as_posix()
            except ValueError:
                return "/work"
            return "/work" if rel in ("", ".") else f"/work/{rel}"
        return str(root)

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
        await self.run_setup(_SETUP_CODE.format(path=self._kernel_cwd()))
        self.last_active = time.time()
        return self.file_tree()

    @staticmethod
    def _safe_rel(path: str) -> str | None:
        """webkitRelativePath 'root/sub/f' -> rel AMAN 'sub/f' (buang segmen root).
        None bila entri berbahaya (absolut / '..')."""
        norm = (path or "").replace("\\", "/").strip().lstrip("/")
        parts = [seg for seg in norm.split("/") if seg not in ("", ".")]
        if not parts or any(seg == ".." for seg in parts):
            return None
        return "/".join(parts[1:]) if len(parts) > 1 else parts[0]

    async def folder_chunk(
        self, path: str, first: bool, reset: bool, data: bytes, max_bytes: int
    ) -> None:
        """Tulis SATU potongan file folder ke workdir/project (upload chunked).

        reset=1 pada awal upload -> hapus project lama. first=1 pada awal FILE -> tulis
        baru ('wb'), selain itu tambah ('ab'). Batas = sisa kuota disk user.
        """
        proj = (self._workdir / "project").resolve()
        if reset:
            if proj.exists():
                shutil.rmtree(proj, ignore_errors=True)
            proj.mkdir(parents=True, exist_ok=True)
            self._folder_bytes = 0
            self._folder_max = max_bytes
        rel = self._safe_rel(path)
        if rel is None:
            raise ValueError("Path folder tidak aman.")
        target = (proj / rel).resolve()
        if target != proj and not str(target).startswith(str(proj) + os.sep):
            raise ValueError("Path folder tidak aman.")
        self._folder_bytes += len(data)
        if self._folder_max > 0 and self._folder_bytes > self._folder_max:
            raise ValueError("Folder melebihi sisa kuota penyimpanan Anda.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb" if first else "ab") as out:
            out.write(data)
        self.last_active = time.time()

    async def folder_finalize(self) -> dict:
        """Selesaikan upload FOLDER: pindahkan CWD kernel ke project + kembalikan tree."""
        proj = self._workdir / "project"
        if not proj.exists() or not any(proj.rglob("*")):
            raise ValueError("Folder kosong.")
        self._root = _effective_root(proj)
        await self.run_setup(_SETUP_CODE.format(path=self._kernel_cwd()))
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
        await self.run_setup(_SETUP_CODE.format(path=self._kernel_cwd()))
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

    def open_raw_file(self, rel: str) -> Path:
        """Path file DI DALAM root project (anti-traversal) untuk disajikan mentah
        (mis. gambar). Beda dari read_text_file: tak decode -> file biner pun boleh."""
        target = self._resolve_in_root(rel)
        if not target.is_file():
            raise FileNotFoundError("File tidak ditemukan.")
        return target

    def _resolve_in_root(self, rel: str) -> Path:
        """Resolusi path relatif DI DALAM root project (anti path traversal)."""
        root = self.root.resolve()
        target = (root / (rel or "").lstrip("/")).resolve()
        if target != root and root not in target.parents:
            raise ValueError("Path di luar project.")
        return target

    def write_text_file(self, rel: str, content: str) -> dict:
        """Tulis/buat file teks di dalam root project -> kembalikan tree terbaru."""
        target = self._resolve_in_root(rel)
        if target == self.root.resolve():
            raise ValueError("Nama file tidak valid.")
        if target.is_dir():
            raise ValueError("Path adalah folder, bukan file.")
        if len((content or "").encode("utf-8")) > _MAX_TEXT_FILE_BYTES:
            raise ValueError("Isi file terlalu besar.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
        self.last_active = time.time()
        return self.file_tree()

    def make_dir(self, rel: str) -> dict:
        """Buat folder baru di dalam root project."""
        target = self._resolve_in_root(rel)
        if target == self.root.resolve():
            raise ValueError("Nama folder tidak valid.")
        if target.exists():
            raise ValueError("Nama sudah dipakai.")
        target.mkdir(parents=True, exist_ok=True)
        self.last_active = time.time()
        return self.file_tree()

    def rename_path(self, rel: str, new_rel: str) -> dict:
        """Ganti nama / pindah file atau folder di dalam root project."""
        src = self._resolve_in_root(rel)
        dst = self._resolve_in_root(new_rel)
        root = self.root.resolve()
        if src == root or dst == root:
            raise ValueError("Tidak bisa mengganti nama root project.")
        if not src.exists():
            raise FileNotFoundError("Item tidak ditemukan.")
        if dst.exists():
            raise ValueError("Nama tujuan sudah dipakai.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        self.last_active = time.time()
        return self.file_tree()

    def delete_path(self, rel: str) -> dict:
        """Hapus file atau folder di dalam root project."""
        target = self._resolve_in_root(rel)
        if target == self.root.resolve():
            raise ValueError("Tidak bisa menghapus root project.")
        if not target.exists():
            raise FileNotFoundError("Item tidak ditemukan.")
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
        self.last_active = time.time()
        return self.file_tree()

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

    # ------------------------------------------- eksekusi milik sesi + buffer replay
    async def _emit(self, msg: dict) -> None:
        """Simpan output ke buffer (untuk replay) + teruskan ke WS aktif bila ada."""
        # Gabung stream BERUNTUN (mis. progress bar tqdm dgn \r) menjadi SATU pesan yang
        # terus di-update -> buffer tak membengkak oleh ribuan baris & replay tetap
        # ringkas (tanpa pesan "sebagian output lama tak tersimpan").
        merged = False
        if msg.get("type") == "stream" and self._buffer:
            last = self._buffer[-1]
            if (
                last.get("type") == "stream"
                and last.get("name") == msg.get("name")
                and last.get("cell_id") == msg.get("cell_id")
            ):
                text = _apply_cr((last.get("text") or "") + (msg.get("text") or ""))
                if len(text) > _MAX_BUFFER_STREAM_CHARS:
                    text = text[-_MAX_BUFFER_STREAM_CHARS:]
                last["text"] = text
                merged = True
        if not merged:
            if len(self._buffer) < _MAX_BUFFER_MSGS:
                self._buffer.append(msg)
            elif len(self._buffer) == _MAX_BUFFER_MSGS:
                self._buffer.append({
                    "type": "stream", "name": "stdout",
                    "text": "\n…(sebagian output lama tak tersimpan untuk replay)\n",
                    "cell_id": self._run_cell_id,
                })
        sink = self._sink
        if sink is not None:
            try:
                await sink(msg)
            except Exception:  # noqa: BLE001
                pass  # WS tertutup di tengah kirim -> abaikan; output tetap di buffer

    def attach_sink(self, on_msg: OnMsg) -> tuple[str | None, list[dict]]:
        """Pasang WS sbg tujuan output; kembalikan (cell_berjalan, buffer) untuk replay.

        Dipanggil saat WS (re)connect -> router memutar ulang buffer agar tampilan sel
        yang sedang/baru berjalan (mis. progress bar) tersinkron kembali.
        """
        self._sink = on_msg
        running = (
            self._run_cell_id
            if self._exec_task is not None and not self._exec_task.done()
            else None
        )
        return running, list(self._buffer)

    def detach_sink(self) -> None:
        """Lepas WS (user pindah menu / refresh). Eksekusi TETAP jalan (buffer diisi)."""
        self._sink = None

    async def start_execution(self, cell_id: str | None, code: str) -> bool:
        """Jalankan sel sebagai tugas MILIK SESI (tak terikat WS). False bila sibuk."""
        if self._exec_task is not None and not self._exec_task.done():
            return False
        self._run_cell_id = cell_id
        self._buffer = []

        async def _runner() -> None:
            await self._emit({"type": "status", "state": "busy", "cell_id": cell_id})

            async def on_msg(m: dict) -> None:
                await self._emit({**m, "cell_id": cell_id})

            try:
                result = await self.execute(code, on_msg)
                await self._emit({"type": "execute_reply", "cell_id": cell_id, **result})
            except Exception as exc:  # noqa: BLE001
                await self._emit({
                    "type": "error", "cell_id": cell_id,
                    "ename": type(exc).__name__, "evalue": str(exc), "traceback": [],
                })
            finally:
                await self._emit({"type": "status", "state": "idle", "cell_id": cell_id})
                self._run_cell_id = None
                # Buffer DIPERTAHANKAN (output sel terakhir) -> tetap bisa di-replay
                # bila user kembali sesudah sel selesai; dibersihkan saat sel berikut mulai.

        self._exec_task = asyncio.create_task(_runner())
        return True


class KernelSessionManager:
    """Mengelola seluruh sesi interaktif + reaper idle."""

    def __init__(self) -> None:
        self._sessions: dict[str, KernelSession] = {}
        self._queue: list[_Ticket] = []        # antrian FIFO sesi interaktif
        self._reaper: asyncio.Task | None = None
        self._spec_ready = False
        self._stopping = False
        self._create_lock = asyncio.Lock()

    def _ensure_kernelspec(self) -> None:
        if self._spec_ready:
            return
        base = Path("_jkernel").resolve()
        kdir = base / "kernels" / KERNEL_NAME
        kdir.mkdir(parents=True, exist_ok=True)
        if _interactive_use_docker():
            # Kernel jalan di container ch-compute (isolasi penuh; jaringan per INTERACTIVE_KERNEL_NET).
            argv = [_write_docker_launcher(base), "{connection_file}"]
        else:
            base_argv = [
                sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}",
            ]
            # Bungkus kernel dalam sandbox user-namespace (sembunyikan .env) bila tersedia.
            argv = (
                sandbox.wrap_kernel_argv(base_argv)
                if sandbox.sandbox_available()
                else base_argv
            )
        (kdir / "kernel.json").write_text(
            json.dumps({
                "argv": argv,
                "display_name": "ComputeHub",
                "language": "python",
            }),
            encoding="utf-8",
        )
        os.environ["JUPYTER_PATH"] = str(base) + os.pathsep + os.environ.get("JUPYTER_PATH", "")
        self._spec_ready = True

    async def start(self) -> None:
        self._ensure_kernelspec()
        if _interactive_use_docker():
            await _cleanup_orphan_kernels()
        self._reaper = asyncio.create_task(self._reap_loop(), name="kernel-reaper")
        logger.info(
            "KernelSessionManager siap (maks %d sesi, idle timeout %ds).",
            settings.INTERACTIVE_MAX_SESSIONS,
            settings.INTERACTIVE_IDLE_TIMEOUT_SECONDS,
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reaper = None
        # Lepas semua tahanan slot antrian + buang tiket.
        for t in self._queue:
            reservations.release(t.ticket_id)
        self._queue.clear()
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

    async def drop_user_sessions(self, user_id: int) -> int:
        """Hentikan SEMUA sesi milik user (akun dinonaktifkan/dihapus/logout)."""
        dropped = 0
        for sess in list(self._sessions.values()):
            if sess.user_id == user_id:
                await self._drop(sess)
                dropped += 1
        if dropped:
            logger.info(
                "Menghentikan %d sesi interaktif milik user #%d.", dropped, user_id
            )
        return dropped

    def earliest_free_eta(self) -> float | None:
        """Perkiraan detik sampai ada slot interaktif kosong (None bila tak tentu)."""
        etas = [
            e for e in (s._expires_in() for s in self._sessions.values()) if e is not None
        ]
        return min(etas) if etas else None

    # ---------------------------------------------------------------- antrian
    def _active_load(self) -> int:
        """Jumlah sesi hidup + tiket yang sedang menahan slot (giliran diberikan)."""
        granted = sum(1 for t in self._queue if t.granted_at is not None)
        return len(self._sessions) + granted

    def _try_place(self, budget_mb: float) -> int | None:
        """GPU yang bisa menampung sesi baru beranggaran `budget_mb`, atau None."""
        if self._active_load() >= settings.INTERACTIVE_MAX_SESSIONS:
            return None
        return gpu_svc.pick_gpu_for(budget_mb)

    def _ticket_for_user(self, user_id: int) -> _Ticket | None:
        for t in self._queue:
            if t.user_id == user_id:
                return t
        return None

    def _waiting_position(self, ticket: _Ticket) -> int:
        """Posisi 1-based di antara tiket yang masih menunggu (belum granted)."""
        waiting = [t for t in self._queue if t.granted_at is None]
        return (waiting.index(ticket) + 1) if ticket in waiting else 1

    def _ensure_ticket(self, user_id: int, source: str, budget_mb: float) -> _Ticket:
        """Ambil tiket user (perbarui) atau buat baru di ekor antrian."""
        t = self._ticket_for_user(user_id)
        now = time.time()
        if t is not None:
            t.last_seen = now
            t.source = source
            t.budget_mb = budget_mb
            return t
        t = _Ticket(
            ticket_id=uuid.uuid4().hex,
            user_id=user_id,
            source=source,
            budget_mb=budget_mb,
            created_at=now,
            last_seen=now,
        )
        self._queue.append(t)
        logger.info("Antrian: user #%d masuk antrian (tiket %s).", user_id, t.ticket_id)
        return t

    def _remove_ticket(self, ticket: _Ticket) -> None:
        reservations.release(ticket.ticket_id)  # lepas tahanan slot (bila ada)
        try:
            self._queue.remove(ticket)
        except ValueError:
            pass

    def _drop_ticket(self, user_id: int) -> None:
        t = self._ticket_for_user(user_id)
        if t is not None:
            self._remove_ticket(t)

    def leave_queue(self, user_id: int) -> bool:
        """User keluar dari antrian (mis. menutup halaman)."""
        t = self._ticket_for_user(user_id)
        if t is None:
            return False
        self._remove_ticket(t)
        return True

    def queue_status(self, user_id: int) -> dict:
        """Status antrian user. Memperbarui last_seen (tanda masih menunggu)."""
        t = self._ticket_for_user(user_id)
        if t is None:
            return {"state": "none"}
        t.last_seen = time.time()
        if t.granted_at is not None:
            return {
                "state": "ready",
                "ticket_id": t.ticket_id,
                "position": 0,
                "eta_seconds": 0,
                "gpu_index": t.gpu_index,
            }
        return {
            "state": "queued",
            "ticket_id": t.ticket_id,
            "position": self._waiting_position(t),
            "waiting": sum(1 for x in self._queue if x.granted_at is None),
            "eta_seconds": self.earliest_free_eta(),
        }

    def _promote(self) -> None:
        """Beri giliran tiket terdepan selama masih ada kapasitas (FIFO).

        "Memberi giliran" = MENAHAN slot (reserve VRAM atas nama tiket) TANPA
        menyalakan kernel. Kernel baru menyala saat user meng-klaim (memanggil
        create dgn ticket_id) -> hemat GPU bila user sudah pergi.
        """
        if self._stopping:
            return
        for t in self._queue:
            if t.granted_at is not None:
                continue
            gpu = self._try_place(t.budget_mb)
            if gpu is None:
                break  # tak ada kapasitas -> jaga urutan, berhenti
            reservations.reserve(t.ticket_id, gpu, t.budget_mb, kind="interactive")
            t.gpu_index = gpu
            t.granted_at = time.time()
            logger.info("Antrian: tiket %s dapat giliran (GPU %s).", t.ticket_id, gpu)

    def _expire_tickets(self, now: float) -> None:
        """Buang tiket basi: giliran tak diklaim (TTL) / berhenti dipantau."""
        grant_ttl = settings.INTERACTIVE_GRANT_TTL_SECONDS
        queue_ttl = settings.INTERACTIVE_QUEUE_TTL_SECONDS
        stale: list[_Ticket] = []
        for t in self._queue:
            if t.granted_at is not None:
                if grant_ttl > 0 and (now - t.granted_at) > grant_ttl:
                    stale.append(t)
            elif queue_ttl > 0 and (now - t.last_seen) > queue_ttl:
                stale.append(t)
        for t in stale:
            logger.info("Antrian: tiket %s kedaluwarsa -> dibuang.", t.ticket_id)
            self._remove_ticket(t)

    async def create(
        self,
        user_id: int,
        source: str = "paste",
        ticket_id: str | None = None,
        python_version: str | None = None,
    ) -> KernelSession:
        if not settings.INTERACTIVE_ENABLED:
            raise RuntimeError("Sesi interaktif dinonaktifkan.")
        async with self._create_lock:
            # Pakai ulang sesi milik user bila masih hidup (1 kernel per user).
            for sess in self._sessions.values():
                if sess.user_id == user_id and sess.is_alive:
                    sess.last_active = time.time()
                    self._drop_ticket(user_id)
                    return sess

            cpu_threads, cap_ram_mb, cap_vram_mb, is_super = await _check_role_limits(user_id)

            # Anggaran VRAM utk GPU-sharing + plafon yang ditegakkan (auto-kill).
            # Saat sharing aktif, sesi non-super WAJIB punya plafon konkret supaya
            # satu sesi tak menyedot seluruh GPU (adil dibagi). Super admin bebas.
            if settings.GPU_SHARE_ENABLED:
                if is_super:
                    budget = settings.INTERACTIVE_DEFAULT_VRAM_MB
                    enforce_vram = 0.0
                else:
                    budget = cap_vram_mb if cap_vram_mb > 0 else settings.INTERACTIVE_DEFAULT_VRAM_MB
                    enforce_vram = budget
            else:
                budget = cap_vram_mb if cap_vram_mb > 0 else settings.INTERACTIVE_DEFAULT_VRAM_MB
                enforce_vram = cap_vram_mb  # perilaku lama (0 = tak di-kill)

            # Giliran dari antrian? (tiket sudah granted & GPU ditahan utk user ini)
            granted: _Ticket | None = None
            if ticket_id:
                cand = self._ticket_for_user(user_id)
                if cand is not None and cand.ticket_id == ticket_id and cand.granted_at is not None:
                    granted = cand

            if granted is not None and granted.gpu_index is not None:
                gpu_index: int | None = granted.gpu_index
            else:
                gpu_index = self._try_place(budget)

            if gpu_index is None:
                # Tak ada kapasitas -> masuk/menetap di antrian (auto-mulai nanti).
                t = self._ensure_ticket(user_id, source, budget)
                raise SessionQueued(
                    t.ticket_id, self._waiting_position(t), self.earliest_free_eta()
                )

            sess = KernelSession(
                user_id=user_id, gpu_index=gpu_index, source=source,
                python_version=python_version,
            )
            sess.cpu_threads = cpu_threads
            sess.cap_ram_mb = cap_ram_mb
            sess.cap_vram_mb = enforce_vram
            sess.budget_vram_mb = budget
            # Pesan slot atas nama sesi; pindahkan tahanan dari tiket bila dari giliran.
            reservations.reserve(sess.id, gpu_index, budget, kind="interactive")
            if granted is not None:
                self._remove_ticket(granted)
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
            self._drop_ticket(user_id)  # bersihkan sisa tiket walk-in bila ada
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
        # Kapasitas baru bebas -> beri giliran tiket antrian berikutnya.
        self._promote()

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
            life = settings.INTERACTIVE_MAX_SESSION_SECONDS
            now = time.time()
            for sess in list(self._sessions.values()):
                if life > 0 and (now - sess.created_at) > life:
                    logger.info(
                        "Sesi %s melebihi umur maks %ds -> dimatikan.", sess.id, life
                    )
                    await self._drop(sess)
                    continue
                if timeout > 0 and not sess.busy and (now - sess.last_active) > timeout:
                    logger.info("Sesi %s idle > %ds -> dimatikan.", sess.id, timeout)
                    await self._drop(sess)
                    continue
                # Ukur pemakaian nyata -> perbarui registry (utk sharing/tampilan)
                # + auto-stop bila melewati plafon.
                try:
                    reason = sess.observe()
                except Exception:  # noqa: BLE001
                    reason = None
                reservations.update_usage(sess.id, sess.last_vram_mb)
                if reason:
                    logger.warning(
                        "Sesi %s dihentikan otomatis: %s", sess.id, reason
                    )
                    await self._drop(sess)
            # Kelola antrian: buang tiket basi lalu beri giliran berikutnya.
            self._expire_tickets(now)
            self._promote()


# Instance global (dipakai lifespan & router).
kernel_manager = KernelSessionManager()
