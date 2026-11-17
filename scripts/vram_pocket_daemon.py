#!/usr/bin/env python3
"""Daemon "kantong VRAM" ComputeHub (berjalan di HOST sebagai systemd user service).

Memegang VRAM atas nama ComputeHub supaya tidak keburu diambil proses lain di server
bersama. Target per GPU ditulis backend ke ``target.json``; daemon ini hanya patuh:

- pegangan > target  -> lepas SEGERA (potongan demi potongan);
- VRAM bebas < ``min_free_mb`` GPU itu -> lepas SEGERA sampai bebas lagi. Inilah
  "lepas duluan": beban kerja ComputeHub yang sedang tumbuh langsung kebagian tanpa
  menunggu backend (reaksi ~0,5 detik);
- pegangan < target  -> tambah PERLAHAN (1 potongan/tick) dan HANYA dari VRAM yang
  memang bebas (tak pernah merebut memori proses lain);
- target basi (backend mati / kantong dimatikan) -> lepas semuanya.

Status (pegangan per GPU) ditulis ke ``status.json`` untuk dibaca backend & UI admin.
Tanpa dependensi selain libcuda (driver API via ctypes).
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import sys
import time
from pathlib import Path

os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")  # samakan urutan dgn NVML

MB = 1024 * 1024
BASE = Path(os.environ.get("CH_POCKET_DIR", "~/.computehub/vram-pocket")).expanduser()
CHUNK_MB = int(os.environ.get("CH_POCKET_CHUNK_MB", "512"))
KEEP_FREE_MB = int(os.environ.get("CH_POCKET_KEEP_FREE_MB", "1024"))
TICK = float(os.environ.get("CH_POCKET_TICK", "0.5"))
STALE_SECONDS = float(os.environ.get("CH_POCKET_STALE_SECONDS", "60"))

_stop = False


def _on_signal(_sig, _frm):
    global _stop
    _stop = True


class Cuda:
    def __init__(self) -> None:
        self.lib = ctypes.CDLL("libcuda.so.1")
        self._chk(self.lib.cuInit(0), "cuInit")
        n = ctypes.c_int()
        self._chk(self.lib.cuDeviceGetCount(ctypes.byref(n)), "cuDeviceGetCount")
        self.count = n.value

    @staticmethod
    def _chk(rc: int, what: str) -> None:
        if rc != 0:
            raise RuntimeError(f"{what} gagal (CUresult={rc})")

    def device(self, idx: int) -> ctypes.c_int:
        dev = ctypes.c_int()
        self._chk(self.lib.cuDeviceGet(ctypes.byref(dev), idx), "cuDeviceGet")
        return dev

    def retain(self, dev: ctypes.c_int) -> ctypes.c_void_p:
        ctx = ctypes.c_void_p()
        self._chk(self.lib.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), dev), "ctxRetain")
        return ctx

    def release(self, dev: ctypes.c_int) -> None:
        self.lib.cuDevicePrimaryCtxRelease_v2(dev)

    def use(self, ctx: ctypes.c_void_p) -> None:
        self._chk(self.lib.cuCtxSetCurrent(ctx), "cuCtxSetCurrent")

    def free_mb(self) -> float:
        free = ctypes.c_size_t()
        total = ctypes.c_size_t()
        self._chk(self.lib.cuMemGetInfo_v2(ctypes.byref(free), ctypes.byref(total)), "memGetInfo")
        return free.value / MB

    def alloc(self, mb: int) -> int | None:
        ptr = ctypes.c_uint64()
        rc = self.lib.cuMemAlloc_v2(ctypes.byref(ptr), ctypes.c_size_t(mb * MB))
        return ptr.value if rc == 0 else None

    def free(self, ptr: int) -> None:
        self.lib.cuMemFree_v2(ctypes.c_uint64(ptr))


class Gpu:
    def __init__(self, cuda: Cuda, idx: int) -> None:
        self.cuda = cuda
        self.idx = idx
        self.dev = cuda.device(idx)
        self.ctx: ctypes.c_void_p | None = None
        self.chunks: list[int] = []

    @property
    def held_mb(self) -> int:
        return len(self.chunks) * CHUNK_MB

    def _enter(self) -> None:
        if self.ctx is None:
            self.ctx = self.cuda.retain(self.dev)
        self.cuda.use(self.ctx)

    def step(self, target_mb: float, min_free_mb: float) -> None:
        if target_mb <= 0 and not self.chunks:
            self.close()
            return
        self._enter()
        while self.chunks and self.held_mb > target_mb:
            self.cuda.free(self.chunks.pop())
        while self.chunks and self.cuda.free_mb() < min_free_mb:
            self.cuda.free(self.chunks.pop())
        if self.held_mb + CHUNK_MB <= target_mb:
            if self.cuda.free_mb() >= CHUNK_MB + min_free_mb:
                ptr = self.cuda.alloc(CHUNK_MB)
                if ptr is not None:
                    self.chunks.append(ptr)
        if not self.chunks and target_mb <= 0:
            self.close()

    def close(self) -> None:
        if self.ctx is None:
            return
        self.cuda.use(self.ctx)
        while self.chunks:
            self.cuda.free(self.chunks.pop())
        self.cuda.use(ctypes.c_void_p())
        self.cuda.release(self.dev)
        self.ctx = None


def _per_gpu(raw) -> dict[int, float]:
    out: dict[int, float] = {}
    for k, v in (raw or {}).items():
        try:
            out[int(k)] = max(0.0, float(v))
        except (TypeError, ValueError):
            continue
    return out


def read_targets() -> tuple[dict[int, float], dict[int, float], str]:
    try:
        data = json.loads((BASE / "target.json").read_text())
    except FileNotFoundError:
        return {}, {}, "target.json belum ada"
    except (OSError, ValueError) as exc:
        return {}, {}, f"target.json tak terbaca: {exc}"
    if not data.get("enabled"):
        return {}, {}, ""
    if time.time() - float(data.get("ts") or 0) > STALE_SECONDS:
        return {}, {}, "target basi (backend tidak memperbarui)"
    return _per_gpu(data.get("targets_mb")), _per_gpu(data.get("min_free_mb")), ""


def write_status(gpus: list[Gpu], note: str) -> None:
    payload = {
        "ts": time.time(),
        "pid": os.getpid(),
        "chunk_mb": CHUNK_MB,
        "held_mb": {str(g.idx): g.held_mb for g in gpus},
        "context": {str(g.idx): g.ctx is not None for g in gpus},
        "note": note,
    }
    tmp = BASE / "status.json.tmp"
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, BASE / "status.json")


def main() -> int:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    BASE.mkdir(parents=True, exist_ok=True)
    cuda = Cuda()
    gpus = [Gpu(cuda, i) for i in range(cuda.count)]
    print(f"vram-pocket: {cuda.count} GPU, potongan {CHUNK_MB} MB, dir {BASE}", flush=True)
    last_note = None
    while not _stop:
        targets, min_free, note = read_targets()
        for g in gpus:
            try:
                g.step(targets.get(g.idx, 0.0), min_free.get(g.idx, KEEP_FREE_MB))
            except Exception as exc:  # noqa: BLE001 — satu GPU bermasalah tak boleh mematikan daemon
                note = f"GPU {g.idx}: {exc}"
        if note != last_note:
            if note:
                print(f"vram-pocket: {note}", flush=True)
            last_note = note
        try:
            write_status(gpus, note)
        except OSError:
            pass
        time.sleep(TICK)
    for g in gpus:
        try:
            g.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        write_status(gpus, "daemon berhenti")
    except OSError:
        pass
    print("vram-pocket: berhenti, semua VRAM dilepas.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
