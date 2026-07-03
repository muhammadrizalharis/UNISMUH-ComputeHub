"""Pasang shim `google.colab` ke site-packages venv aktif (idempoten).

Menyalin `colab_shim/__init__.py` dan `colab_shim/drive.py` ke
`<site-packages>/google/colab/` sehingga `from google.colab import drive`
berhasil dan memberi panduan (gdown / Upload) alih-alih ModuleNotFoundError.

Jalankan setelah membuat/membangun ulang venv:
    .venv/bin/python scripts/install_colab_shim.py

Keamanan: hanya menambah subpaket `colab` ke namespace package `google`
(PEP 420). Skrip MENOLAK berjalan bila `google` ternyata paket biasa
(punya __init__.py) demi menjaga google.protobuf / google.* lain.
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

SRC = Path(__file__).resolve().parent / "colab_shim"


def main() -> int:
    import google  # namespace package (google.protobuf, dll.)

    if getattr(google, "__file__", None) is not None:
        raise SystemExit(
            "BATAL: `google` bukan namespace package (ada __init__.py). "
            "Pemasangan dihentikan demi menjaga google.protobuf/google.*."
        )

    dest = Path(list(google.__path__)[0]) / "colab"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "drive.py"):
        shutil.copyfile(SRC / name, dest / name)

    # Verifikasi: shim ter-impor DAN namespace google tetap sehat.
    importlib.invalidate_caches()
    importlib.import_module("google.colab.drive")
    importlib.import_module("google.protobuf")
    print(f"OK: shim google.colab terpasang di {dest}")
    print("Verifikasi: import google.colab.drive OK; google.protobuf OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
