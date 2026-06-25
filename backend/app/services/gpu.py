"""Deteksi & monitoring GPU.

Sumber data:
  1. NVML (nvidia-ml-py)  -> akurat & cepat (diutamakan).
  2. fallback: parsing `nvidia-smi --query-gpu`.

Modul ini juga jadi pusat ENFORCEMENT GPU: kalau tidak ada GPU yang terlihat,
job tidak boleh dijalankan (lihat scheduler/executor).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MIB = 1024 * 1024

# Cache state NVML: None = belum dicoba, False = tidak tersedia, modul = tersedia.
_nvml_module = None


def _try_nvml():
    """Inisialisasi NVML sekali; kembalikan modul pynvml atau False."""
    global _nvml_module
    if _nvml_module is not None:
        return _nvml_module
    try:
        import pynvml  # disediakan paket nvidia-ml-py

        pynvml.nvmlInit()
        _nvml_module = pynvml
        logger.info("NVML aktif untuk monitoring GPU.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("NVML tidak tersedia (%s); fallback ke nvidia-smi.", exc)
        _nvml_module = False
    return _nvml_module


@dataclass
class GpuInfo:
    index: int
    name: str
    uuid: str = ""
    util_percent: float = 0.0
    mem_used_mb: float = 0.0
    mem_total_mb: float = 0.0
    temperature_c: float = 0.0
    power_w: float = 0.0

    @property
    def mem_free_mb(self) -> float:
        return max(0.0, self.mem_total_mb - self.mem_used_mb)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["mem_free_mb"] = self.mem_free_mb
        return d


def _decode(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _allowed_indices() -> set[int] | None:
    idx = settings.gpu_visible_indices
    return set(idx) if idx is not None else None


def _list_via_nvml(nvml, allowed: set[int] | None) -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    count = nvml.nvmlDeviceGetCount()
    for i in range(count):
        if allowed is not None and i not in allowed:
            continue
        handle = nvml.nvmlDeviceGetHandleByIndex(i)
        try:
            mem = nvml.nvmlDeviceGetMemoryInfo(handle)
            util = nvml.nvmlDeviceGetUtilizationRates(handle)
        except Exception as exc:  # noqa: BLE001
            logger.debug("NVML gagal baca GPU %d: %s", i, exc)
            continue

        try:
            temp = float(
                nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU)
            )
        except Exception:  # noqa: BLE001
            temp = 0.0
        try:
            power = nvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
        except Exception:  # noqa: BLE001
            power = 0.0
        try:
            uuid = _decode(nvml.nvmlDeviceGetUUID(handle))
        except Exception:  # noqa: BLE001
            uuid = ""

        gpus.append(
            GpuInfo(
                index=i,
                name=_decode(nvml.nvmlDeviceGetName(handle)),
                uuid=uuid,
                util_percent=float(util.gpu),
                mem_used_mb=mem.used / _MIB,
                mem_total_mb=mem.total / _MIB,
                temperature_c=temp,
                power_w=float(power),
            )
        )
    return gpus


def _list_via_smi(allowed: set[int] | None) -> list[GpuInfo]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    query = "index,name,uuid,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    try:
        proc = subprocess.run(
            [smi, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("nvidia-smi gagal: %s", exc)
        return []

    def _f(x: str) -> float:
        try:
            return float(x)
        except ValueError:
            return 0.0

    gpus: list[GpuInfo] = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        index = int(_f(parts[0]))
        if allowed is not None and index not in allowed:
            continue
        gpus.append(
            GpuInfo(
                index=index,
                name=parts[1],
                uuid=parts[2],
                util_percent=_f(parts[3]),
                mem_used_mb=_f(parts[4]),
                mem_total_mb=_f(parts[5]),
                temperature_c=_f(parts[6]),
                power_w=_f(parts[7]),
            )
        )
    return gpus


def list_gpus() -> list[GpuInfo]:
    """Daftar GPU yang boleh dipakai platform (terfilter GPU_VISIBLE_DEVICES)."""
    allowed = _allowed_indices()
    nvml = _try_nvml()
    if nvml:
        gpus = _list_via_nvml(nvml, allowed)
        if gpus:
            return gpus
    return _list_via_smi(allowed)


def gpu_count() -> int:
    return len(list_gpus())


def get_gpu(index: int) -> GpuInfo | None:
    """Ambil info 1 GPU berdasarkan index."""
    for gpu in list_gpus():
        if gpu.index == index:
            return gpu
    return None


def gpu_process_memory_mb(gpu_index: int, pids: set[int]) -> float:
    """Total VRAM (MB) yang dipakai proses-proses `pids` pada GPU `gpu_index`.

    Memakai NVML compute running processes. 0.0 bila NVML/akses tidak tersedia.
    """
    nvml = _try_nvml()
    if not nvml or not pids:
        return 0.0
    try:
        handle = nvml.nvmlDeviceGetHandleByIndex(gpu_index)
    except Exception:  # noqa: BLE001
        return 0.0

    total_bytes = 0
    for getter in (
        "nvmlDeviceGetComputeRunningProcesses_v3",
        "nvmlDeviceGetComputeRunningProcesses",
    ):
        fn = getattr(nvml, getter, None)
        if fn is None:
            continue
        try:
            procs = fn(handle)
        except Exception:  # noqa: BLE001
            continue
        for proc in procs:
            if proc.pid in pids and getattr(proc, "usedGpuMemory", None):
                total_bytes += proc.usedGpuMemory
        break
    return total_bytes / _MIB


def driver_info() -> dict:
    """Versi driver NVIDIA & CUDA (untuk laporan sistem)."""
    out = {"driver_version": "", "cuda_version": ""}
    nvml = _try_nvml()
    if not nvml:
        return out
    try:
        out["driver_version"] = _decode(nvml.nvmlSystemGetDriverVersion())
    except Exception:  # noqa: BLE001
        pass
    try:
        v = int(nvml.nvmlSystemGetCudaDriverVersion_v2())
        out["cuda_version"] = f"{v // 1000}.{(v % 1000) // 10}"
    except Exception:  # noqa: BLE001
        pass
    return out


def all_gpu_processes() -> list[tuple[int, int, float]]:
    """Semua proses (compute+graphics) di tiap GPU terlihat.

    Kembalikan list (gpu_index, pid, vram_mb). Inilah dasar "siapa memakai GPU"
    — termasuk proses di luar platform (mis. ComfyUI user lain).
    """
    nvml = _try_nvml()
    if not nvml:
        return []
    allowed = _allowed_indices()
    try:
        count = nvml.nvmlDeviceGetCount()
    except Exception:  # noqa: BLE001
        return []

    out: list[tuple[int, int, float]] = []
    getters = (
        "nvmlDeviceGetComputeRunningProcesses_v3",
        "nvmlDeviceGetComputeRunningProcesses",
        "nvmlDeviceGetGraphicsRunningProcesses_v3",
        "nvmlDeviceGetGraphicsRunningProcesses",
    )
    for i in range(count):
        if allowed is not None and i not in allowed:
            continue
        try:
            handle = nvml.nvmlDeviceGetHandleByIndex(i)
        except Exception:  # noqa: BLE001
            continue
        per_pid: dict[int, float] = {}
        seen_kind = {"compute": False, "graphics": False}
        for getter in getters:
            kind = "compute" if "Compute" in getter else "graphics"
            if seen_kind[kind]:
                continue  # sudah pakai versi _v3, jangan dobel
            fn = getattr(nvml, getter, None)
            if fn is None:
                continue
            try:
                procs = fn(handle)
            except Exception:  # noqa: BLE001
                continue
            seen_kind[kind] = True
            for proc in procs:
                mem = getattr(proc, "usedGpuMemory", None) or 0
                per_pid[proc.pid] = max(per_pid.get(proc.pid, 0.0), mem / _MIB)
        for pid, mb in per_pid.items():
            out.append((i, pid, mb))
    return out


def gpu_available() -> bool:
    """True bila ada minimal 1 GPU terlihat -> syarat WAJIB untuk eksekusi job."""
    return gpu_count() > 0


def pick_free_gpu(
    min_free_mb: float | None = None,
    busy_indices: set[int] | None = None,
) -> int | None:
    """Pilih GPU dengan VRAM bebas terbanyak yang memenuhi syarat.

    - busy_indices: index GPU yang sedang dipakai job platform (dihindari).
    - min_free_mb: minimal VRAM bebas; default dari settings.
    """
    if min_free_mb is None:
        min_free_mb = settings.GPU_MIN_FREE_MEMORY_MB
    busy = busy_indices or set()

    best_index: int | None = None
    best_free = -1.0
    for gpu in list_gpus():
        if gpu.index in busy:
            continue
        if gpu.mem_free_mb < min_free_mb:
            continue
        if gpu.mem_free_mb > best_free:
            best_free = gpu.mem_free_mb
            best_index = gpu.index
    return best_index


def usable_total_mb(gpu: GpuInfo) -> float:
    """VRAM total yang boleh dipesan platform di sebuah GPU (sisakan headroom)."""
    return max(0.0, gpu.mem_total_mb - settings.GPU_SHARE_HEADROOM_MB)


def pick_gpu_for(
    required_mb: float,
    exclude: set[int] | None = None,
) -> int | None:
    """Pilih GPU yang BISA BERBAGI: muat anggaran `required_mb` beban kerja baru.

    Inilah inti GPU-sharing. Sebuah GPU menerima beban kerja baru bila SEMUA syarat:
      1) jumlah beban kerja platform di GPU itu < GPU_MAX_WORKLOADS_PER_GPU
         (0 = tanpa batas jumlah), DAN
      2) anggaran terpakai + required_mb <= usable_total (cegah overcommit di antara
         beban kerja kita sendiri, walau belum sempat mengalokasi VRAM), DAN
      3) VRAM bebas NYATA (NVML) >= required_mb + headroom (jaga agar fisiknya muat
         sekarang — ikut memperhitungkan pemakai GPU di LUAR platform).

    Saat GPU_SHARE_ENABLED=False -> jatuh balik ke 1 beban kerja per GPU (perilaku lama).
    Mengembalikan index GPU terpilih, atau None bila tak ada yang muat.
    """
    from app.services import reservations  # impor lokal (hindari siklus saat modul muat)

    exclude = exclude or set()
    required_mb = max(0.0, float(required_mb or 0.0))
    headroom = settings.GPU_SHARE_HEADROOM_MB
    max_per_gpu = settings.GPU_MAX_WORKLOADS_PER_GPU if settings.GPU_SHARE_ENABLED else 1

    best_index: int | None = None
    best_room = -1.0
    for gpu in list_gpus():
        if gpu.index in exclude:
            continue
        cnt = reservations.count(gpu.index)
        if max_per_gpu > 0 and cnt >= max_per_gpu:
            continue
        usable = usable_total_mb(gpu)
        planned = reservations.planned_mb(gpu.index)
        if planned + required_mb > usable:
            continue
        # Jaga fisik: butuh VRAM bebas nyata cukup sekarang (akun pemakai luar).
        need_free = required_mb + headroom
        if gpu.mem_free_mb < need_free:
            continue
        # Sebar beban: pilih GPU dengan sisa anggaran terbesar (paling lega).
        room = usable - planned
        if room > best_room:
            best_room = room
            best_index = gpu.index
    return best_index


def shutdown() -> None:
    """Tutup NVML saat aplikasi berhenti."""
    global _nvml_module
    if _nvml_module and _nvml_module is not False:
        try:
            _nvml_module.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass
    _nvml_module = None
