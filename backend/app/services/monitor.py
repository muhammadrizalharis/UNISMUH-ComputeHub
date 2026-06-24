"""Monitoring sistem (CPU/RAM/GPU) + sampler latar belakang.

Catatan: orkestrasi (web server + scheduler) memakai CPU sangat ringan.
Yang DILARANG memakai CPU adalah *komputasi job* (lihat executor) — itu wajib GPU.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import psutil

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.monitoring import ResourceSample, SampleScope
from app.schemas.monitoring import GpuOut, SystemSnapshot
from app.services import gpu as gpu_svc

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
        self, job_id: int, pid: int, gpu_index: int, interval: float
    ) -> None:
        self.job_id = job_id
        self.pid = pid
        self.gpu_index = gpu_index
        self.interval = max(1.0, interval)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.peak_ram_mb = 0.0
        self.peak_vram_mb = 0.0
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
            "avg_gpu_util_percent": (
                self._util_sum / self._util_count if self._util_count else None
            ),
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
        vram = gpu_svc.gpu_process_memory_mb(self.gpu_index, pids)
        gpu = gpu_svc.get_gpu(self.gpu_index)
        util = gpu.util_percent if gpu else 0.0

        self.peak_ram_mb = max(self.peak_ram_mb, ram)
        self.peak_vram_mb = max(self.peak_vram_mb, vram)
        self._util_sum += util
        self._util_count += 1

        async with AsyncSessionLocal() as session:
            session.add(
                ResourceSample(
                    scope=SampleScope.job,
                    job_id=self.job_id,
                    cpu_percent=0.0,
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
