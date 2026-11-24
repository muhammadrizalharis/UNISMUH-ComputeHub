"""Ruang kerja kelas (A4): folder Kelas/<nama>/ milik mahasiswa + pantauan baca-saja pengajar.

Folder berada di penyimpanan pribadi mahasiswa (kuotanya sendiri) dan TETAP miliknya
setelah keluar kelas. Pengajar hanya bisa MEMBACA isi folder ini selama mahasiswa masih
anggota — tidak ada akses ke berkas lain, layar, atau jendela aplikasi.
Semua akses menolak symlink agar tidak bisa "melompat" keluar dari folder kelas.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from app.services import class_materials as materials_svc
from app.services import workspace as workspace_svc
from app.services.class_materials import KELAS_DIR, MaterialError

MAX_WALK_ENTRIES = 3000
MAX_WALK_DEPTH = 8
MAX_LIST_ENTRIES = 1000
MAX_READ_BYTES = 2 * 1024 * 1024
SNIPPET_BYTES = 4096
_VSCODE_SETTINGS = {"files.autoSave": "afterDelay", "files.autoSaveDelay": 1000}


class WorkspaceError(Exception):
    pass


def _hidden(name: str) -> bool:
    return name in workspace_svc._HIDDEN or name.startswith(".")


def rel_path(folder: str) -> str:
    return f"{KELAS_DIR}/{folder}"


def ensure_folder(user_id: int, folder: str) -> str:
    """Buat Kelas/<folder>/ (+ autosave VS Code ~1 dtk) bila belum ada. Kembalikan path relatif."""
    root = workspace_svc.ensure_root(user_id).resolve()
    try:
        base = materials_svc._safe_mkdirs(root, [KELAS_DIR, folder])
        vs = materials_svc._safe_mkdirs(base, [".vscode"])
    except MaterialError as exc:
        raise WorkspaceError(str(exc)) from exc
    target = vs / "settings.json"
    if not os.path.lexists(target):
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "w") as f:
                json.dump(_VSCODE_SETTINGS, f, indent=2)
                f.write("\n")
        except OSError:
            pass
    return rel_path(folder)


def class_root(user_id: int, folder: str) -> Path | None:
    """Path folder kelas bila ada & bukan symlink di jalurnya; None bila belum ada."""
    cur = workspace_svc.user_root(user_id)
    for part in (KELAS_DIR, folder):
        cur = cur / part
        try:
            st = os.lstat(cur)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            return None
    return cur


def _inside(user_id: int, folder: str, rel: str) -> Path:
    base = class_root(user_id, folder)
    if base is None:
        raise WorkspaceError("Folder kelas mahasiswa ini belum ada.")
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    cur = base
    for part in parts:
        if part == ".." or _hidden(part):
            raise WorkspaceError("Path tidak valid.")
        cur = cur / part
        try:
            st = os.lstat(cur)
        except OSError as exc:
            raise WorkspaceError("Berkas tidak ditemukan.") from exc
        if stat.S_ISLNK(st.st_mode):
            raise WorkspaceError("Path tidak valid.")
    return cur


def _is_binary(head: bytes) -> bool:
    return b"\x00" in head


def _notebook_code(raw: bytes) -> str:
    try:
        nb = json.loads(raw.decode("utf-8", "replace"))
        cells = nb.get("cells") or []
    except (ValueError, AttributeError):
        return ""
    out: list[str] = []
    for c in cells:
        if isinstance(c, dict) and c.get("cell_type") == "code":
            src = c.get("source")
            out.append("".join(src) if isinstance(src, list) else str(src or ""))
    return "\n\n# ---\n".join(s for s in out if s.strip())


def _snippet(path: Path) -> str | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if path.suffix.lower() == ".ipynb":
            raw = f.read(MAX_READ_BYTES + 1)
            if len(raw) > MAX_READ_BYTES:
                return None
            return _notebook_code(raw)[:SNIPPET_BYTES]
        head = f.read(SNIPPET_BYTES)
    if _is_binary(head):
        return None
    return head.decode("utf-8", "replace")


def empty_summary() -> dict:
    return {"exists": False, "file_count": 0, "total_bytes": 0,
            "last_file": None, "last_modified": None, "snippet": None, "truncated": False}


def summary(user_id: int, folder: str | None) -> dict:
    """Ringkasan untuk ubin pantauan: jumlah file, file terakhir disimpan, cuplikannya."""
    base = class_root(user_id, folder) if folder else None
    if base is None:
        return empty_summary()
    files = total = seen = 0
    last: tuple[float, Path] | None = None
    truncated = False
    base_depth = len(base.parts)
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        if len(Path(dirpath).parts) - base_depth >= MAX_WALK_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not _hidden(d)]
        for fn in filenames:
            seen += 1
            if seen > MAX_WALK_ENTRIES:
                truncated = True
                break
            if _hidden(fn):
                continue
            p = Path(dirpath) / fn
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            files += 1
            total += st.st_size
            if last is None or st.st_mtime > last[0]:
                last = (st.st_mtime, p)
        if truncated:
            dirnames[:] = []
            break
    return {
        "exists": True,
        "file_count": files,
        "total_bytes": total,
        "last_file": last[1].relative_to(base).as_posix() if last else None,
        "last_modified": last[0] if last else None,
        "snippet": _snippet(last[1]) if last else None,
        "truncated": truncated,
    }


def list_dir(user_id: int, folder: str, rel: str) -> list[dict]:
    d = _inside(user_id, folder, rel)
    if not d.is_dir():
        raise WorkspaceError("Bukan folder.")
    out: list[dict] = []
    with os.scandir(d) as it:
        for e in it:
            if _hidden(e.name):
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                kind = "dir"
            elif stat.S_ISREG(st.st_mode):
                kind = "file"
            else:
                continue
            out.append({"name": e.name, "type": kind, "size": st.st_size if kind == "file" else 0,
                        "modified": st.st_mtime})
            if len(out) >= MAX_LIST_ENTRIES:
                break
    out.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    return out


def read_file(user_id: int, folder: str, rel: str) -> dict:
    p = _inside(user_id, folder, rel)
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise WorkspaceError("Berkas tidak dapat dibaca.") from exc
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise WorkspaceError("Bukan berkas.")
        base = {"path": rel, "size": st.st_size, "modified": st.st_mtime,
                "language": workspace_svc._lang_for(p.name)}
        if st.st_size > MAX_READ_BYTES:
            return {**base, "content": None, "reason": "too_large"}
        raw = f.read(MAX_READ_BYTES)
    if _is_binary(raw[:8192]):
        return {**base, "content": None, "reason": "binary"}
    return {**base, "content": raw.decode("utf-8", "replace"), "reason": None}
