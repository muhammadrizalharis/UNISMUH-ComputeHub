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

from app.core.config import settings
from app.core.logging import get_logger
from app.models.job import JobSource, JobStatus
from app.services import archive as archive_svc
from app.services import policy as policy_svc
from app.services import repo as repo_svc
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


@dataclasses.dataclass
class RunResult:
    status: JobStatus
    exit_code: int | None
    pid: int | None
    started_at: dt.datetime
    finished_at: dt.datetime
    error_message: str | None = None


def _build_env(gpu_index: int) -> dict[str, str]:
    """Environment subprocess dengan GPU dipaksa + footprint CPU diminimalkan."""
    env = os.environ.copy()

    # --- Paksa GPU spesifik ---
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    env["NVIDIA_VISIBLE_DEVICES"] = str(gpu_index)
    env["GPU_DEVICE_ORDINAL"] = str(gpu_index)

    # --- Minimalkan pemakaian CPU (server bersama) ---
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


class JobExecutor:
    """Menjalankan & mengelola subprocess job (mendukung cancel)."""

    def __init__(self) -> None:
        self._procs: dict[int, asyncio.subprocess.Process] = {}

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
        try:
            proc = await asyncio.create_subprocess_exec(
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
                cwd=run_cwd,
                env=env,
                stdout=log,
                stderr=log,
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

    def _resolve_command(self, run_cwd: str, log) -> str | None:
        """Tentukan perintah eksekusi otomatis dari isi folder."""
        py = sys.executable
        cmd = sources_svc.detect_entrypoint(Path(run_cwd), py)
        if cmd:
            return cmd
        nb = sources_svc.single_notebook(Path(run_cwd))
        if nb is not None:
            code = sources_svc.notebook_to_script(nb)
            sources_svc.write_main(Path(run_cwd), code)
            log.write(f"[SOURCE] notebook {nb.name} dikonversi -> main.py\n".encode())
            log.flush()
            return f"{shlex.quote(py)} main.py"
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
        on_start: Callable[[int], None] | None = None,
    ) -> RunResult:
        """Jalankan satu job di GPU `gpu_index`. Blok sampai selesai."""
        started_at = dt.datetime.now(dt.timezone.utc)
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        env = _build_env(gpu_index)
        run_cwd = working_dir

        with open(log_path, "ab", buffering=0) as log:
            header = (
                f"===== JOB #{job_id} =====\n"
                f"waktu_mulai : {started_at.isoformat()}\n"
                f"gpu_index   : {gpu_index}\n"
                f"sumber      : {source_type.value}\n"
                f"batas_waktu : {time_limit_seconds or 'tanpa batas'} dtk\n"
                f"working_dir : {working_dir}\n"
                f"command     : {command}\n"
                f"CUDA_VISIBLE_DEVICES={env['CUDA_VISIBLE_DEVICES']}\n"
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
                log.write(f"[EXECUTOR] repo siap di {run_cwd}\n{'-' * 60}\n".encode())
                log.flush()

            # --- Ekstrak project upload (ZIP) bila perlu ---
            elif source_type is JobSource.upload:
                archive = Path(working_dir) / "_upload.zip"
                project_dir = Path(working_dir) / "project"
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
                run_cwd = str(project_dir)
                log.write(f"[EXECUTOR] project siap di {run_cwd}\n{'-' * 60}\n".encode())
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
            if (
                source_type in (JobSource.git, JobSource.upload)
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
                resolved = self._resolve_command(run_cwd, log)
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
                    f"[EXECUTOR] perintah otomatis: {command}\n{'-' * 60}\n".encode()
                )
                log.flush()

            # --- PREFLIGHT GPU (wajib) ---
            if settings.REQUIRE_CUDA_PREFLIGHT:
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
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=run_cwd,
                    env=env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,  # grup proses sendiri -> mudah di-kill
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
                await self._terminate(proc)
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
                await self._terminate(proc)
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
        await self._terminate(proc)
        return True

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
