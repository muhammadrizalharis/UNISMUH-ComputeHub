"""Sesi INTERAKTIF (notebook/console ala Colab) dengan kernel Jupyter hidup.

Setiap sesi = 1 kernel IPython yang dipasang (pin) ke 1 GPU lewat
CUDA_VISIBLE_DEVICES, sehingga eksekusi sel tetap WAJIB di GPU. Kernel
mempertahankan state antar-sel (variabel tetap hidup) — seperti Google Colab.

Penjagaan server bersama:
  - GPU yang dipakai sesi di-RESERVE (lihat reservations.py) supaya job batch
    tidak memakai GPU yang sama.
  - Idle reaper mematikan kernel yang menganggur untuk membebaskan GPU.
  - Batas jumlah sesi serempak & batas waktu eksekusi per-sel (anti runaway).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from queue import Empty
from typing import Awaitable, Callable

from jupyter_client.manager import AsyncKernelManager

from app.core.config import settings
from app.core.logging import get_logger
from app.services import gpu as gpu_svc
from app.services import reservations

logger = get_logger(__name__)

KERNEL_NAME = "computehub"
_ALLOWED_MIMES = (
    "text/plain",
    "text/html",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "image/svg+xml",
    "application/json",
)
_MAX_STREAM_CHARS = 200_000  # batasi 1 pesan output agar WS tidak kebanjiran

OnMsg = Callable[[dict], Awaitable[None]]


def _clean_data(data: dict) -> dict:
    out: dict = {}
    for mime in _ALLOWED_MIMES:
        if mime in data:
            val = data[mime]
            if isinstance(val, str) and len(val) > _MAX_STREAM_CHARS:
                val = val[:_MAX_STREAM_CHARS] + "\n…(dipotong)"
            out[mime] = val
    return out


def _kernel_env(gpu_index: int) -> dict[str, str]:
    """Environment kernel: GPU dipaksa + footprint CPU diminimalkan."""
    env = os.environ.copy()
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    env["NVIDIA_VISIBLE_DEVICES"] = str(gpu_index)
    env["GPU_DEVICE_ORDINAL"] = str(gpu_index)
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    env["PYTHONUNBUFFERED"] = "1"
    return env


class KernelSession:
    """Satu kernel IPython hidup, ter-pin ke satu GPU."""

    def __init__(self, user_id: int, gpu_index: int) -> None:
        self.id = uuid.uuid4().hex
        self.user_id = user_id
        self.gpu_index = gpu_index
        self.created_at = time.time()
        self.last_active = time.time()
        self.busy = False
        self.exec_count = 0
        self._km: AsyncKernelManager | None = None
        self._kc = None
        self._lock = asyncio.Lock()
        self._workdir = (settings.jobs_path / "_interactive" / self.id)

    # ----------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._workdir.mkdir(parents=True, exist_ok=True)
        self._km = AsyncKernelManager(kernel_name=KERNEL_NAME)
        await self._km.start_kernel(
            env=_kernel_env(self.gpu_index), cwd=str(self._workdir)
        )
        self._kc = self._km.client()
        self._kc.start_channels()
        await self._kc.wait_for_ready(
            timeout=settings.INTERACTIVE_STARTUP_TIMEOUT_SECONDS
        )
        logger.info(
            "Kernel interaktif %s siap (user=%s, GPU=%s).",
            self.id, self.user_id, self.gpu_index,
        )

    async def shutdown(self) -> None:
        try:
            if self._kc is not None:
                self._kc.stop_channels()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._km is not None:
                await self._km.shutdown_kernel(now=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal shutdown kernel %s: %s", self.id, exc)
        finally:
            reservations.release(self.gpu_index)
            logger.info("Kernel interaktif %s dimatikan (GPU %s bebas).", self.id, self.gpu_index)

    async def interrupt(self) -> None:
        if self._km is not None:
            await self._km.interrupt_kernel()

    async def restart(self) -> None:
        async with self._lock:
            if self._km is not None:
                await self._km.restart_kernel(now=True)
                await self._kc.wait_for_ready(
                    timeout=settings.INTERACTIVE_STARTUP_TIMEOUT_SECONDS
                )
                self.exec_count = 0
                self.last_active = time.time()

    @property
    def is_alive(self) -> bool:
        return self._km is not None

    def info(self) -> dict:
        return {
            "session_id": self.id,
            "gpu_index": self.gpu_index,
            "busy": self.busy,
            "execution_count": self.exec_count,
            "idle_seconds": round(time.time() - self.last_active, 1),
        }

    # ----------------------------------------------------------- execute
    async def execute(self, code: str, on_msg: OnMsg) -> dict:
        """Jalankan satu sel; streaming output via on_msg(...) (awaitable)."""
        max_seconds = max(5, settings.INTERACTIVE_MAX_EXEC_SECONDS)
        async with self._lock:
            self.busy = True
            self.last_active = time.time()
            kc = self._kc
            status = "ok"
            try:
                msg_id = kc.execute(code, allow_stdin=False, store_history=True)
                deadline = time.monotonic() + max_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        await self.interrupt()
                        await on_msg({
                            "type": "error",
                            "ename": "TimeoutError",
                            "evalue": f"Eksekusi melebihi {max_seconds}s — dihentikan.",
                            "traceback": [],
                        })
                        status = "error"
                        break
                    try:
                        msg = await kc.get_iopub_msg(timeout=min(remaining, 1.0))
                    except (Empty, asyncio.TimeoutError):
                        continue
                    if msg.get("parent_header", {}).get("msg_id") != msg_id:
                        continue
                    mtype = msg["header"]["msg_type"]
                    content = msg["content"]
                    if mtype == "status":
                        if content.get("execution_state") == "idle":
                            break
                    elif mtype == "stream":
                        text = content.get("text", "")
                        if len(text) > _MAX_STREAM_CHARS:
                            text = text[:_MAX_STREAM_CHARS] + "\n…(dipotong)"
                        await on_msg({
                            "type": "stream",
                            "name": content.get("name", "stdout"),
                            "text": text,
                        })
                    elif mtype in ("execute_result", "display_data"):
                        await on_msg({
                            "type": "result",
                            "data": _clean_data(content.get("data", {})),
                            "execution_count": content.get("execution_count"),
                        })
                    elif mtype == "execute_input":
                        self.exec_count = content.get("execution_count", self.exec_count)
                    elif mtype == "error":
                        status = "error"
                        await on_msg({
                            "type": "error",
                            "ename": content.get("ename", ""),
                            "evalue": content.get("evalue", ""),
                            "traceback": content.get("traceback", []),
                        })
                # ambil balasan shell (status final) tanpa menggantung lama
                try:
                    while True:
                        reply = await kc.get_shell_msg(timeout=0.5)
                        if reply.get("parent_header", {}).get("msg_id") == msg_id:
                            self.exec_count = reply["content"].get(
                                "execution_count", self.exec_count
                            )
                            break
                except (Empty, asyncio.TimeoutError):
                    pass
            finally:
                self.busy = False
                self.last_active = time.time()
            return {"status": status, "execution_count": self.exec_count}


class KernelSessionManager:
    """Mengelola seluruh sesi interaktif + reaper idle."""

    def __init__(self) -> None:
        self._sessions: dict[str, KernelSession] = {}
        self._reaper: asyncio.Task | None = None
        self._spec_ready = False
        self._create_lock = asyncio.Lock()

    def _ensure_kernelspec(self) -> None:
        if self._spec_ready:
            return
        base = Path("_jkernel").resolve()
        kdir = base / "kernels" / KERNEL_NAME
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "kernel.json").write_text(
            json.dumps({
                "argv": [
                    sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}",
                ],
                "display_name": "ComputeHub",
                "language": "python",
            }),
            encoding="utf-8",
        )
        os.environ["JUPYTER_PATH"] = str(base) + os.pathsep + os.environ.get("JUPYTER_PATH", "")
        self._spec_ready = True

    async def start(self) -> None:
        self._ensure_kernelspec()
        self._reaper = asyncio.create_task(self._reap_loop(), name="kernel-reaper")
        logger.info(
            "KernelSessionManager siap (maks %d sesi, idle timeout %ds).",
            settings.INTERACTIVE_MAX_SESSIONS,
            settings.INTERACTIVE_IDLE_TIMEOUT_SECONDS,
        )

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reaper = None
        for sess in list(self._sessions.values()):
            await self._drop(sess)

    @property
    def reserved_gpus(self) -> set[int]:
        return {s.gpu_index for s in self._sessions.values()}

    def get(self, session_id: str, user_id: int) -> KernelSession | None:
        sess = self._sessions.get(session_id)
        if sess is not None and sess.user_id == user_id:
            return sess
        return None

    def list_for(self, user_id: int) -> list[dict]:
        return [s.info() for s in self._sessions.values() if s.user_id == user_id]

    async def create(self, user_id: int) -> KernelSession:
        if not settings.INTERACTIVE_ENABLED:
            raise RuntimeError("Sesi interaktif dinonaktifkan.")
        async with self._create_lock:
            # Pakai ulang sesi milik user bila masih hidup (1 kernel per user).
            for sess in self._sessions.values():
                if sess.user_id == user_id and sess.is_alive:
                    sess.last_active = time.time()
                    return sess
            if len(self._sessions) >= settings.INTERACTIVE_MAX_SESSIONS:
                raise RuntimeError(
                    "Semua slot sesi interaktif sedang dipakai. Coba lagi sebentar lagi."
                )
            busy = reservations.reserved_indices()
            try:
                from app.services.scheduler import scheduler

                busy = busy | set(scheduler.busy_gpus)
            except Exception:  # noqa: BLE001
                pass
            gpu_index = gpu_svc.pick_free_gpu(
                min_free_mb=settings.GPU_MIN_FREE_MEMORY_MB, busy_indices=busy
            )
            if gpu_index is None:
                raise RuntimeError(
                    "Tidak ada GPU bebas untuk sesi interaktif (semua sedang dipakai)."
                )
            reservations.reserve(gpu_index)
            sess = KernelSession(user_id=user_id, gpu_index=gpu_index)
            try:
                await sess.start()
            except Exception:
                reservations.release(gpu_index)
                raise
            self._sessions[sess.id] = sess
            return sess

    async def shutdown_session(self, session_id: str, user_id: int) -> bool:
        sess = self.get(session_id, user_id)
        if sess is None:
            return False
        await self._drop(sess)
        return True

    async def _drop(self, sess: KernelSession) -> None:
        self._sessions.pop(sess.id, None)
        try:
            await sess.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal menutup sesi %s: %s", sess.id, exc)

    async def _reap_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            timeout = settings.INTERACTIVE_IDLE_TIMEOUT_SECONDS
            if timeout <= 0:
                continue
            now = time.time()
            for sess in list(self._sessions.values()):
                if not sess.busy and (now - sess.last_active) > timeout:
                    logger.info("Sesi %s idle > %ds -> dimatikan.", sess.id, timeout)
                    await self._drop(sess)


# Instance global (dipakai lifespan & router).
kernel_manager = KernelSessionManager()
