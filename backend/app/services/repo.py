"""Sumber job dari Git (GitHub): validasi URL & clone aman.

Catatan keamanan:
  - Hanya host yang diizinkan (default github.com).
  - URL & ref divalidasi (anti argument-injection).
  - git dijalankan via argument list (TANPA shell).
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# https://host/owner/repo(.git)
_URL_RE = re.compile(
    r"^https://([A-Za-z0-9.\-]+)/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+?(?:\.git)?/?$"
)
_REF_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")


def validate_repo_url(url: str) -> str | None:
    """Kembalikan pesan error bila tidak valid, atau None bila valid."""
    url = (url or "").strip()
    m = _URL_RE.match(url)
    if not m:
        return "URL repo tidak valid (format: https://github.com/owner/repo)."
    host = m.group(1).lower()
    if host not in settings.allowed_git_hosts:
        return f"Host git tidak diizinkan: {host}."
    return None


def validate_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    if ref.startswith("-") or not _REF_RE.match(ref):
        return "Ref/branch/commit tidak valid."
    return None


async def _run_git(args: list[str], log: BinaryIO, timeout: int, cwd: Path | None = None) -> int:
    git = shutil.which("git")
    if not git:
        log.write(b"[GIT] git tidak tersedia di server.\n")
        log.flush()
        return 127
    log.write(f"[GIT] $ git {' '.join(args)}\n".encode())
    log.flush()
    proc = await asyncio.create_subprocess_exec(
        git, *args, stdout=log, stderr=log, cwd=str(cwd) if cwd else None
    )
    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        log.write(b"[GIT] Timeout saat clone.\n")
        log.flush()
        return 124


async def clone_repo(
    *,
    url: str,
    ref: str | None,
    dest: Path,
    log: BinaryIO,
) -> bool:
    """Clone repo ke `dest`. Tulis output ke `log`. True bila sukses."""
    err = validate_repo_url(url) or validate_ref(ref)
    if err:
        log.write(f"[GIT] Ditolak: {err}\n".encode())
        log.flush()
        return False

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Jalankan git dari folder INDUK dengan nama tujuan RELATIF ('repo') supaya baik
    # perintah yang di-log MAUPUN output git ("Cloning into 'repo'...") tak memuat path
    # absolut server (username/struktur folder = info sensitif).
    parent = dest.parent
    name = dest.name

    timeout = settings.GIT_CLONE_TIMEOUT_SECONDS

    if ref:
        # Full clone supaya bisa checkout branch/tag/commit apa pun.
        code = await _run_git(["clone", url, name], log, timeout, cwd=parent)
        if code != 0:
            return False
        code = await _run_git(
            ["-C", name, "checkout", "--quiet", ref], log, timeout, cwd=parent
        )
        return code == 0

    # Tanpa ref: clone dangkal (lebih cepat & hemat).
    code = await _run_git(["clone", "--depth", "1", url, name], log, timeout, cwd=parent)
    return code == 0
