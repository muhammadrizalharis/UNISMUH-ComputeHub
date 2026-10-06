"""Plafon VRAM per-proses DI DALAM container ComputeHub (job, kernel, Devbox).

Folder ini di-mount read-only ke `/opt/ch-vram` dan dimasukkan ke PYTHONPATH, sehingga
CPython otomatis mengimpor `sitecustomize` ini di setiap interpreter yang dijalankan
user. Tanpa env `CH_MAX_VRAM_MB` (> 0) modul ini tidak melakukan apa pun, jadi aman
untuk container CPU, proses pip, dan lingkungan Linux user di luar ComputeHub.

NVIDIA tidak menyediakan pembatas VRAM keras per-container, jadi plafon ditegakkan di
lapisan framework: PyTorch (`set_per_process_memory_fraction`) dan TensorFlow
(`LogicalDeviceConfiguration`). Melebihi plafon -> OutOfMemoryError pada proses user,
bukan proses user lain yang jadi korban.
"""

import builtins
import importlib.machinery
import importlib.util
import os
import sys

_MB = 1024.0 * 1024.0


def _cap_mb():
    try:
        nilai = float(os.environ.get("CH_MAX_VRAM_MB") or 0)
    except (TypeError, ValueError):
        return 0.0
    return nilai if nilai > 0 else 0.0


def _lapor(pesan):
    if os.environ.get("CH_VRAM_QUIET"):
        return
    try:
        sys.stderr.write("[ComputeHub] " + pesan + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _terapkan_torch(torch, cap_mb):
    """True bila sudah selesai diurus (termasuk saat GPU tidak ada)."""
    cuda = getattr(torch, "cuda", None)
    if cuda is None or not callable(getattr(cuda, "is_available", None)):
        return False
    if not cuda.is_available():
        return True
    jumlah = cuda.device_count()
    for idx in range(jumlah):
        total_mb = cuda.get_device_properties(idx).total_memory / _MB
        if total_mb <= 0 or cap_mb >= total_mb:
            continue
        cuda.set_per_process_memory_fraction(cap_mb / total_mb, idx)
    if jumlah:
        _lapor(
            "Plafon VRAM %d MB diterapkan pada %d GPU (kebijakan akun; "
            "minta tambahan ke admin bila kurang)." % (int(cap_mb), jumlah)
        )
    return True


def _terapkan_tensorflow(tf, cap_mb):
    config = getattr(tf, "config", None)
    if config is None:
        return False
    gpus = config.list_physical_devices("GPU")
    if not gpus:
        return True
    konfig = config.LogicalDeviceConfiguration(memory_limit=int(cap_mb))
    for gpu in gpus:
        config.set_logical_device_configuration(gpu, [konfig])
    _lapor("Plafon VRAM %d MB diterapkan pada %d GPU TensorFlow." % (int(cap_mb), len(gpus)))
    return True


def _pasang_hook(cap_mb):
    selesai = set()
    sedang = set()
    penangan = {"torch": _terapkan_torch, "tensorflow": _terapkan_tensorflow}
    impor_asli = builtins.__import__

    def __import__(name, globals=None, locals=None, fromlist=(), level=0):
        modul = impor_asli(name, globals, locals, fromlist, level)
        akar = name.split(".")[0] if level == 0 else ""
        fungsi = penangan.get(akar)
        if fungsi is None or akar in selesai or akar in sedang:
            return modul
        induk = sys.modules.get(akar)
        if induk is None:
            return modul
        spec = getattr(induk, "__spec__", None)
        if spec is not None and getattr(spec, "_initializing", False):
            return modul  # paket masih setengah terimpor: tunggu impor berikutnya
        # Penangan memanggil CUDA, yang mengimpor modul lain -> tanpa penjaga ini
        # hook memanggil dirinya sendiri sampai menggantung.
        sedang.add(akar)
        try:
            if fungsi(induk, cap_mb):
                selesai.add(akar)
        except Exception as exc:  # noqa: BLE001
            # Paket setengah terimpor / API versi lain: jangan ganggu proses user.
            _lapor("Plafon VRAM belum bisa dipasang pada %s (%s)." % (akar, exc))
            selesai.add(akar)
        finally:
            sedang.discard(akar)
        return modul

    builtins.__import__ = __import__


def _teruskan_ke_bawaan():
    """Modul ini membayangi sitecustomize bawaan image, jadi yang asli tetap dijalankan."""
    sendiri = os.path.dirname(os.path.abspath(__file__))
    jalur = [p for p in sys.path if p and os.path.abspath(p) != sendiri]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", jalur)
    if spec is None or spec.loader is None:
        return
    try:
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    except Exception:  # noqa: BLE001
        pass


_cap = _cap_mb()
if _cap > 0:
    try:
        _pasang_hook(_cap)
    except Exception:  # noqa: BLE001  — hook gagal TIDAK boleh menggagalkan proses user
        pass
try:
    _teruskan_ke_bawaan()
except Exception:  # noqa: BLE001
    pass
