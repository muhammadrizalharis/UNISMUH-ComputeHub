"""Autocomplete Python (jedi) untuk editor kode — statik, TANPA eksekusi kode user.

jedi menganalisis teks kode saja; tidak ada import/eval terhadap kode user, jadi
aman dipakai di server bersama. Dipanggil dari endpoint /lint/complete via
threadpool (jedi sinkron).
"""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_CODE_CHARS = 100_000
_MAX_ITEMS = 60


def complete(code: str, line: int, column: int) -> list[dict]:
    """Kembalikan saran pelengkapan pada posisi (line 1-based, column 0-based)."""
    if not code or len(code) > _MAX_CODE_CHARS:
        return []
    try:
        import jedi

        script = jedi.Script(code=code)
        comps = script.complete(line=line, column=column)
    except Exception as exc:  # noqa: BLE001 — posisi tak valid dll: bukan error fatal
        logger.debug("jedi complete gagal: %s", exc)
        return []
    out: list[dict] = []
    for c in comps[:_MAX_ITEMS]:
        try:
            out.append(
                {
                    "label": c.name,
                    "type": c.type or "text",
                    # Sisa teks yang perlu disisipkan dari posisi kursor.
                    "insert": c.complete if c.complete is not None else c.name,
                }
            )
        except Exception:  # noqa: BLE001
            continue
    return out
