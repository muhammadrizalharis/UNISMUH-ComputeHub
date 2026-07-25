"""Workspace PERSISTEN per-user (/persist = ~/.computehub/users/<id>) — file browser ala Colab.

Backend berjalan sebagai user host (pemilik folder data), jadi bisa membaca/menulis langsung
di filesystem host TANPA docker. SEMUA operasi DI-SCOPE ke folder milik user (anti path
traversal) dan berbatas ukuran/jumlah agar aman dari penyalahgunaan.

Folder ini sama persis dengan yang di-mount sebagai /persist di container job (ch-job-*) &
kernel (ch-kernel-*). Jadi file yang dibuat dari notebook/job tampil di sini, dan file yang
diunggah/disimpan di sini langsung tersedia di sesi berikutnya (state durable lintas sesi).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from app.core.config import settings

# Tempat sampah per-user. Menghapus dari menu Penyimpanan MEMINDAHKAN item ke sini,
# bukan menghancurkannya — satu salah klik pada folder skripsi tidak lagi permanen.
# Tetap DI DALAM folder user, jadi ikut terhitung kuota (jujur & tak bisa disalahgunakan
# sbg penyimpanan gratis), dan dibersihkan otomatis setelah beberapa hari.
TRASH_DIR = ".trash"

# Folder internal (cache pip/jupyter/cuda) disembunyikan dari tampilan "Files" agar bersih.
_HIDDEN = {
    ".local", ".cache", ".nv", ".ipython", ".config", ".jupyter", ".conda",
    "__pycache__", ".ipynb_checkpoints", ".pki", TRASH_DIR,
}
_MAX_ENTRIES = 4000          # batas jumlah node pohon (anti membludak)
MAX_UPLOAD_BYTES = 256 * 1024 * 1024  # 256 MB: batas 1 file UNGGAH ke workspace
_MAX_ZIP_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB: batas total isi folder saat diunduh sbg ZIP
_MAX_ZIP_FILES = 20_000                  # batas jumlah file dalam 1 arsip unduhan


def _editor_limit() -> int:
    """Batas byte yang dikirim ke editor/penampil di BROWSER (bukan batas penyimpanan).

    Berapa pun besar file boleh tersimpan selama kuota disk user cukup; angka ini hanya
    menjaga tab browser tidak macet saat merender isi file. Di atas ini file tetap utuh
    di server dan bisa DIUNDUH.
    """
    return max(1, int(settings.EDITOR_MAX_FILE_MB)) * 1024 * 1024


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
    limit = _editor_limit()
    size = target.stat().st_size
    raw = target.read_bytes()[: limit + 1]
    truncated = size > limit
    raw = raw[:limit]
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


def _iter_dir_files(base: Path):
    """Yield (path_absolut, arcname) tiap file di `base`; lewati folder internal & symlink."""
    for dirpath, dirnames, filenames in os.walk(base):
        # Pangkas folder tersembunyi in-place agar tidak ditelusuri (cache pip/jupyter dsb).
        dirnames[:] = [
            d for d in dirnames
            if d not in _HIDDEN and not (Path(dirpath) / d).is_symlink()
        ]
        for fn in filenames:
            fp = Path(dirpath) / fn
            if fp.is_symlink():
                continue
            yield fp, fp.relative_to(base).as_posix()


def zip_dir(user_id: int, rel: str) -> tuple[str, Path]:
    """Arsipkan sebuah folder (atau SELURUH workspace bila `rel` kosong) menjadi .zip.

    Kembalikan (nama_file_zip, path_temp_di_disk). Pemanggil WAJIB menghapus file temp
    setelah dikirim (mis. lewat cleanup_temp). Folder internal (cache pip/jupyter) & symlink
    dilewati; berbatas ukuran & jumlah file agar aman (anti membludak / isi disk).
    """
    root = user_root(user_id).resolve()
    target = _safe(user_id, rel)
    if not target.exists():
        raise FileNotFoundError("Folder tidak ditemukan.")
    if not target.is_dir():
        raise ValueError("Path bukan folder.")
    base_name = "workspace" if target == root else target.name

    # Prahitung ukuran & jumlah (lewati hidden/symlink) → tolak lebih awal bila kelewat besar.
    total = 0
    count = 0
    for fp, _arc in _iter_dir_files(target):
        count += 1
        if count > _MAX_ZIP_FILES:
            raise ValueError(
                f"Terlalu banyak file (> {_MAX_ZIP_FILES}). Unduh sub-folder satu per satu."
            )
        try:
            total += fp.stat().st_size
        except OSError:
            continue
        if total > _MAX_ZIP_BYTES:
            raise ValueError(
                f"Isi folder > {_MAX_ZIP_BYTES // (1024**3)} GB, terlalu besar untuk ZIP. "
                "Unduh sub-folder/berkas yang lebih kecil."
            )

    fd, tmp_str = tempfile.mkstemp(prefix="ch-ws-", suffix=".zip")
    os.close(fd)
    tmp = Path(tmp_str)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            wrote = False
            for fp, arc in _iter_dir_files(target):
                try:
                    zf.write(fp, arcname=f"{base_name}/{arc}")
                    wrote = True
                except OSError:
                    continue
            if not wrote:  # folder kosong → tetap hasilkan zip valid & jelas
                zf.writestr(f"{base_name}/", "")
    except Exception:
        cleanup_temp(tmp)
        raise
    return f"{base_name}.zip", tmp


def cleanup_temp(path: Path) -> None:
    """Hapus file sementara (mis. zip unduhan) tanpa menimbulkan error."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def save_text(user_id: int, rel: str, content: str) -> dict:
    """Tulis/timpa file teks (mis. simpan notebook). Buat folder induk bila perlu."""
    if not (rel or "").strip():
        raise ValueError("Nama file kosong.")
    data = (content or "").encode("utf-8")
    limit = _editor_limit()
    if len(data) > limit:
        raise ValueError(
            f"File terlalu besar untuk disimpan dari editor (maks {limit // (1024 * 1024)} MB)."
        )
    target = _safe(user_id, rel)
    if target == user_root(user_id).resolve():
        raise ValueError("Path tidak valid.")
    if target.is_dir():
        raise ValueError("Path adalah folder, bukan file.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": rel, "size": len(data)}


