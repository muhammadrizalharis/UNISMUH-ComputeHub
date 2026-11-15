"""Peringatan sekali saat `keras` di-import pada image Python 3.10 (ch-compute:latest).

Keras >= 3.13 (berisi perbaikan keamanan) butuh Python 3.11+, sehingga image 3.10
tertahan di 3.12.x. Modul ini dimuat lewat `ch_keras_notice.pth`; ia hanya
menulis satu baris ke stderr lalu melepas dirinya — import keras tetap normal.
"""

import sys

_MSG = (
    "[ComputeHub] Perhatian: Keras di Python 3.10 belum mendapat semua perbaikan "
    "keamanan. Pilih Python 3.11 ke atas di form Submit Job / toolbar notebook. "
    "Jangan memuat model dari sumber yang tidak tepercaya.\n"
)


class _KerasNotice:
    def find_spec(self, name, path=None, target=None):
        if name == "keras" or name.startswith("keras."):
            try:
                sys.meta_path.remove(self)
            except ValueError:
                pass
            try:
                sys.stderr.write(_MSG)
            except Exception:
                pass
        return None


if sys.version_info < (3, 11) and not any(
    type(f).__name__ == "_KerasNotice" for f in sys.meta_path
):
    sys.meta_path.insert(0, _KerasNotice())
