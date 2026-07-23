"""Runtime eksekusi job: 'unshare' (sandbox host, DEFAULT) atau 'docker' (container).

Mode 'docker' menjalankan command job di CONTAINER EFEMERAL per-job (ch-job-<id>) dari
image ch-compute (Python+torch). working_dir job di-bind ke /work, jadi container HANYA
melihat folder job-nya sendiri (+ isi image) — bukan host, .env, atau job/user lain
(isolasi penuh antar-mahasiswa). Cancel/timeout BERSIH: `docker rm -f ch-job-<id>`.

KEAMANAN: hanya membuat/menghapus container bernama PERSIS ch-job-<id>; pakai
`settings.DOCKER_CMD` (sudo passwordless yang sudah ada) tanpa mengubah setelan sistem.
Default 'unshare' -> perilaku lama TIDAK berubah sampai diaktifkan eksplisit.
"""

from __future__ import annotations

import os
import shlex
import sys

from app.core.config import settings
from app.models.job import JobDevice
from app.services import provision


def runtime() -> str:
    return (settings.JOB_RUNTIME or "unshare").strip().lower()


def use_docker() -> bool:
    """True bila job harus dijalankan di container (butuh akses docker = provision aktif)."""
    return runtime() == "docker" and provision.is_enabled()


def job_container_name(job_id: int) -> str:
    return f"ch-job-{int(job_id)}"


