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
    """Konversi .ipynb -> skrip Python (sel kode digabung; magics/!shell di-skip)."""
    data = json.loads(ipynb_path.read_text(encoding="utf-8", errors="replace"))
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
    """Kembalikan satu-satunya .ipynb di top-level (bila tepat satu)."""
    nbs = sorted(run_dir.glob("*.ipynb"))
    return nbs[0] if len(nbs) == 1 else None
