"""Executor job: menjalankan command sebagai subprocess yang DIPAKSA ke GPU.

ATURAN KERAS (sesuai kebijakan server kampus):
  - Setiap job di-pin ke 1 GPU lewat CUDA_VISIBLE_DEVICES.
  - Sebelum command utama jalan, ada PREFLIGHT CUDA: kalau tidak ada GPU CUDA
    yang terlihat, job langsung GAGAL (exit 97). TIDAK ada fallback ke CPU.
  - Komputasi di CPU tidak diizinkan (server bersama).
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import os
import shlex
import signal
import sys
from pathlib import Path
from typing import Callable

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import get_logger
from app.models.job import JobDevice, JobSource, JobStatus
from app.services import archive as archive_svc
from app.services import cpu_pool
from app.services import jobruntime
from app.services import lint as lint_svc
from app.services import policy as policy_svc
from app.services import repo as repo_svc
from app.services import sandbox
from app.services import sources as sources_svc

logger = get_logger(__name__)

# Exit code khusus saat preflight GPU gagal.
PREFLIGHT_FAIL_CODE = 97
# Exit code khusus saat job melewati batas waktu (timeout).
TIMEOUT_CODE = 124

# Script preflight: pastikan minimal 1 GPU CUDA terlihat (dengan masking aktif).
_PREFLIGHT_SCRIPT = (
    "import os, sys\n"
    "try:\n"
    "    import torch\n"
    "    n = torch.cuda.device_count() if torch.cuda.is_available() else 0\n"
    "except Exception as e:\n"
    "    sys.stderr.write('[PREFLIGHT] gagal cek CUDA via torch: %r\\n' % (e,))\n"
    "    n = 0\n"
    "if n < 1:\n"
    "    sys.stderr.write('[PREFLIGHT] GAGAL: tidak ada GPU CUDA terlihat. "
    "Job DIBATALKAN (CPU tidak diizinkan).\\n')\n"
    "    sys.exit(97)\n"
    "sys.stderr.write('[PREFLIGHT] OK: %d GPU CUDA terlihat (CUDA_VISIBLE_DEVICES=%s)\\n' "
    "% (n, os.environ.get('CUDA_VISIBLE_DEVICES','')))\n"
)


def _short_path(path: str | Path, base: str | Path) -> str:
    """Path RELATIF terhadap folder kerja job (mis. 'project', 'repo', '.') supaya LOG
    tak membocorkan path ABSOLUT server (username & struktur folder = info sensitif)."""
    try:
        return os.path.relpath(str(path), str(base))
    except Exception:  # noqa: BLE001
        return Path(str(path)).name


def _safe_cmd(command: str) -> str:
    """Sembunyikan path absolut interpreter Python pada perintah -> tampil 'python' saja
    di log (eksekusi tetap memakai path asli). Cegah bocornya lokasi venv/server."""
    exe = sys.executable
    return command.replace(shlex.quote(exe), "python").replace(exe, "python")


@dataclasses.dataclass
class RunResult:
    status: JobStatus
    exit_code: int | None
    pid: int | None
    started_at: dt.datetime
    finished_at: dt.datetime
    error_message: str | None = None


def _build_env(
    gpu_index: int, cpu_threads: int = 0, device: JobDevice = JobDevice.gpu
) -> dict[str, str]:
    """Environment subprocess: GPU dipaksa (device gpu) / disembunyikan (device cpu)
    + footprint CPU dibatasi.

    `cpu_threads` = plafon thread komputasi peran (0 = pakai default sistem).
    """
    env = os.environ.copy()
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"

    if device is JobDevice.cpu:
        # --- Sembunyikan SEMUA GPU (komputasi murni CPU) ---
        env["CUDA_VISIBLE_DEVICES"] = ""
        env["NVIDIA_VISIBLE_DEVICES"] = ""
    else:
        # --- Paksa GPU spesifik ---
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
        env["NVIDIA_VISIBLE_DEVICES"] = str(gpu_index)
        env["GPU_DEVICE_ORDINAL"] = str(gpu_index)

    # --- Batasi jumlah thread CPU (server bersama) ---
    threads = cpu_threads if cpu_threads and cpu_threads > 0 else settings.JOB_DEFAULT_CPU_THREADS
    threads = str(max(1, int(threads)))
    env["OMP_NUM_THREADS"] = threads
    env["MKL_NUM_THREADS"] = threads
    env["OPENBLAS_NUM_THREADS"] = threads
    env["NUMEXPR_NUM_THREADS"] = threads
    env["VECLIB_MAXIMUM_THREADS"] = threads
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


class JobExecutor:
    """Menjalankan & mengelola subprocess job (mendukung cancel)."""

    def __init__(self) -> None:
        self._procs: dict[int, asyncio.subprocess.Process] = {}
        # job_id -> nama container docker (mode JOB_RUNTIME=docker) utk cancel bersih.
        self._docker_jobs: dict[int, str] = {}

    def is_running(self, job_id: int) -> bool:
        return job_id in self._procs

    async def _run_preflight(self, env: dict[str, str], log) -> bool:
        """True bila GPU CUDA terlihat. Output ditulis ke log."""
        try:
            import sys

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                _PREFLIGHT_SCRIPT,
                env=env,
                stdout=log,
                stderr=log,
            )
            code = await proc.wait()
            return code == 0
        except Exception as exc:  # noqa: BLE001
            log.write(f"[PREFLIGHT] error menjalankan preflight: {exc!r}\n".encode())
            log.flush()
            return False

    async def _pip_install(self, run_cwd: str, env: dict[str, str], log) -> bool:
        """Install requirements.txt ke ./_pydeps (terisolasi, tak mengotori env bersama)."""
        req = Path(run_cwd) / "requirements.txt"
        if not req.exists():
            return True  # tidak ada dependency -> lewati

        target = Path(run_cwd) / "_pydeps"
        log.write(
            b"[PIP] requirements.txt ditemukan -> install ke ./_pydeps "
            b"(terisolasi per job)...\n"
        )
        log.flush()
        pip_argv = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-input",
            "--disable-pip-version-check",
            "--target",
            str(target),
            "-r",
            str(req),
        ]
        # Sandbox pip juga: requirements.txt jahat bisa jalankan setup.py yg baca .env.
        if sandbox.sandbox_available():
            pip_argv = sandbox.wrap_exec_argv(pip_argv)
        try:
            proc = await asyncio.create_subprocess_exec(
                *pip_argv,
                cwd=run_cwd,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,  # grup proses sendiri -> killpg saat timeout
                preexec_fn=sandbox.apply_rlimits,
            )
        except Exception as exc:  # noqa: BLE001
            log.write(f"[PIP] Gagal start: {exc!r}\n".encode())
            log.flush()
            return False

        try:
            code = await asyncio.wait_for(
                proc.wait(), timeout=settings.PIP_INSTALL_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            log.write(b"[PIP] Timeout saat install.\n")
            log.flush()
            return False

        if code != 0:
            log.write(f"[PIP] Gagal (exit {code}).\n".encode())
            log.flush()
            return False

        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(target) + (os.pathsep + existing if existing else "")
        log.write(b"[PIP] Selesai. PYTHONPATH -> ./_pydeps\n" + b"-" * 60 + b"\n")
        log.flush()
        return True

    def _resolve_command(self, run_cwd: str, env: dict[str, str], log) -> str | None:
        """Tentukan perintah eksekusi otomatis dari isi folder."""
        py = sys.executable
        cmd = sources_svc.detect_entrypoint(Path(run_cwd), py)
        if cmd:
            return cmd
        nb = sources_svc.single_notebook(Path(run_cwd))
        if nb is not None:
            try:
                sources_svc.validate_notebook(nb)
            except ValueError as exc:
                # Notebook ketemu tapi RUSAK -> beri alasan jelas, lalu None.
                log.write(f"[SOURCE] {exc}\n".encode())
                log.flush()
                return None
            try:
                rel = nb.relative_to(Path(run_cwd))
            except ValueError:
                rel = Path(nb.name)
            # Jalankan SEBAGAI NOTEBOOK (nbclient): output tiap sel DISIMPAN kembali ke
            # berkas .ipynb-nya (in-place) supaya tampil DI BAWAH kode di tampilan
            # notebook, bukan cuma teks di log.
            sources_svc.write_notebook_runner(Path(run_cwd))
            env["CH_NB_IN"] = str(rel)
            env["CH_NB_OUT"] = str(rel)
            log.write(
                f"[SOURCE] notebook {rel} dijalankan sebagai NOTEBOOK "
                "(output tiap sel disimpan ke berkasnya)\n".encode()
            )
            log.flush()
            return f"{shlex.quote(py)} _run_notebook.py"
        return None

    async def run_job(
        self,
        *,
        job_id: int,
        command: str,
        working_dir: str,
        gpu_index: int,
        log_path: str,
        source_type: JobSource = JobSource.command,
        repo_url: str | None = None,
        repo_ref: str | None = None,
        time_limit_seconds: int | None = None,
        auto_install: bool = True,
        inline_code: str | None = None,
        cpu_threads: int = 0,
        max_ram_mb: float = 0.0,
        owner_id: int | None = None,
        device: JobDevice = JobDevice.gpu,
        python_version: str | None = None,
        cpu_affinity: list[int] | None = None,
        on_start: Callable[[int], None] | None = None,
    ) -> RunResult:
        """Jalankan satu job di GPU `gpu_index` (atau CPU). Blok sampai selesai."""
        started_at = dt.datetime.now(dt.timezone.utc)
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        env = _build_env(gpu_index, cpu_threads, device)
        env["CH_TIMEOUT"] = str(time_limit_seconds or 3600)
        run_cwd = working_dir

        with open(log_path, "ab", buffering=0) as log:
            header = (
                f"===== JOB #{job_id} =====\n"
                f"waktu_mulai : {started_at.isoformat()}\n"
                f"device      : {device.value}\n"
                f"gpu_index   : {gpu_index if device is JobDevice.gpu else '-'}\n"
                f"cpu_affinity: {cpu_affinity if cpu_affinity else '-'}\n"
                f"sumber      : {source_type.value}\n"
                f"batas_waktu : {time_limit_seconds or 'tanpa batas'} dtk\n"
                f"working_dir : {Path(working_dir).name}\n"
                f"command     : {_safe_cmd(command)}\n"
                f"CUDA_VISIBLE_DEVICES={env['CUDA_VISIBLE_DEVICES']!r}\n"
                f"{'-' * 60}\n"
            )
            log.write(header.encode())
            log.flush()

            # --- Clone repo Git bila perlu ---
            if source_type is JobSource.git:
                clone_dir = Path(working_dir) / "repo"
                ok = await repo_svc.clone_repo(
                    url=repo_url or "",
                    ref=repo_ref,
                    dest=clone_dir,
                    log=log,
                )
                if not ok:
                    finished_at = dt.datetime.now(dt.timezone.utc)
                    msg = "Gagal clone repo Git."
                    log.write(f"{'-' * 60}\n[EXECUTOR] {msg}\n".encode())
                    log.flush()
                    return RunResult(
                        status=JobStatus.failed,
                        exit_code=None,
                        pid=None,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_message=msg,
                    )
                run_cwd = str(clone_dir)
                log.write(
                    f"[EXECUTOR] repo siap di {_short_path(run_cwd, working_dir)}/"
                    f"\n{'-' * 60}\n".encode()
                )
                log.flush()

            # --- Project upload: FOLDER (disimpan langsung) atau ZIP (perlu ekstrak) ---
            elif source_type is JobSource.upload:
                archive = Path(working_dir) / "_upload.zip"
                project_dir = Path(working_dir) / "project"
                # Folder upload (baru): project/ sudah berisi file -> tak perlu ekstrak.
                if project_dir.is_dir() and any(project_dir.iterdir()):
                    log.write(b"[EXECUTOR] project folder siap (tanpa ekstrak).\n")
                    log.flush()
                elif archive.exists():
                    ok = archive_svc.safe_extract(archive, project_dir, log)
                    if not ok:
                        finished_at = dt.datetime.now(dt.timezone.utc)
                        msg = "Gagal mengekstrak project upload."
                        log.write(f"{'-' * 60}\n[EXECUTOR] {msg}\n".encode())
                        log.flush()
                        return RunResult(
                            status=JobStatus.failed,
                            exit_code=None,
                            pid=None,
                            started_at=started_at,
                            finished_at=finished_at,
                            error_message=msg,
                        )
                else:
                    finished_at = dt.datetime.now(dt.timezone.utc)
                    msg = "Berkas project upload tidak ditemukan."
                    log.write(f"{'-' * 60}\n[EXECUTOR] {msg}\n".encode())
                    log.flush()
                    return RunResult(
                        status=JobStatus.failed,
                        exit_code=None,
                        pid=None,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_message=msg,
                    )
                run_cwd = str(project_dir)
                log.write(
                    f"[EXECUTOR] project siap di {_short_path(run_cwd, working_dir)}/"
                    f"\n{'-' * 60}\n".encode()
                )
                log.flush()

            # --- Kode tempel (paste): tulis main.py ---
            elif source_type is JobSource.paste:
                sources_svc.write_main(Path(working_dir), inline_code or "")
                run_cwd = working_dir
                log.write(b"[EXECUTOR] kode tempel ditulis ke main.py\n")
                log.write(f"{'-' * 60}\n".encode())
                log.flush()

            # --- Notebook: eksekusi PENUH (nbclient) + simpan output ---
            elif source_type is JobSource.notebook:
                run_cwd = working_dir
                sources_svc.write_notebook_runner(Path(working_dir))
                command = f"{shlex.quote(sys.executable)} _run_notebook.py"
                env["CH_TIMEOUT"] = str(time_limit_seconds or 3600)
                log.write(
                    b"[EXECUTOR] notebook runner siap (eksekusi penuh + simpan output)\n"
                )
                log.write(f"{'-' * 60}\n".encode())
                log.flush()

            # --- Auto-install requirements.txt (git/upload) ---
            # Mode docker: pip dijalankan DI DALAM container (jobruntime), bukan di host.
            if (
                not jobruntime.use_docker()
                and source_type in (JobSource.git, JobSource.upload)
                and auto_install
                and policy_svc.get().auto_pip_install
            ):
                ok = await self._pip_install(run_cwd, env, log)
                if not ok:
                    finished_at = dt.datetime.now(dt.timezone.utc)
                    msg = "Gagal install requirements.txt."
                    log.write(f"[EXECUTOR] {msg}\n".encode())
                    log.flush()
                    return RunResult(
                        status=JobStatus.failed,
                        exit_code=None,
                        pid=None,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_message=msg,
                    )

            # --- Tentukan perintah OTOMATIS bila kosong ---
            if not command.strip():
                resolved = self._resolve_command(run_cwd, env, log)
                if resolved is None:
                    finished_at = dt.datetime.now(dt.timezone.utc)
                    msg = (
                        "Entrypoint tidak ditemukan. Sertakan main.py, satu file "
                        ".py, atau notebook .ipynb."
                    )
                    log.write(f"[EXECUTOR] {msg}\n".encode())
                    log.flush()
                    return RunResult(
                        status=JobStatus.failed,
                        exit_code=None,
                        pid=None,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_message=msg,
                    )
                command = resolved
                log.write(
                    f"[EXECUTOR] perintah otomatis: {_safe_cmd(command)}\n{'-' * 60}\n".encode()
                )
                log.flush()

            # --- PREFLIGHT LINT (analisis kode statik; peringatan saja, tak memblokir) ---
            # Penting untuk upload ZIP & GitHub repo yang tak punya editor 'error lens'.
            try:
                lint_block = await run_in_threadpool(
                    lint_svc.preflight_lint_text,
                    source_type=source_type.value,
                    command=command,
                    run_cwd=run_cwd,
                    working_dir=working_dir,
                )
                if lint_block:
                    log.write(lint_block.encode())
                    log.flush()
            except Exception as exc:  # noqa: BLE001  -- lint tak boleh menggagalkan job
                logger.debug("preflight lint error: %s", exc)

            # --- PREFLIGHT GPU (wajib utk device gpu; dilewati utk device cpu) ---
            # Mode docker: preflight dijalankan DI DALAM container (jobruntime).
            if (
                not jobruntime.use_docker()
                and settings.REQUIRE_CUDA_PREFLIGHT
                and device is JobDevice.gpu
            ):
                ok = await self._run_preflight(env, log)
                if not ok:
                    finished_at = dt.datetime.now(dt.timezone.utc)
                    msg = "Preflight GPU gagal: tidak ada GPU CUDA terlihat (CPU tidak diizinkan)."
                    log.write(f"{'-' * 60}\n[EXECUTOR] {msg}\n".encode())
                    log.flush()
                    return RunResult(
                        status=JobStatus.failed,
                        exit_code=PREFLIGHT_FAIL_CODE,
                        pid=None,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_message=msg,
                    )

            # --- Jalankan command utama ---
            try:
                if jobruntime.use_docker():
                    # Mode docker: container EFEMERAL per-job (ch-job-<id>), isolasi penuh.
                    name = jobruntime.job_container_name(job_id)
                    auto_pip_docker = (
                        source_type in (JobSource.git, JobSource.upload)
                        and auto_install
                        and policy_svc.get().auto_pip_install
                    )
                    # Teruskan SEMUA env CH_* (CH_TIMEOUT, CH_NB_IN, CH_NB_OUT, ...) ke
                    # container -> runner notebook menemukan berkas .ipynb yang BENAR
                    # (bukan default 'notebook.ipynb') & timeout aktif di mode docker.
                    env_extra = {k: v for k, v in env.items() if k.startswith("CH_")} or None
                    argv = jobruntime.docker_run_argv(
                        job_id=job_id,
                        working_dir=working_dir,
                        run_cwd=run_cwd,
                        command=command,
                        gpu_index=gpu_index,
                        device=device,
                        cpu_threads=cpu_threads,
                        memory_mb=max_ram_mb,
                        owner_id=owner_id,
                        auto_pip=auto_pip_docker,
                        preflight_script=_PREFLIGHT_SCRIPT,
                        env_extra=env_extra,
                        python_version=python_version,
                    )
                    self._docker_jobs[job_id] = name
                    log.write(
                        f"[EXECUTOR] runtime=docker container={name} "
                        f"image={settings.image_for_python(python_version)}\n".encode()
                    )
                    log.flush()
                    proc = await asyncio.create_subprocess_exec(
                        *argv,
                        cwd=working_dir,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                elif sandbox.sandbox_available():
                    proc = await asyncio.create_subprocess_exec(
                        *sandbox.wrap_shell_argv(command),
                        cwd=run_cwd,
                        env=env,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,  # grup proses sendiri -> mudah di-kill
                        preexec_fn=sandbox.apply_rlimits,  # batas resource (anti fork bomb dst)
                    )
                else:
                    proc = await asyncio.create_subprocess_shell(
                        command,
                        cwd=run_cwd,
                        env=env,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,  # grup proses sendiri -> mudah di-kill
                        preexec_fn=sandbox.apply_rlimits,  # batas resource (anti fork bomb dst)
                    )
            except Exception as exc:  # noqa: BLE001
                finished_at = dt.datetime.now(dt.timezone.utc)
                msg = f"Gagal start subprocess: {exc!r}"
                log.write(f"[EXECUTOR] {msg}\n".encode())
                log.flush()
                return RunResult(
                    status=JobStatus.failed,
                    exit_code=None,
                    pid=None,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_message=msg,
                )

            self._procs[job_id] = proc
            # Kunci affinity proses utama -> anak (joblib n_jobs) mewarisi mask.
            # (Mode docker: CPU dibatasi via --cpus container, pin host dilewati.)
            if cpu_affinity and not jobruntime.use_docker():
                cpu_pool.pin_process(proc.pid, cpu_affinity)
                log.write(
                    f"[EXECUTOR] cpu_affinity job dikunci ke core {cpu_affinity}\n".encode()
                )
                log.flush()
            if on_start is not None:
                try:
                    on_start(proc.pid)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("on_start callback error: %s", exc)
            try:
                if time_limit_seconds and time_limit_seconds > 0:
                    exit_code = await asyncio.wait_for(
                        proc.wait(), timeout=time_limit_seconds
                    )
                else:
                    exit_code = await proc.wait()
            except asyncio.TimeoutError:
                await self._terminate_job(job_id, proc)
                finished_at = dt.datetime.now(dt.timezone.utc)
                msg = (
                    f"Melebihi batas waktu {time_limit_seconds} dtk (timeout) "
                    f"-> job dihentikan."
                )
                log.write(f"\n[EXECUTOR] {msg}\n".encode())
                log.flush()
                return RunResult(
                    status=JobStatus.failed,
                    exit_code=TIMEOUT_CODE,
                    pid=proc.pid,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_message=msg,
                )
            except asyncio.CancelledError:
                await self._terminate_job(job_id, proc)
                finished_at = dt.datetime.now(dt.timezone.utc)
                log.write(f"\n[EXECUTOR] Job #{job_id} dibatalkan.\n".encode())
                log.flush()
                return RunResult(
                    status=JobStatus.cancelled,
                    exit_code=None,
                    pid=proc.pid,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_message="Job dibatalkan.",
                )
            finally:
                self._procs.pop(job_id, None)
                self._docker_jobs.pop(job_id, None)

            finished_at = dt.datetime.now(dt.timezone.utc)
            status = JobStatus.succeeded if exit_code == 0 else JobStatus.failed
            footer = (
                f"{'-' * 60}\n"
                f"[EXECUTOR] selesai status={status.value} exit_code={exit_code} "
                f"durasi={(finished_at - started_at).total_seconds():.1f}s\n"
            )
            log.write(footer.encode())
            log.flush()
            return RunResult(
                status=status,
                exit_code=exit_code,
                pid=proc.pid,
                started_at=started_at,
                finished_at=finished_at,
                error_message=None if status is JobStatus.succeeded else f"exit code {exit_code}",
            )

    async def cancel(self, job_id: int) -> bool:
        """Batalkan job yang sedang berjalan. True bila prosesnya ditemukan."""
        proc = self._procs.get(job_id)
        if proc is None:
            return False
        await self._terminate_job(job_id, proc)
        return True

    async def _terminate_job(
        self, job_id: int, proc: asyncio.subprocess.Process
    ) -> None:
        """Hentikan job. Mode docker: hapus container (mematikan semua proses di dalamnya)."""
        name = self._docker_jobs.get(job_id)
        if name:
            try:
                rm = await asyncio.create_subprocess_exec(
                    *settings.DOCKER_CMD.split(),
                    "rm",
                    "-f",
                    name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(
                    rm.wait(), timeout=settings.DOCKER_CMD_TIMEOUT_SECONDS
                )
            except Exception:  # noqa: BLE001
                pass
        await self._terminate(proc)

    @staticmethod
    async def _terminate(proc: asyncio.subprocess.Process) -> None:
        """SIGTERM ke grup proses, lalu SIGKILL bila belum mati."""
        if proc.returncode is not None:
            return
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass


# Instance global.
executor = JobExecutor()
