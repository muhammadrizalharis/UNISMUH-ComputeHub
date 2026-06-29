"""Workspace PERSISTEN per-user (/persist = ~/.computehub/users/<id>) — file browser ala Colab.

Backend berjalan sebagai user host (pemilik folder data), jadi bisa membaca/menulis langsung
di filesystem host TANPA docker. SEMUA operasi DI-SCOPE ke folder milik user (anti path
traversal) dan berbatas ukuran/jumlah agar aman dari penyalahgunaan.

Folder ini sama persis dengan yang di-mount sebagai /persist di container job (ch-job-*) &
kernel (ch-kernel-*). Jadi file yang dibuat dari notebook/job tampil di sini, dan file yang
diunggah/disimpan di sini langsung tersedia di sesi berikutnya (state durable lintas sesi).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.core.config import settings

# Folder internal (cache pip/jupyter/cuda) disembunyikan dari tampilan "Files" agar bersih.
_HIDDEN = {
    ".local", ".cache", ".nv", ".ipython", ".config", ".jupyter", ".conda",
    "__pycache__", ".ipynb_checkpoints", ".pki",
}
_MAX_ENTRIES = 4000          # batas jumlah node pohon (anti membludak)
_MAX_TEXT_BYTES = 1_000_000  # 1 MB: batas baca file teks ke editor
_MAX_SAVE_BYTES = 5_000_000  # 5 MB: batas tulis 1 file dari UI (mis. notebook)

# Ekstensi -> bahasa Monaco (untuk highlight saat buka file).
_LANG = {
    ".py": "python", ".ipynb": "json", ".json": "json", ".js": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".md": "markdown", ".txt": "plaintext", ".csv": "plaintext", ".log": "plaintext",
    ".yml": "yaml", ".yaml": "yaml", ".toml": "ini", ".cfg": "ini", ".ini": "ini",
    ".sh": "shell", ".html": "html", ".css": "css", ".sql": "sql", ".xml": "xml",
    ".c": "c", ".cpp": "cpp", ".h": "cpp", ".java": "java", ".go": "go", ".rs": "rust",
}


def user_root(user_id: int) -> Path:
    """Folder workspace milik user (belum tentu sudah ada)."""
    return settings.docker_user_data_root / str(int(user_id))


def ensure_root(user_id: int) -> Path:
    root = user_root(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe(user_id: int, rel: str) -> Path:
    """Resolusi `rel` DI DALAM folder user; tolak path traversal (di luar root)."""
    root = user_root(user_id).resolve()
    target = (root / (rel or "")).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path di luar workspace.")
    return target


def _lang_for(name: str) -> str:
    return _LANG.get(Path(name).suffix.lower(), "plaintext")


def _node(path: Path, root: Path, budget: list[int]) -> dict:
    node: dict = {
        "name": path.name or "workspace",
        "path": "" if path == root else path.relative_to(root).as_posix(),
        "type": "dir",
        "children": [],
    }
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return node
    for child in entries:
        if budget[0] <= 0:
            break
        if child.name in _HIDDEN or child.is_symlink():
            continue
        budget[0] -= 1
        if child.is_dir():
            node["children"].append(_node(child, root, budget))
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


def tree(user_id: int) -> dict:
    """Pohon file workspace user (folder internal disembunyikan)."""
    root = ensure_root(user_id).resolve()
    t = _node(root, root, [_MAX_ENTRIES])
    t["name"] = "workspace"
    return t


def usage(user_id: int) -> dict:
    """Total byte & jumlah file di workspace (TERMASUK folder internal -> pemakaian nyata)."""
    root = user_root(user_id)
    total = 0
    files = 0
    if root.exists():
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                fp = Path(dirpath) / fn
                if fp.is_symlink():
                    continue
                try:
                    total += fp.stat().st_size
                    files += 1
                except OSError:
                    continue
    return {"bytes": total, "files": files}


def read_text(user_id: int, rel: str) -> dict:
    """Baca file teks (anti traversal, batas ukuran). Raise FileNotFoundError/ValueError."""
    target = _safe(user_id, rel)
    if not target.is_file():
        raise FileNotFoundError("File tidak ditemukan.")
    size = target.stat().st_size
    raw = target.read_bytes()[: _MAX_TEXT_BYTES + 1]
    truncated = size > _MAX_TEXT_BYTES
    raw = raw[:_MAX_TEXT_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File biner — tidak bisa ditampilkan di editor.")
    return {
        "path": rel,
        "content": text,
        "language": _lang_for(target.name),
        "truncated": truncated,
        "size": size,
    }


def resolve_file(user_id: int, rel: str) -> tuple[str, Path]:
    """Validasi & kembalikan (nama, path absolut) sebuah file untuk diunduh (stream disk)."""
    target = _safe(user_id, rel)
    if not target.is_file():
        raise FileNotFoundError("File tidak ditemukan.")
    return target.name, target


def save_text(user_id: int, rel: str, content: str) -> dict:
    """Tulis/timpa file teks (mis. simpan notebook). Buat folder induk bila perlu."""
    if not (rel or "").strip():
        raise ValueError("Nama file kosong.")
    data = (content or "").encode("utf-8")
    if len(data) > _MAX_SAVE_BYTES:
        raise ValueError("File terlalu besar untuk disimpan dari editor (maks 5 MB).")
    target = _safe(user_id, rel)
    if target == user_root(user_id).resolve():
        raise ValueError("Path tidak valid.")
    if target.is_dir():
        raise ValueError("Path adalah folder, bukan file.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": rel, "size": len(data)}


def delete(user_id: int, rel: str) -> None:
    """Hapus file atau folder DI DALAM workspace (tak boleh root)."""
    root = user_root(user_id).resolve()
    target = _safe(user_id, rel)
    if target == root:
        raise ValueError("Tidak bisa menghapus root workspace.")
    if not target.exists():
        raise FileNotFoundError("Tidak ditemukan.")
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)