def delete(user_id: int, rel: str) -> dict:
    """Pindahkan file/folder ke tempat sampah (BUKAN hapus permanen).

    Item disimpan di `<root>/.trash/<token>/<nama asli>` + `meta.json` berisi path
    asalnya, sehingga bisa dikembalikan persis ke tempat semula. Tempat sampah
    dibersihkan otomatis setelah `WORKSPACE_TRASH_DAYS` hari.
    """
    root = user_root(user_id).resolve()
    target = _safe(user_id, rel)
    if target == root:
        raise ValueError("Tidak bisa menghapus root workspace.")
    if not target.exists():
        raise FileNotFoundError("Tidak ditemukan.")
    if _trash_root(user_id) in (target, *target.parents):
        raise ValueError("Gunakan menu Tempat Sampah untuk item di dalamnya.")

    purge_expired(user_id)
    rel_asli = target.relative_to(root).as_posix()
    token = f"{int(time.time())}-{secrets.token_hex(4)}"
    slot = _trash_root(user_id) / token
    slot.mkdir(parents=True, exist_ok=True)
    meta = {
        "token": token,
        "path": rel_asli,
        "name": target.name,
        "type": "dir" if target.is_dir() else "file",
        "deleted_at": time.time(),
        "size": _ukuran(target),
    }
    try:
        shutil.move(str(target), str(slot / target.name))
    except OSError:
        shutil.rmtree(slot, ignore_errors=True)
        raise
    (slot / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def _trash_root(user_id: int) -> Path:
    return user_root(user_id).resolve() / TRASH_DIR


def _ukuran(path: Path) -> int:
    """Total byte sebuah file/folder (0 bila tak terbaca)."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            fp = Path(dirpath) / fn
            if fp.is_symlink():
                continue
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def _baca_slot(slot: Path) -> dict | None:
    """Metadata satu item di tempat sampah; None bila rusak/tak lengkap."""
    if not slot.is_dir():
        return None
    try:
        meta = json.loads((slot / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    isi = slot / str(meta.get("name") or "")
    if not meta.get("token") or not isi.exists():
        return None
    return meta


def list_trash(user_id: int) -> list[dict]:
    """Isi tempat sampah user, terbaru dulu. Sekalian membersihkan yang kedaluwarsa."""
    purge_expired(user_id)
    trash = _trash_root(user_id)
    if not trash.is_dir():
        return []
    items = [m for slot in trash.iterdir() if (m := _baca_slot(slot)) is not None]
    items.sort(key=lambda m: m.get("deleted_at", 0), reverse=True)
    return items


def restore_trash(user_id: int, token: str) -> dict:
    """Kembalikan item ke lokasi asalnya. Bila sudah ada yang senama, diberi akhiran."""
    root = user_root(user_id).resolve()
    slot = _slot_aman(user_id, token)
    meta = _baca_slot(slot)
    if meta is None:
        raise FileNotFoundError("Item tidak ada di tempat sampah.")

    sumber = slot / str(meta["name"])
    tujuan = _safe(user_id, str(meta["path"]))
    tujuan.parent.mkdir(parents=True, exist_ok=True)
    if tujuan.exists():
        batang = tujuan.stem if tujuan.is_file() or tujuan.suffix else tujuan.name
        akhiran = tujuan.suffix if tujuan.is_file() or tujuan.suffix else ""
        for i in range(1, 100):
            kandidat = tujuan.with_name(f"{batang} (pulih {i}){akhiran}")
            if not kandidat.exists():
                tujuan = kandidat
                break
        else:
            raise ValueError("Terlalu banyak salinan dengan nama itu.")
    shutil.move(str(sumber), str(tujuan))
    shutil.rmtree(slot, ignore_errors=True)
    return {"path": tujuan.relative_to(root).as_posix(), "name": tujuan.name}


def delete_trash(user_id: int, token: str | None = None) -> int:
    """Hapus PERMANEN satu item (token) atau seluruh isi tempat sampah. -> jumlah item."""
    trash = _trash_root(user_id)
    if not trash.is_dir():
        return 0
    if token:
        slot = _slot_aman(user_id, token)
        if not slot.is_dir():
            raise FileNotFoundError("Item tidak ada di tempat sampah.")
        shutil.rmtree(slot, ignore_errors=True)
        return 1
    jumlah = sum(1 for slot in trash.iterdir() if slot.is_dir())
    shutil.rmtree(trash, ignore_errors=True)
    return jumlah


def purge_expired(user_id: int) -> int:
    """Buang isi tempat sampah yang lebih tua dari batas hari. -> jumlah yang dibuang."""
    hari = settings.WORKSPACE_TRASH_DAYS
    trash = _trash_root(user_id)
    if hari <= 0 or not trash.is_dir():
        return 0
    batas = time.time() - hari * 86400
    dibuang = 0
    for slot in trash.iterdir():
        if not slot.is_dir():
            continue
        meta = _baca_slot(slot)
        # Slot rusak (meta hilang/isi hilang) ikut dibersihkan agar tak jadi sampah abadi.
        umur = meta.get("deleted_at", 0) if meta else _mtime(slot)
        if umur < batas:
            shutil.rmtree(slot, ignore_errors=True)
            dibuang += 1
    return dibuang


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _slot_aman(user_id: int, token: str) -> Path:
    """Path slot tempat sampah dari token; token dibatasi agar tak bisa keluar folder."""
    t = (token or "").strip()
    if not t or not all(c.isalnum() or c == "-" for c in t):
        raise ValueError("Token tidak valid.")
    return _trash_root(user_id) / t


def rename(user_id: int, rel: str, new_name: str) -> dict:
    """Ganti NAMA file/folder di tempatnya (tidak memindahkan ke folder lain).

    `new_name` di-basename & ditolak bila mengandung pemisah path/`..` -> tak bisa
    dipakai untuk keluar dari workspace. Nama folder internal (mis. `.cache`) ditolak
    agar entri tak "hilang" dari tampilan.
    """
    root = user_root(user_id).resolve()
    src = _safe(user_id, rel)
    if src == root:
        raise ValueError("Root workspace tidak bisa diganti nama.")
    if not src.exists():
        raise FileNotFoundError("Tidak ditemukan.")
    name = (new_name or "").strip()
    if not name or name in (".", "..") or len(name) > 120:
        raise ValueError("Nama tidak valid.")
    if "/" in name or "\\" in name or "\0" in name:
        raise ValueError("Nama tidak boleh mengandung '/' atau '\\'.")
    if name in _HIDDEN:
        raise ValueError("Nama itu dipakai sistem, pilih nama lain.")
    dst = _safe(user_id, (src.parent / name).relative_to(root).as_posix())
    if dst == src:
        return {"path": src.relative_to(root).as_posix(), "name": src.name}
    if dst.exists():
        raise ValueError(f"Sudah ada '{name}' di folder itu.")
    src.rename(dst)
    return {"path": dst.relative_to(root).as_posix(), "name": name}


def prepare_upload_target(user_id: int, rel_dir: str, filename: str):
    """Validasi tujuan unggah & siapkan folder induk; kembalikan (path_absolut, rel_str).

    `filename` di-basename (buang komponen path) untuk cegah traversal; `rel_dir` (opsional)
    = subfolder tujuan. Penulisan isi dilakukan pemanggil secara streaming (anti boros RAM).
    """
    name = os.path.basename((filename or "").strip())
    if not name or name in (".", ".."):
        raise ValueError("Nama file tidak valid.")
    sub = (rel_dir or "").strip().strip("/")
    rel = f"{sub}/{name}" if sub else name
    root = user_root(user_id).resolve()
    target = _safe(user_id, rel)
    if target == root or target.is_dir():
        raise ValueError("Path tujuan tidak valid.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, target.relative_to(root).as_posix()
