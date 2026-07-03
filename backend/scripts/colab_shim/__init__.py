"""Shim `google.colab` untuk ComputeHub (paket ini KHUSUS Google Colab).

`google.colab` hanya ada di runtime Google Colab. Saat mahasiswa menyalin
notebook Colab yang memuat `from google.colab import drive`, tanpa shim ini
mereka akan mendapat `ModuleNotFoundError` yang membingungkan. Shim ini
membuat impor tersebut berhasil, lalu `drive.mount(...)` memberi PANDUAN yang
jelas (pakai gdown atau fitur Upload) alih-alih error mentah.

Dipasang ke site-packages oleh `backend/scripts/install_colab_shim.py`
(idempoten; jalankan ulang setelah venv dibangun ulang).

PENTING: JANGAN pernah membuat `google/__init__.py`. `google` harus tetap
namespace package (PEP 420) agar `google.protobuf` / `google.*` lain (dipakai
TensorFlow dll.) tidak rusak.
"""

__all__ = ["drive"]