async def cleanup_orphan_job_containers() -> None:
    """Hapus container job YATIM (ch-job-*) sisa crash/restart backend sebelumnya.

    Container job efemeral pakai `--rm` (auto-hapus saat keluar normal), tetapi bila
    proses backend CRASH di tengah job, container bisa tetap hidup di daemon dan menahan
    VRAM/CPU. Saat startup kita bersihkan by-name PERSIS pola milik kita (ch-job-*) —
    TIDAK pernah menyentuh container pengguna lain. Best-effort & no-op bila docker mati.
    """
    import asyncio

    if not provision.is_enabled():
        return
    cmd = settings.DOCKER_CMD.split()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, "ps", "-aq", "--filter", "name=ch-job-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(
            proc.communicate(), timeout=settings.DOCKER_CMD_TIMEOUT_SECONDS
        )
        ids = [x for x in (out or b"").decode(errors="replace").split() if x]
        if ids:
            rm = await asyncio.create_subprocess_exec(
                *cmd, "rm", "-f", *ids,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(rm.wait(), timeout=settings.DOCKER_CMD_TIMEOUT_SECONDS)
            from app.core.logging import get_logger

            get_logger(__name__).info(
                "Bersihkan %d container job yatim (ch-job-*).", len(ids)
            )
    except Exception:  # noqa: BLE001 — best-effort, jangan gagalkan startup
        pass


def _translate(command: str) -> str:
    """Ganti referensi interpreter Python HOST (sys.executable) -> 'python' container."""
    py = sys.executable
    return command.replace(shlex.quote(py), "python").replace(py, "python")


def _container_cwd(working_dir: str, run_cwd: str) -> str:
    """Path cwd di dalam container (working_dir di-mount ke /work)."""
    rel = os.path.relpath(run_cwd, working_dir)
    if rel in (".", ""):
        return "/work"
    return "/work/" + rel.replace(os.sep, "/")


def _build_inner(
    working_dir: str,
    run_cwd: str,
    command: str,
    *,
    device: JobDevice,
    auto_pip: bool,
    preflight_script: str | None,
    use_shared: bool = True,
) -> str:
    """Skrip `sh -c` di dalam container: preflight GPU -> cd -> pip opsional -> exec job."""
    cwd = _container_cwd(working_dir, run_cwd)
    lines: list[str] = []
    if preflight_script and device is JobDevice.gpu:
        lines.append(f"python -c {shlex.quote(preflight_script)} || exit $?")
    lines.append(f"cd {shlex.quote(cwd)} || exit 1")
    # Overlay library BERSAMA di PYTHONPATH (/opt/ch-shared) — HANYA image Python
    # default (paket cp310; merusak 3.11+). requirements.txt user (bila ada)
    # dipasang ke ./_pydeps & DIPRIORITASKAN.
    shared_part = "/opt/ch-shared:" if use_shared else ""
    if auto_pip:
        lines.append(
            "if [ -f requirements.txt ]; then "
            "python -m pip install --no-input --disable-pip-version-check "
            "--target ./_pydeps -r requirements.txt || exit 1; "
            f'export PYTHONPATH="./_pydeps:{shared_part}${{PYTHONPATH:-}}"; '
            f'else export PYTHONPATH="{shared_part}${{PYTHONPATH:-}}"; fi'
        )
    elif use_shared:
        lines.append('export PYTHONPATH="/opt/ch-shared:${PYTHONPATH:-}"')
    lines.append(f"exec {_translate(command)}")
    return "\n".join(lines)


def docker_run_argv(
    *,
    job_id: int,
    working_dir: str,
    run_cwd: str,
    command: str,
    gpu_index: int,
    device: JobDevice,
    cpu_threads: int = 0,
    memory_mb: float = 0.0,
    owner_id: int | None = None,
    auto_pip: bool = False,
    preflight_script: str | None = None,
    env_extra: dict[str, str] | None = None,
    python_version: str | None = None,
) -> list[str]:
    """argv `docker run --rm` untuk menjalankan job di container efemeral terisolasi."""
    name = job_container_name(job_id)
    args = [
        *settings.DOCKER_CMD.split(),
        "run",
        "--rm",
        "--name",
        name,
        *provision.hardening_argv(),
        "-v",
        f"{working_dir}:/work",
        "-w",
        "/work",
    ]
    # Workspace PERSISTEN per-user (ala "Drive" Colab): file & pip --user tetap antar-job,
    # tetap terisolasi (hanya volume user ini). HOME=/persist -> ~/.local & ~/.cache persist.
    if owner_id is not None:
        persist = settings.docker_user_data_root / str(int(owner_id))
        try:
            persist.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        args += ["-v", f"{persist}:/persist", "-e", "HOME=/persist"]
    # Overlay library BERSAMA (publik, read-only) -> semua job dapat library umum tanpa
    # perlu install. HANYA utk image Python default (isinya paket cp310 — merusak 3.11+).
    # Library milik user (requirements.txt/pip) TETAP per-user & menang.
    use_shared = settings.is_default_python(python_version)
    shared = settings.shared_pydeps_path
    if use_shared and shared.exists():
        args += ["-v", f"{shared}:/opt/ch-shared:ro"]
    # Model pre-trained bersama (read-only) — SEMUA versi Python (file model, bukan paket
    # pip): user pakai path /opt/ch-models tanpa download ulang (hemat bandwidth & kuota).
    models = settings.shared_models_path
    if models.exists():
        args += ["-v", f"{models}:/opt/ch-models:ro", "-e", "CH_SHARED_MODELS=/opt/ch-models"]
    # Batas RAM/CPU per-job sesuai kebijakan peran/user. memory_mb=0 -> TANPA batas
    # (kebijakan 0=unlimited, mis. super admin). docker --memory = hard limit (OOM-kill).
    if memory_mb and memory_mb > 0:
        if settings.SOFT_LIMIT_ENABLED:
            # Mode LUNAK: soft target (reservation = cap) + plafon KERAS tinggi -> job
            # MELAR melewati cap (tak OOM-kill di cap), hanya dibatasi plafon keras utk
            # jaga node. MULT<=0 -> tanpa plafon keras (murni soft, risiko node).
            args += ["--memory-reservation", f"{int(memory_mb)}m"]
            mult = float(settings.SOFT_LIMIT_RAM_HARD_MULT)
            if mult > 0:
                args += ["--memory", f"{int(memory_mb * mult)}m"]
        else:
            args += ["--memory", f"{int(memory_mb)}m"]
    cpus = (
        str(cpu_threads)
        if cpu_threads and cpu_threads > 0
        else settings.DOCKER_USER_CPUS
    )
    if cpus:
        args += ["--cpus", cpus]
    if settings.DOCKER_USER_PIDS_LIMIT > 0:
        args += ["--pids-limit", str(settings.DOCKER_USER_PIDS_LIMIT)]
    if device is JobDevice.gpu:
        if settings.DOCKER_GPU_MODE == "legacy":
            args += ["--runtime", "nvidia", "-e", f"NVIDIA_VISIBLE_DEVICES={gpu_index}"]
        else:
            args += ["--gpus", f"device={gpu_index}"]

    threads = str(max(1, cpu_threads or settings.JOB_DEFAULT_CPU_THREADS))
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        args += ["-e", f"{key}={threads}"]
    args += ["-e", "PYTHONUNBUFFERED=1"]
    if device is JobDevice.cpu:
        args += ["-e", "CUDA_VISIBLE_DEVICES=", "-e", "NVIDIA_VISIBLE_DEVICES="]
    for key, val in (env_extra or {}).items():
        if val is not None:
            args += ["-e", f"{key}={val}"]

    inner = _build_inner(
        working_dir,
        run_cwd,
        command,
        device=device,
        auto_pip=auto_pip,
        preflight_script=preflight_script,
        use_shared=use_shared,
    )
    args += [settings.image_for_python(python_version), "sh", "-c", inner]
    return args
