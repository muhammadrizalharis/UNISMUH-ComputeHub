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
) -> str:
    """Skrip `sh -c` di dalam container: preflight GPU -> cd -> pip opsional -> exec job."""
    cwd = _container_cwd(working_dir, run_cwd)
    lines: list[str] = []
    if preflight_script and device is JobDevice.gpu:
        lines.append(f"python -c {shlex.quote(preflight_script)} || exit $?")
    lines.append(f"cd {shlex.quote(cwd)} || exit 1")
    if auto_pip:
        lines.append(
            "if [ -f requirements.txt ]; then "
            "python -m pip install --no-input --disable-pip-version-check "
            "--target ./_pydeps -r requirements.txt || exit 1; "
            'export PYTHONPATH="./_pydeps:${PYTHONPATH:-}"; fi'
        )
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
    auto_pip: bool = False,
    preflight_script: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> list[str]:
    """argv `docker run --rm` untuk menjalankan job di container efemeral terisolasi."""
    name = job_container_name(job_id)
    args = [
        *settings.DOCKER_CMD.split(),
        "run",
        "--rm",
        "--name",
        name,
        "-v",
        f"{working_dir}:/work",
        "-w",
        "/work",
    ]
    # Batas RAM/CPU per-job sesuai kebijakan peran/user. memory_mb=0 -> TANPA batas
    # (kebijakan 0=unlimited, mis. super admin). docker --memory = hard limit (OOM-kill).
    if memory_mb and memory_mb > 0:
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
    )
    args += [settings.DOCKER_USER_IMAGE, "sh", "-c", inner]
    return args
