"""Shim `google.colab.drive` — mount Google Drive ala Colab TIDAK didukung.

Di ComputeHub tidak ada infrastruktur Google Colab (OAuth + FUSE + server
Google), sehingga `drive.mount('/content/drive')` tak dapat memasang Drive.
Fungsi di sini menjaga kompatibilitas tanda tangan Colab, tetapi memberi
panduan alternatif dan berhenti dengan pesan yang jelas.
"""

from __future__ import annotations

_GUIDE = """\
[ComputeHub] `google.colab` hanya tersedia di Google Colab, bukan di server kampus ini,
jadi drive.mount('/content/drive') tidak bisa dijalankan di sini.

Cara mengakses data dari Google Drive di ComputeHub:
  1) File/folder Drive yang DI-SHARE (punya link publik) -> pakai gdown (sudah terpasang):
         import gdown
         gdown.download("https://drive.google.com/uc?id=FILE_ID", "data.csv", quiet=False)
         # folder: gdown.download_folder("https://drive.google.com/drive/folders/FOLDER_ID")
  2) File milik sendiri -> UPLOAD langsung lewat tombol Upload di ComputeHub,
     lalu baca dari path lokal, mis. pd.read_csv("data.csv").
"""


def mount(
    mountpoint: str = "/content/drive",
    force_remount: bool = False,
    timeout_ms: int = 120_000,
    **_kwargs: object,
) -> None:
    """Kompatibel tanda tangan Colab; cetak panduan lalu hentikan dengan jelas."""
    print(_GUIDE)
    raise RuntimeError(
        "google.colab.drive.mount tidak didukung di ComputeHub. Gunakan gdown untuk "
        "file Drive publik, atau fitur Upload (lihat panduan yang tercetak di atas)."
    )


def flush_and_unmount(*_args: object, **_kwargs: object) -> None:
    """No-op berpanduan (Drive tidak pernah benar-benar terpasang)."""
    print(_GUIDE)
