"""Penyimpanan MATERI KELAS (A2): salinan beku file/folder dari workspace pengajar.

Alur:
1. Pengajar membagikan file/folder dari /persist miliknya -> `snapshot()` menyalinnya ke
   `<data>/class-materials/<kelas>/<materi>/<nama>` (di luar workspace siapa pun).
2. Mahasiswa menekan "Ambil salinan" -> `deliver()` menyalin materi ke
   `/persist/Kelas/<nama kelas>/<nama>` miliknya, TANPA menimpa (nama bentrok diberi akhiran).

Keamanan: workspace dikendalikan pengguna (bisa berisi symlink), jadi symlink dilewati,
file dibuka dengan O_NOFOLLOW, dan folder tujuan dibuat per komponen sambil menolak symlink.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

from app.core.config import settings
from app.services import workspace as workspace_svc

# Tanpa batas ukuran materi (keputusan admin); yang menjaga hanya sisa disk server.
MAX_MATERIAL_FILES = 50_000
KELAS_DIR = "Kelas"
_CHUNK = 1024 * 1024


class MaterialError(ValueError):
    """Kesalahan yang aman ditampilkan ke pengguna."""


def store_root() -> Path:
    return settings.docker_user_data_root.parent / "class-materials"


def class_dir(class_id: int) -> Path:
    return store_root() / str(int(class_id))


def material_dir(class_id: int, material_id: int) -> Path:
    return class_dir(class_id) / str(int(material_id))


def _skip_name(name: str) -> bool:
    return name in workspace_svc._HIDDEN


def _scan(src: Path) -> tuple[int, int]:
    """Hitung (byte, jumlah file) yang akan disalin; tolak bila melewati batas."""
    st = os.lstat(src)
    if stat.S_ISREG(st.st_mode):
        return st.st_size, 1
    total = files = 0
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = [d for d in dirnames if not _skip_name(d) and not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            try:
                fst = os.lstat(os.path.join(dirpath, fn))
            except OSError:
                continue
            if not stat.S_ISREG(fst.st_mode):
                continue
            total += fst.st_size
            files += 1
            if files > MAX_MATERIAL_FILES:
                raise MaterialError(f"Folder berisi terlalu banyak file (maks {MAX_MATERIAL_FILES}).")
    return total, files


def _copy_file(src: Path, dst: Path) -> None:
    """Salin satu file biasa; sumber tak boleh symlink, tujuan harus baru (O_EXCL)."""
    fd_in = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd_in).st_mode):
            return
        fd_out = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd_in, "rb", closefd=False) as fin, os.fdopen(fd_out, "wb") as fout:
            shutil.copyfileobj(fin, fout, _CHUNK)
    finally:
        os.close(fd_in)


def _copy_tree(src: Path, dst: Path) -> None:
    st = os.lstat(src)
    if stat.S_ISREG(st.st_mode):
        _copy_file(src, dst)
        return
    os.mkdir(dst, 0o755)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = [d for d in dirnames if not _skip_name(d) and not os.path.islink(os.path.join(dirpath, d))]
        rel = os.path.relpath(dirpath, src)
        base = dst if rel == "." else dst / rel
        for d in dirnames:
            os.mkdir(base / d, 0o755)
        for fn in filenames:
            s = Path(dirpath) / fn
            try:
                if not stat.S_ISREG(os.lstat(s).st_mode):
                    continue
            except OSError:
                continue
            _copy_file(s, base / fn)


def _remove(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    except OSError:
        pass


def class_usage(class_id: int) -> int:
    root = class_dir(class_id)
    total = 0
    for dirpath, _d, filenames in os.walk(root, followlinks=False):
        for fn in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, fn)).st_size
            except OSError:
                continue
    return total


def inspect_source(user_id: int, rel: str) -> tuple[Path, str, int, int]:
    """Validasi sumber di workspace pengajar -> (path, kind, byte, jumlah file)."""
    rel = (rel or "").strip().strip("/")
    if not rel:
        raise MaterialError("Pilih file atau folder yang akan dibagikan.")
    if _skip_name(rel.split("/")[0]):
        raise MaterialError("Folder sistem tidak bisa dibagikan.")
    root = workspace_svc.user_root(user_id).resolve()
    # Jangan me-resolve komponen terakhir: symlink harus ditolak, bukan diikuti.
    parent = workspace_svc._safe(user_id, os.path.dirname(rel))
    src = parent / os.path.basename(rel)
    if src == root or root not in src.parents:
        raise MaterialError("Path tidak valid.")
    try:
        st = os.lstat(src)
    except FileNotFoundError as exc:
        raise MaterialError("File atau folder tidak ditemukan.") from exc
    if stat.S_ISLNK(st.st_mode) or not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
        raise MaterialError("Hanya file atau folder biasa yang bisa dibagikan.")
    size, files = _scan(src)
    return src, ("file" if stat.S_ISREG(st.st_mode) else "dir"), size, files


def snapshot(src: Path, class_id: int, material_id: int) -> None:
    """Salin sumber ke penyimpanan materi kelas (atomik: tmp lalu rename)."""
    final = material_dir(class_id, material_id)
    tmp = final.with_name(f".tmp-{material_id}")
    _remove(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        _copy_tree(src, tmp / src.name)
        _remove(final)
        tmp.rename(final)
    except Exception:
        _remove(tmp)
        raise


def remove_material(class_id: int, material_id: int) -> None:
    _remove(material_dir(class_id, material_id))


def remove_class(class_id: int) -> None:
    _remove(class_dir(class_id))


def folder_name(class_name: str, class_id: int) -> str:
    name = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", " ", class_name or "")
    name = re.sub(r"\s+", " ", name).strip().lstrip(".").strip()[:80].rstrip()
    return name or f"kelas-{int(class_id)}"


def _safe_mkdirs(root: Path, parts: list[str]) -> Path:
    """Buat folder per komponen di dalam root, menolak symlink/file di jalurnya."""
    cur = root
    for part in parts:
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            os.mkdir(cur, 0o755)
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise MaterialError(f"'{cur.relative_to(root).as_posix()}' bukan folder biasa di workspace Anda.")
    return cur


def _free_name(parent: Path, name: str) -> Path:
    cand = parent / name
    if not os.path.lexists(cand):
        return cand
    p = Path(name)
    stem, suffix = (p.stem, p.suffix) if p.suffix and not name.startswith(".") else (name, "")
    for i in range(2, 1000):
        cand = parent / f"{stem} ({i}){suffix}"
        if not os.path.lexists(cand):
            return cand
    raise MaterialError("Terlalu banyak salinan dengan nama yang sama.")


def deliver(class_id: int, material_id: int, name: str, user_id: int, class_folder: str) -> str:
    """Salin materi ke /persist/Kelas/<kelas>/ milik user. Kembalikan path relatif tujuan."""
    src = material_dir(class_id, material_id) / name
    if not os.path.lexists(src):
        raise MaterialError("Berkas materi tidak ditemukan di server. Minta pengajar membagikan ulang.")
    root = workspace_svc.ensure_root(user_id).resolve()
    parent = _safe_mkdirs(root, [KELAS_DIR, class_folder])
    dst = _free_name(parent, name)
    try:
        _copy_tree(src, dst)
    except Exception:
        _remove(dst)
        raise
    return dst.relative_to(root).as_posix()
