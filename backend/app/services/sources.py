"""Penyiapan sumber kode: deteksi entrypoint otomatis & konversi notebook.

Tujuan: mahasiswa cukup unggah/tempel kode; sistem menentukan perintah jalannya.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

# Urutan kandidat entrypoint umum (top-level).
ENTRY_CANDIDATES = ("main.py", "app.py", "train.py", "run.py", "__main__.py")


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
    """Tentukan perintah eksekusi dari isi folder. None bila tidak ketemu .py.

    Catatan: notebook (.ipynb) TIDAK ditangani di sini (lihat caller).
    """
    py = shlex.quote(python_exe)

    # 1) Kandidat nama umum di top-level.
    for name in ENTRY_CANDIDATES:
        if (run_dir / name).is_file():
            return f"{py} {shlex.quote(name)}"

    # 2) Tepat satu file .py di top-level.
    top_py = sorted(p.name for p in run_dir.glob("*.py"))
    if len(top_py) == 1:
        return f"{py} {shlex.quote(top_py[0])}"

    # 3) main.py di subfolder (paket).
    for cand in sorted(run_dir.rglob("main.py")):
        rel = cand.relative_to(run_dir)
        return f"{py} {shlex.quote(str(rel))}"

    return None


def single_notebook(run_dir: Path) -> Path | None:
    """Kembalikan SATU .ipynb untuk dijalankan otomatis.

    Prioritas: tepat satu .ipynb di TOP-LEVEL. Bila top-level tak ada, cari REKURSIF di
    subfolder (mis. notebook/analisis.ipynb) dan pakai bila tepat satu. Berkas checkpoint
    & hasil eksekusi kita sendiri (notebook_executed.ipynb) diabaikan. Bila jumlahnya >1
    (ambigu), kembalikan None supaya sistem tidak menebak.
    """

    def _ok(p: Path) -> bool:
        parts = set(p.parts)
        return ".ipynb_checkpoints" not in parts and p.name != "notebook_executed.ipynb"

    top = sorted(p for p in run_dir.glob("*.ipynb") if _ok(p))
    if top:
        return top[0] if len(top) == 1 else None
    deep = sorted(p for p in run_dir.rglob("*.ipynb") if _ok(p))
    return deep[0] if len(deep) == 1 else None
