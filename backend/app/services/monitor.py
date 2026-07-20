"""Monitoring sistem (CPU/RAM/GPU) + sampler latar belakang.

Catatan: orkestrasi (web server + scheduler) memakai CPU sangat ringan.
Yang DILARANG memakai CPU adalah *komputasi job* (lihat executor) — itu wajib GPU.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import signal

import psutil

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.monitoring import ResourceSample, SampleScope
from app.schemas.monitoring import GpuOut, SystemSnapshot
from app.services import gpu as gpu_svc
from app.services import reservations

logger = get_logger(__name__)

_MB = 1024 * 1024


def system_snapshot() -> SystemSnapshot:
    """Snapshot real-time CPU/RAM/GPU."""
    vm = psutil.virtual_memory()
    gpus = gpu_svc.list_gpus()
    return SystemSnapshot(
        timestamp=dt.datetime.now(dt.timezone.utc),
        cpu_percent=psutil.cpu_percent(interval=None),
        cpu_cores=psutil.cpu_count(logical=True) or 0,
        memory_used_mb=(vm.total - vm.available) / _MB,
        memory_total_mb=vm.total / _MB,
        gpu_available=len(gpus) > 0,
        gpus=[GpuOut(**g.as_dict()) for g in gpus],
    )


class ResourceMonitor:
    """Sampler periodik yang menyimpan ResourceSample ke DB."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="resource-monitor")
        logger.info(
            "ResourceMonitor jalan (interval %.0fs).",
            settings.MONITOR_SAMPLE_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _loop(self) -> None:
        # Inisialisasi baseline cpu_percent.
        psutil.cpu_percent(interval=None)
        interval = max(2.0, settings.MONITOR_SAMPLE_INTERVAL_SECONDS)
        while not self._stop.is_set():
            try:
                await self._sample_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sampling monitoring gagal: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _sample_once(self) -> None:
        snap = system_snapshot()
        rows: list[ResourceSample] = []

        if snap.gpus:
            for g in snap.gpus:
                rows.append(
                    ResourceSample(
                        scope=SampleScope.system,
                        cpu_percent=snap.cpu_percent,
                        memory_used_mb=snap.memory_used_mb,
                        memory_total_mb=snap.memory_total_mb,
                        gpu_index=g.index,
                        gpu_util_percent=g.util_percent,
                        gpu_mem_used_mb=g.mem_used_mb,
                        gpu_mem_total_mb=g.mem_total_mb,
                        gpu_temperature_c=g.temperature_c,
                        gpu_power_w=g.power_w,
                    )
                )
        else:
            rows.append(
                ResourceSample(
                    scope=SampleScope.system,
                    cpu_percent=snap.cpu_percent,
                    memory_used_mb=snap.memory_used_mb,
                    memory_total_mb=snap.memory_total_mb,
                )
            )

        async with AsyncSessionLocal() as session:
            session.add_all(rows)
            await session.commit()


# Instance global (dipakai lifespan & router).
monitor = ResourceMonitor()


class JobSampler:
    """Mengukur RAM/VRAM/GPU & menulis ResourceSample(scope=job) selama job jalan.

    Aggregat (peak RAM, peak VRAM, rata-rata util GPU) dikembalikan saat stop().
    """

    def __init__(
        self,
        job_id: int,
        pid: int,
        gpu_index: int,
        interval: float,
        *,
        max_ram_mb: float = 0.0,
        max_vram_mb: float = 0.0,
        log_path: str | None = None,
    ) -> None:
        self.job_id = job_id
        self.pid = pid
        self.gpu_index = gpu_index
        self.interval = max(1.0, interval)
        self.max_ram_mb = max(0.0, float(max_ram_mb or 0.0))
        self.max_vram_mb = max(0.0, float(max_vram_mb or 0.0))
        self.log_path = log_path
        self.kill_reason: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.peak_ram_mb = 0.0
        self.peak_vram_mb = 0.0
        self.peak_cpu_percent = 0.0
        self._proc_cache: dict[int, psutil.Process] = {}
        self._util_sum = 0.0
        self._util_count = 0

    def start(self) -> None:
        self._task = asyncio.create_task(
            self._loop(), name=f"job-sampler-{self.job_id}"
        )

    async def stop(self) -> dict:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            except Exception:  # noqa: BLE001
                pass
        return {
            "peak_ram_mb": self.peak_ram_mb or None,
            "peak_vram_mb": self.peak_vram_mb or None,
            "peak_cpu_percent": self.peak_cpu_percent or None,
            "avg_gpu_util_percent": (
                self._util_sum / self._util_count if self._util_count else None
            ),
            "kill_reason": self.kill_reason,
        }

    def _proc_pids(self) -> set[int]:
        try:
            p = psutil.Process(self.pid)
            procs = [p, *p.children(recursive=True)]
            return {pr.pid for pr in procs if pr.is_running()}
        except psutil.Error:
            return set()

    @staticmethod
    def _ram_mb(pids: set[int]) -> float:
        total = 0
        for pid in pids:
            try:
                total += psutil.Process(pid).memory_info().rss
            except psutil.Error:
                continue
        return total / _MB

    def _cpu_percent(self, pids: set[int]) -> float:
        """Total CPU% job + anak proses (bisa >100% utk multi-core/thread).

        psutil.Process.cpu_percent(interval=None) menghitung delta sejak panggilan
        terakhir pada instance YANG SAMA -> cache Process per-pid. Proses baru:
        panggilan pertama = baseline (0), nilai valid mulai sampel berikutnya.
        """
        total = 0.0
        for pid in pids:
            proc = self._proc_cache.get(pid)
            if proc is None:
                try:
                    proc = psutil.Process(pid)
                    proc.cpu_percent(interval=None)
                    self._proc_cache[pid] = proc
                except psutil.Error:
                    continue
            else:
                try:
                    total += proc.cpu_percent(interval=None)
                except psutil.Error:
                    self._proc_cache.pop(pid, None)
        for dead in [p for p in self._proc_cache if p not in pids]:
            self._proc_cache.pop(dead, None)
        return total

    def _enforce(self, ram: float, vram: float, pids: set[int]) -> None:
        """Auto-stop bila RAM/VRAM job melebihi plafon peran (0 = tanpa batas)."""
        if self.kill_reason is not None:
            return
        # Mode LUNAK: JANGAN bunuh job karena RAM/VRAM (user minta melambat/melar, bukan
        # dihentikan). Plafon keras RAM (docker --memory) tetap jaga node; VRAM diserahkan
        # ke CUDA (tak bisa di-throttle dari luar).
        if settings.SOFT_LIMIT_ENABLED:
            return
        reason: str | None = None
        if self.max_ram_mb > 0 and ram > self.max_ram_mb:
            reason = (
                f"RAM {ram:.0f} MB melebihi plafon {self.max_ram_mb:.0f} MB"
            )
        elif self.max_vram_mb > 0 and vram > self.max_vram_mb:
            reason = (
                f"VRAM {vram:.0f} MB melebihi plafon {self.max_vram_mb:.0f} MB"
            )
        if reason is None:
            return
        self.kill_reason = reason
        logger.warning("Job #%d dihentikan otomatis: %s", self.job_id, reason)
        self._log_breach(reason)
        self._kill(pids)

    def _log_breach(self, reason: str) -> None:
        if not self.log_path:
            return
        try:
            with open(self.log_path, "ab", buffering=0) as f:
                f.write(
                    f"\n{'-' * 60}\n[LIMIT] {reason} -> job DIHENTIKAN otomatis "
                    f"oleh sistem.\n".encode()
                )
        except Exception:  # noqa: BLE001
            pass

    def _kill(self, pids: set[int]) -> None:
        # Job dijalankan dengan start_new_session -> pid = pemimpin grup proses.
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGKILL)
            return
        except Exception:  # noqa: BLE001
            pass
        for pid in pids or {self.pid}:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:  # noqa: BLE001
                continue

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._sample_once()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Sampling job #%d gagal: %s", self.job_id, exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    async def _sample_once(self) -> None:
        pids = self._proc_pids()
        if not pids:
            return
        ram = self._ram_mb(pids)
        cpu = self._cpu_percent(pids)
        vram = gpu_svc.gpu_process_memory_mb(self.gpu_index, pids)
        gpu = gpu_svc.get_gpu(self.gpu_index)
        util = gpu.util_percent if gpu else 0.0

        self.peak_ram_mb = max(self.peak_ram_mb, ram)
        self.peak_vram_mb = max(self.peak_vram_mb, vram)
        self.peak_cpu_percent = max(self.peak_cpu_percent, cpu)
        self._util_sum += util
        self._util_count += 1

        # Laporkan VRAM nyata ke registry (untuk penempatan sharing + tampilan).
        reservations.update_usage(f"job:{self.job_id}", vram)

        self._enforce(ram, vram, pids)

        async with AsyncSessionLocal() as session:
            session.add(
                ResourceSample(
                    scope=SampleScope.job,
                    job_id=self.job_id,
                    cpu_percent=cpu,
                    memory_used_mb=ram,
                    memory_total_mb=0.0,
                    gpu_index=self.gpu_index,
                    gpu_util_percent=util,
                    gpu_mem_used_mb=vram,
                    gpu_mem_total_mb=gpu.mem_total_mb if gpu else 0.0,
                    gpu_temperature_c=gpu.temperature_c if gpu else 0.0,
                    gpu_power_w=gpu.power_w if gpu else 0.0,
                )
            )
            await session.commit()
