"""Analisis statik (lint) kode Python — AMAN: hanya mem-parsing, TIDAK menjalankan kode.

Dipakai oleh:
- Endpoint POST /api/v1/lint  -> "error lens" langsung di editor (tempel kode & sel notebook).
- Pre-flight job di executor    -> peringatan kode untuk upload ZIP & GitHub repo (ditulis ke log job).

Mesin: pyflakes (mendeteksi SyntaxError, nama tak terdefinisi, import/variabel tak terpakai, dll).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pyflakes import api as _pyflakes_api

# Batas ukuran agar analisis tetap ringan & tak bisa dipakai membebani server.
MAX_CODE_BYTES = 200_000

# Kelas pesan pyflakes yang dianggap ERROR (bug nyata). Sisanya -> WARNING.
_ERROR_MESSAGES = frozenset(
    {
        "UndefinedName",
        "UndefinedLocal",
        "UndefinedExport",
        "DuplicateArgument",
        "ReturnOutsideFunction",
        "YieldOutsideFunction",
        "ContinueOutsideLoop",
        "BreakOutsideLoop",
        "ForwardAnnotationSyntaxError",
        "RaiseNotImplemented",
        "TwoStarredExpressions",
        "TooManyExpressionsInStarredAssignment",
        "IfTuple",
        "AssertTuple",
    }
)


@dataclass
class Diagnostic:
    line: int
    col: int
    severity: str  # 'error' | 'warning'
    message: str
    source: str = "pyflakes"


class _Collector:
    """Reporter pyflakes yang mengumpulkan diagnostik alih-alih mencetak ke stderr."""

    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []

    def unexpectedError(self, filename: str, msg: str) -> None:  # noqa: N802
        self.diagnostics.append(Diagnostic(1, 1, "warning", str(msg)))

    def syntaxError(  # noqa: N802
        self,
        filename: str,
        msg: str,
        lineno: int | None,
        offset: int | None,
        text: str | None,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(int(lineno or 1), int(offset or 1), "error", f"SyntaxError: {msg}")
        )

    def flake(self, message) -> None:  # pyflakes.messages.Message
        cls = type(message).__name__
        severity = "error" if cls in _ERROR_MESSAGES else "warning"
        try:
            text = message.message % message.message_args
        except Exception:  # noqa: BLE001
            text = str(getattr(message, "message", cls))
        col = int(getattr(message, "col", 0)) + 1
        self.diagnostics.append(
            Diagnostic(int(message.lineno), col, severity, text)
        )


def lint_code(code: str) -> list[Diagnostic]:
    """Kembalikan daftar diagnostik untuk satu blok kode Python. Tak pernah melempar exception."""
    if not code or not code.strip():
        return []
    if len(code.encode("utf-8", "ignore")) > MAX_CODE_BYTES:
        return [Diagnostic(1, 1, "warning", "Kode terlalu besar untuk dianalisis.")]
    collector = _Collector()
    try:
        _pyflakes_api.check(code, "<user_code>", reporter=collector)
    except Exception as exc:  # noqa: BLE001  -- lint tak boleh menggagalkan request/job
        return [Diagnostic(1, 1, "warning", f"Analisis lint gagal: {exc}")]
    collector.diagnostics.sort(key=lambda d: (d.line, d.col))
    return collector.diagnostics


def _strip_magics(code: str) -> str:
    """Komentari baris IPython magic / shell (%, %%, !, ?) agar tak jadi SyntaxError palsu."""
    out: list[str] = []
    for line in code.splitlines():
        stripped = line.lstrip()
        if stripped[:1] in ("%", "!") or stripped[:2] == "%%" or stripped.endswith("?"):
            out.append("pass  # (magic/shell line)")
        else:
            out.append(line)
    return "\n".join(out)


def extract_notebook_code(path: str | Path) -> str:
    """Gabungkan semua sel kode dari .ipynb menjadi satu skrip (urut), magic dibersihkan."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except Exception:  # noqa: BLE001
        return ""
    parts: list[str] = []
    for cell in data.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", [])
        text = "".join(src) if isinstance(src, list) else str(src)
        if text.strip():
            parts.append(_strip_magics(text))
    return "\n\n".join(parts)


def _find_entry_py(command: str, run_cwd: str | Path) -> Path | None:
    """Cari file .py yang akan dieksekusi dari string command (token diakhiri .py)."""
    run_cwd = Path(run_cwd)
    for token in command.replace("'", " ").replace('"', " ").split():
        if token.endswith(".py"):
            cand = (run_cwd / token).resolve() if not Path(token).is_absolute() else Path(token)
            if cand.is_file():
                return cand
    return None


def format_diagnostics_block(diagnostics: list[Diagnostic], *, target: str) -> str:
    """Format blok teks '[LINT]' untuk ditulis ke log job (pre-flight)."""
    errs = sum(1 for d in diagnostics if d.severity == "error")
    warns = len(diagnostics) - errs
    lines = [
        "-" * 60,
        f"[LINT] Analisis kode statik ({target}): "
        f"{errs} error, {warns} peringatan.",
    ]
    if not diagnostics:
        lines.append("[LINT] Tidak ada masalah terdeteksi.")
    else:
        for d in diagnostics[:50]:
            tag = "ERROR " if d.severity == "error" else "WARN  "
            lines.append(f"[LINT] {tag} baris {d.line}:{d.col}  {d.message}")
        if len(diagnostics) > 50:
            lines.append(f"[LINT] ... dan {len(diagnostics) - 50} lainnya.")
        if errs:
            lines.append(
                "[LINT] Ada kemungkinan error; job tetap dijalankan, periksa pesan di atas."
            )
    lines.append("-" * 60)
    return "\n".join(lines) + "\n"


def preflight_lint_text(
    *,
    source_type: str,
    command: str,
    run_cwd: str | Path,
    working_dir: str | Path,
) -> str | None:
    """Hasilkan blok '[LINT]' untuk job (best-effort). None bila tak ada yang bisa dianalisis."""
    try:
        code = ""
        target = ""
        if source_type == "notebook":
            nb = next(Path(working_dir).glob("*.ipynb"), None)
            if nb is not None:
                code = extract_notebook_code(nb)
                target = nb.name
        else:
            entry = _find_entry_py(command, run_cwd)
            if entry is not None:
                code = entry.read_text(encoding="utf-8", errors="ignore")
                target = entry.name
        if not code.strip():
            return None
        diags = lint_code(code)
        return format_diagnostics_block(diags, target=target or "kode")
    except Exception:  # noqa: BLE001  -- pre-flight tak boleh menggagalkan job
        return None
