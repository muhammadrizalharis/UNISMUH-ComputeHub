"""Penyiapan sumber kode: deteksi entrypoint otomatis & konversi notebook.

Tujuan: mahasiswa cukup unggah/tempel kode; sistem menentukan perintah jalannya.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

# Urutan kandidat entrypoint umum (top-level).
ENTRY_CANDIDATES = ("main.py", "app.py", "train.py", "run.py", "__main__.py")

# Folder yang TIDAK ikut ditelusuri saat mencari entrypoint (dependensi/junk) supaya
# tak salah pilih berkas milik library & tetap cepat pada project besar.
_IGNORE_DIRS = {
    "_pydeps", "__pycache__", ".git", ".hg", ".svn", "node_modules",
    ".ipynb_checkpoints", ".venv", "venv", "env", "site-packages",
    ".mypy_cache", ".pytest_cache", ".tox", ".idea", ".vscode",
}
# Berkas yang tak dianggap entrypoint (buatan sistem / hasil eksekusi).
_IGNORE_FILES = {"_run_notebook.py", "notebook_executed.ipynb"}


def _iter_files(root: Path, suffix: str) -> list[Path]:
    """Semua berkas ber-suffix (mis. '.py' / '.ipynb') di KEDALAMAN APA PUN — termasuk
    sub-sub-subfolder — SAMBIL memangkas folder dependensi/junk (_pydeps, __pycache__,
    .git, node_modules, dll). Memakai os.walk agar folder junk tak ditelusuri (efisien).
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Pangkas in-place -> os.walk tidak turun ke folder junk.
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
        for fn in filenames:
            if fn.endswith(suffix) and fn not in _IGNORE_FILES:
                out.append(Path(dirpath) / fn)
    return out


# Penanda skrip hasil auto-konversi notebook (dibuat sistem versi lama). File ber-penanda
# ini TIDAK dianggap entrypoint supaya NOTEBOOK aslinya yang dijalankan (bukan skrip basi).
_GEN_MARKER = b"Auto-generated dari notebook oleh ComputeHub"


def _is_generated(p: Path) -> bool:
    try:
        with open(p, "rb") as fh:
            return _GEN_MARKER in fh.read(256)
    except OSError:
        return False


def write_main(run_dir: Path, code: str) -> Path:
    """Tulis kode ke run_dir/main.py."""
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "main.py"
    target.write_text(code, encoding="utf-8")
    return target


# Driver eksekusi notebook (app/runners/notebook_runner.py).
_RUNNER_SRC = Path(__file__).resolve().parent.parent / "runners" / "notebook_runner.py"


def write_notebook_runner(run_dir: Path) -> Path:
    """Salin driver eksekusi notebook ke folder job sebagai _run_notebook.py."""
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "_run_notebook.py"
    target.write_text(_RUNNER_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def validate_notebook(ipynb_path: Path) -> None:
    """Pastikan berkas .ipynb valid (JSON + berisi 'cells'). Melempar ValueError berpesan
    jelas bila tidak — supaya job notebook GAGAL dengan alasan yang bisa dimengerti user,
    bukan traceback mentah."""
    try:
        data = json.loads(ipynb_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"notebook {ipynb_path.name} bukan .ipynb valid (JSON rusak): {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        raise ValueError(f"notebook {ipynb_path.name} tidak berisi sel yang valid.")


def notebook_to_script(ipynb_path: Path) -> str:
    """Konversi .ipynb -> skrip Python (sel kode digabung; magics/!shell di-skip).

    Melempar ValueError berpesan jelas bila berkas BUKAN .ipynb valid (JSON rusak atau
    tanpa sel) -> job gagal dengan alasan yang bisa dimengerti user, bukan traceback.
    """
    try:
        data = json.loads(ipynb_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"notebook {ipynb_path.name} bukan .ipynb valid (JSON rusak): {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        raise ValueError(f"notebook {ipynb_path.name} tidak berisi sel yang valid.")
    out: list[str] = ["# Auto-generated dari notebook oleh ComputeHub\n"]
    for index, cell in enumerate(data.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", [])
        code = "".join(source) if isinstance(source, list) else str(source)
        out.append(f"# --- Cell {index} ---")
        for line in code.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("%") or stripped.startswith("!"):
                out.append(f"# [skip] {line}")  # magic / shell tidak dijalankan
            else:
                out.append(line)
        out.append("")
    return "\n".join(out) + "\n"


def detect_entrypoint(run_dir: Path, python_exe: str) -> str | None:
    """Tentukan perintah eksekusi dari isi folder — cari .py di KEDALAMAN APA PUN.

    Notebook (.ipynb) ditangani terpisah oleh caller (single_notebook). Urutan prioritas
    (aman, tak menebak sembarangan):
      1) Nama kandidat umum (main.py, app.py, …) di TOP-LEVEL.
      2) Tepat satu .py di TOP-LEVEL.
      3) Nama kandidat umum di subfolder mana pun (paling DANGKAL & prioritas nama).
      4) Tepat satu skrip .py 'runnable' (bukan __init__.py) di SELURUH pohon.
    """
    py = shlex.quote(python_exe)

    def _cmd(path: Path) -> str:
        return f"{py} {shlex.quote(str(path.relative_to(run_dir)))}"

    # 1) Nama kandidat umum di TOP-LEVEL (paling eksplisit) — abaikan skrip generated.
    for name in ENTRY_CANDIDATES:
        cand = run_dir / name
        if cand.is_file() and not _is_generated(cand):
            return _cmd(cand)

    # Semua .py (rekursif), KECUALI skrip hasil auto-konversi notebook (artefak basi).
    all_py = [p for p in _iter_files(run_dir, ".py") if not _is_generated(p)]

    # 2) Tepat satu .py di TOP-LEVEL.
    top_py = [p for p in all_py if p.parent == run_dir]
    if len(top_py) == 1:
        return _cmd(top_py[0])

    # 3) Nama kandidat umum di subfolder mana pun -> paling DANGKAL, lalu prioritas nama.
    prio = {name: i for i, name in enumerate(ENTRY_CANDIDATES)}
    cands = sorted(
        (p for p in all_py if p.name in ENTRY_CANDIDATES),
        key=lambda p: (len(p.relative_to(run_dir).parts), prio.get(p.name, 99), str(p).lower()),
    )
    if cands:
        return _cmd(cands[0])

    # 4) Tepat satu skrip .py 'runnable' (bukan __init__.py) di seluruh pohon.
    runnable = [p for p in all_py if p.name != "__init__.py"]
    if len(runnable) == 1:
        return _cmd(runnable[0])

    return None


def single_notebook(run_dir: Path) -> Path | None:
    """Kembalikan SATU .ipynb untuk dijalankan otomatis — dicari di KEDALAMAN APA PUN.

    Prioritas: tepat satu .ipynb di TOP-LEVEL. Bila top-level kosong, pakai .ipynb di
    subfolder (sub-sub-… sekalipun) bila tepat satu. Checkpoint & hasil eksekusi kita
    (notebook_executed.ipynb) sudah diabaikan oleh _iter_files. Bila >1 (ambigu) -> None.
    """
    nbs = _iter_files(run_dir, ".ipynb")
    top = [p for p in nbs if p.parent == run_dir]
    if top:
        return top[0] if len(top) == 1 else None
    if len(nbs) == 1:
        return nbs[0]
    return None
