"""Batas resource keras (rlimit) untuk subprocess job & kernel — mitigasi DoS non-root.

Dipakai sebagai `preexec_fn` saat spawn subprocess: fungsi ini berjalan di proses
ANAK setelah fork dan sebelum exec, sehingga batasnya berlaku untuk kode user
(dan diwariskan ke anak-anaknya).

CATATAN PENTING: SENGAJA TIDAK menyetel RLIMIT_AS / RLIMIT_DATA (memori virtual)
karena CUDA/PyTorch mereservasi address space sangat besar — membatasinya akan
membuat job GPU crash. Plafon memori ditegakkan terpisah lewat sampler (advisory).
Tujuan modul ini: mencegah fork bomb, core dump, dan file raksasa memenuhi disk.
"""

from __future__ import annotations

import resource
import shlex
import subprocess
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# .../backend (untuk menemukan .env yang harus disembunyikan dari kode user).
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _set(res: int, value: int) -> None:
    """Pasang soft=hard=value; abaikan bila tak didukung / melebihi hard limit."""
    try:
        resource.setrlimit(res, (value, value))
    except (ValueError, OSError):
        # Jangan gagalkan job hanya karena satu limit tak bisa dipasang.
        pass


def apply_rlimits() -> None:
    """preexec_fn: pasang batas proses/file/core untuk kode user."""
    if settings.JOB_RLIMIT_NO_CORE:
        _set(resource.RLIMIT_CORE, 0)
    if settings.JOB_RLIMIT_NPROC > 0:
        _set(resource.RLIMIT_NPROC, settings.JOB_RLIMIT_NPROC)
    if settings.JOB_RLIMIT_FSIZE_MB > 0:
        _set(resource.RLIMIT_FSIZE, settings.JOB_RLIMIT_FSIZE_MB * 1024 * 1024)
    if settings.JOB_RLIMIT_NOFILE > 0:
        _set(resource.RLIMIT_NOFILE, settings.JOB_RLIMIT_NOFILE)


# --------------------------------------------------------------------------
# Sandbox isolasi (user-namespace via unshare) — sembunyikan rahasia dari job
# --------------------------------------------------------------------------
_UNSHARE = ["unshare", "--user", "--map-root-user", "--mount"]
_sandbox_ok: bool | None = None


def sensitive_paths() -> list[str]:
    """File rahasia yang WAJIB disembunyikan dari kode user (mis. backend/.env)."""
    out: list[str] = []
    env_file = _BACKEND_DIR / ".env"
    if env_file.exists():
        out.append(str(env_file.resolve()))
    return out


def sandbox_available() -> bool:
    """Cek (sekali, di-cache) apakah unshare user-namespace bisa dipakai non-root."""
    global _sandbox_ok
    if _sandbox_ok is not None:
        return _sandbox_ok
    if not settings.JOB_SANDBOX_ENABLED:
        _sandbox_ok = False
        return False
    try:
        r = subprocess.run(
            [*_UNSHARE, "/bin/sh", "-c", "true"],
            capture_output=True,
            timeout=10,
        )
        _sandbox_ok = r.returncode == 0
    except Exception:  # noqa: BLE001
        _sandbox_ok = False
    if not _sandbox_ok:
        logger.warning(
            "Sandbox unshare TIDAK tersedia -> kode user jalan TANPA isolasi .env."
        )
    else:
        logger.info("Sandbox unshare aktif (sembunyikan %d file rahasia).", len(sensitive_paths()))
    return _sandbox_ok


def _hide_prelude() -> str:
    """Perintah shell: bind /dev/null di atas tiap file rahasia (di dalam mount-ns)."""
    parts = [
        f"mount --bind /dev/null {shlex.quote(p)} 2>/dev/null || true"
        for p in sensitive_paths()
    ]
    return " ; ".join(parts)


def wrap_shell_argv(command: str) -> list[str]:
    """argv create_subprocess_exec: jalankan `command` (string shell) di dalam
    user+mount namespace yang menyembunyikan file rahasia. cwd diwarisi dari parent."""
    prelude = _hide_prelude()
    inner = (prelude + " ; " if prelude else "") + f"exec /bin/sh -c {shlex.quote(command)}"
    return [*_UNSHARE, "/bin/sh", "-c", inner]


def wrap_kernel_argv(base_argv: list[str]) -> list[str]:
    """Bungkus argv kernel (mis. python -m ipykernel_launcher -f {connection_file})
    dalam sandbox. Token {connection_file} TETAP literal agar disubstitusi Jupyter."""
    prelude = _hide_prelude()
    cmd = " ".join(
        # JANGAN quote token {connection_file} agar Jupyter bisa substitusi.
        a if a == "{connection_file}" else shlex.quote(a)
        for a in base_argv
    )
    inner = (prelude + " ; " if prelude else "") + f"exec {cmd}"
    return [*_UNSHARE, "/bin/sh", "-c", inner]
