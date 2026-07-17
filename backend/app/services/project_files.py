"""Operasi file pada folder project (root-based) — dipakai explorer job batch (JobDetail).

Path-safe: semua operasi DI DALAM `root`; '..'/absolut ditolak. Membangun pohon &
deteksi bahasa memakai util dari services.interactive agar konsisten dengan explorer
Notebook Interaktif (satu perilaku di seluruh aplikasi).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.services.interactive import (
    _MAX_TEXT_FILE_BYTES,
    _MAX_TREE_ENTRIES,
    _build_tree,
    _lang_for,
)


def _safe(root: Path, rel: str) -> Path:
    """Resolusi `rel` DI DALAM root; tolak path traversal (di luar root)."""
    root = root.resolve()
    target = (root / (rel or "").lstrip("/")).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path di luar project.")
    return target


def build_tree(root: Path) -> dict:
    root = root.resolve()
    if not root.exists():
        return {"name": "project", "path": "", "type": "dir", "children": []}
    t = _build_tree(root, root, [_MAX_TREE_ENTRIES])
    if not t.get("name"):
        t["name"] = "project"
    return t


def read_text(root: Path, rel: str) -> dict:
    target = _safe(root, rel)
    if not target.is_file():
        raise FileNotFoundError("File tidak ditemukan.")
    size = target.stat().st_size
    raw = target.read_bytes()[:_MAX_TEXT_FILE_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File biner — tidak bisa ditampilkan di editor.")
    return {
        "path": rel,
        "content": text,
        "language": _lang_for(target.name),
        "truncated": size > _MAX_TEXT_FILE_BYTES,
    }


def write_text(root: Path, rel: str, content: str) -> dict:
    target = _safe(root, rel)
    if target == root.resolve():
        raise ValueError("Nama file tidak valid.")
    if target.is_dir():
        raise ValueError("Path adalah folder, bukan file.")
    if len((content or "").encode("utf-8")) > _MAX_TEXT_FILE_BYTES:
        raise ValueError("Isi file terlalu besar.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content or "", encoding="utf-8")
    return build_tree(root)


def make_dir(root: Path, rel: str) -> dict:
    target = _safe(root, rel)
    if target == root.resolve():
        raise ValueError("Nama folder tidak valid.")
    if target.exists():
        raise ValueError("Nama sudah dipakai.")
    target.mkdir(parents=True, exist_ok=True)
    return build_tree(root)


def rename(root: Path, rel: str, new_rel: str) -> dict:
    src = _safe(root, rel)
    dst = _safe(root, new_rel)
    r = root.resolve()
    if src == r or dst == r:
        raise ValueError("Tidak bisa mengganti nama root project.")
    if not src.exists():
        raise FileNotFoundError("Item tidak ditemukan.")
    if dst.exists():
        raise ValueError("Nama tujuan sudah dipakai.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return build_tree(root)


def delete(root: Path, rel: str) -> dict:
    target = _safe(root, rel)
    if target == root.resolve():
        raise ValueError("Tidak bisa menghapus root project.")
    if not target.exists():
        raise FileNotFoundError("Item tidak ditemukan.")
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)
    return build_tree(root)
