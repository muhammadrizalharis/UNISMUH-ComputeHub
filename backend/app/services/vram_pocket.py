"""Kantong VRAM: ComputeHub "memesan" sejumlah VRAM di server bersama.

Daemon host (scripts/computehub_devbox.py) memegang VRAM sungguhan; modul ini yang
menentukan BERAPA yang dipegang di tiap GPU dan menulisnya ke ``target.json``.

Aturan target per GPU (lihat ``compute_targets``):
  1) ukuran kantong dibagi rata ke GPU; GPU yang tak muat (sudah dipakai pengguna
     lain) dialihkan ke GPU lain;
  2) bagian yang SUDAH dipakai beban kerja ComputeHub di GPU itu tidak dipegang lagi
     (kantong "terpakai" oleh user kita);
  3) GPU yang sedang ditempati beban kerja ComputeHub selalu disisakan VRAM bebas
     sebesar BUFFER (daemon melepas begitu sisa bebas turun) -> kode user yang tumbuh
     langsung kebagian dari kantong;
  4) kantong tak pernah merebut VRAM yang sedang dipakai proses lain.

Saat admisi, VRAM yang dipegang kantong dihitung sebagai VRAM bebas milik ComputeHub.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

STATUS_STALE_SECONDS = 15.0


def base_dir() -> Path:
    return settings.docker_user_data_root.parent / "vram-pocket"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ konfigurasi
@dataclass
class PocketConfig:
    enabled: bool
    size_mb: float
    updated_by: str = ""
    updated_at: float = 0.0


def get_config() -> PocketConfig:
    data = _read_json(base_dir() / "config.json") or {}
    try:
        size = float(data.get("size_mb", settings.VRAM_POCKET_DEFAULT_SIZE_MB))
    except (TypeError, ValueError):
        size = settings.VRAM_POCKET_DEFAULT_SIZE_MB
    return PocketConfig(
        enabled=bool(data.get("enabled", settings.VRAM_POCKET_DEFAULT_ENABLED)),
        size_mb=max(0.0, size),
        updated_by=str(data.get("updated_by") or ""),
        updated_at=float(data.get("updated_at") or 0.0),
    )


def set_config(enabled: bool | None, size_mb: float | None, actor: str) -> PocketConfig:
    cur = get_config()
    new = PocketConfig(
        enabled=cur.enabled if enabled is None else bool(enabled),
        size_mb=cur.size_mb if size_mb is None else max(0.0, float(size_mb)),
        updated_by=actor,
        updated_at=time.time(),
    )
    _write_json(base_dir() / "config.json", new.__dict__)
    refresh()
    return new


# ------------------------------------------------------------------ status daemon
def daemon_status() -> dict | None:
    """Isi status.json bila masih segar (daemon hidup), selain itu None."""
    data = _read_json(base_dir() / "status.json")
    if not data:
        return None
    if time.time() - float(data.get("ts") or 0) > STATUS_STALE_SECONDS:
        return None
    return data


def held_map() -> dict[int, float]:
    """VRAM yang sedang dipegang kantong per GPU (0 bila daemon mati)."""
    st = daemon_status()
    if not st:
        return {}
    out: dict[int, float] = {}
    for k, v in (st.get("held_mb") or {}).items():
        try:
            out[int(k)] = max(0.0, float(v))
        except (TypeError, ValueError):
            continue
    return out


def held_mb(gpu_index: int) -> float:
    """Pegangan kantong di GPU ini (0 bila kantong mati / loop backend tak berjalan)."""
    if _task is None or not get_config().enabled:
        return 0.0
    return held_map().get(int(gpu_index), 0.0)


# ------------------------------------------------------------------ logika target
@dataclass
class GpuView:
    index: int
    total_mb: float
    used_mb: float       # NVML: termasuk pegangan kantong & beban kerja ComputeHub
    held_mb: float       # dipegang kantong
    ch_used_mb: float    # VRAM nyata beban kerja ComputeHub
    ch_holders: int      # jumlah beban kerja ComputeHub yang memegang GPU ini


def compute_targets(
    gpus: list[GpuView],
    size_mb: float,
    enabled: bool,
    *,
    buffer_mb: float,
    keep_free_mb: float,
    chunk_mb: float,
) -> dict[int, dict]:
    """Hitung target pegangan per GPU. Fungsi murni (mudah diuji)."""
    out: dict[int, dict] = {}
    for g in gpus:
        out[g.index] = {
            "share_mb": 0.0,
            "target_mb": 0.0,
            "min_free_mb": buffer_mb if g.ch_holders > 0 else keep_free_mb,
            "capacity_mb": 0.0,
        }
    if not enabled or size_mb <= 0 or not gpus:
        return out

    # Kapasitas kantong di tiap GPU = semua VRAM kecuali milik pengguna lain & sisa wajib.
    cap: dict[int, float] = {}
    for g in gpus:
        outsider = max(0.0, g.used_mb - g.held_mb - g.ch_used_mb)
        cap[g.index] = max(0.0, g.total_mb - outsider - out[g.index]["min_free_mb"])
        out[g.index]["capacity_mb"] = cap[g.index]

    # Bagi rata; sisa dari GPU yang tak muat dialihkan ke GPU lain (water-filling).
    share = {g.index: 0.0 for g in gpus}
    remaining = float(size_mb)
    open_idx = [g.index for g in gpus]
    while remaining > 1e-6 and open_idx:
        each = remaining / len(open_idx)
        next_open = []
        for i in open_idx:
            give = min(each, cap[i] - share[i])
            share[i] += give
            remaining -= give
            if cap[i] - share[i] > 1e-6:
                next_open.append(i)
        if len(next_open) == len(open_idx) and remaining > 1e-6 and each <= 1e-6:
            break
        open_idx = next_open

    for g in gpus:
        # Bagian kantong yang sudah dipakai user ComputeHub tak perlu dipegang lagi.
        want = share[g.index] - g.ch_used_mb
        if chunk_mb > 0:
            want = (want // chunk_mb) * chunk_mb
        out[g.index]["share_mb"] = round(share[g.index], 1)
        out[g.index]["target_mb"] = max(0.0, want)
    return out


def _views() -> list[GpuView]:
    from app.services import gpu as gpu_svc
    from app.services import reservations, vram_borrow

    held = held_map()
    return [
        GpuView(
            index=g.index,
            total_mb=g.mem_total_mb,
            used_mb=g.mem_used_mb,
            held_mb=held.get(g.index, 0.0),
            # Peminjam (project compose terdaftar) dihitung seperti beban kerja kita.
            ch_used_mb=reservations.used_mb(g.index) + vram_borrow.used_mb(g.index),
            ch_holders=reservations.holders(g.index) + vram_borrow.holders(g.index),
        )
        for g in gpu_svc.list_gpus()
    ]


_last: dict = {}


def refresh() -> dict[int, dict]:
    """Hitung ulang target & tulis target.json untuk daemon."""
    global _last
    cfg = get_config()
    views = _views()
    targets = compute_targets(
        views,
        cfg.size_mb,
        cfg.enabled,
        buffer_mb=settings.VRAM_POCKET_BUFFER_MB,
        keep_free_mb=settings.VRAM_POCKET_KEEP_FREE_MB,
        chunk_mb=settings.VRAM_POCKET_CHUNK_MB,
    )
    _write_json(
        base_dir() / "target.json",
        {
            "enabled": cfg.enabled,
            "ts": time.time(),
            "size_mb": cfg.size_mb,
            "targets_mb": {str(i): t["target_mb"] for i, t in targets.items()},
            "min_free_mb": {str(i): t["min_free_mb"] for i, t in targets.items()},
        },
    )
    _last = {"views": views, "targets": targets}
    return targets


def on_claims_changed() -> None:
    if _task is not None:
        try:
            refresh()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Kantong VRAM gagal refresh: %s", exc)


def status() -> dict:
    """Ringkasan untuk UI admin."""
    cfg = get_config()
    st = daemon_status()
    try:
        targets = refresh()
        views = {v.index: v for v in _last.get("views", [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kantong VRAM: status gagal dihitung: %s", exc)
        targets, views = {}, {}
    held = held_map()
    per = []
    for i, t in sorted(targets.items()):
        v = views.get(i)
        per.append(
            {
                "index": i,
                "total_mb": round(v.total_mb, 1) if v else 0.0,
                "used_mb": round(v.used_mb, 1) if v else 0.0,
                "free_mb": round(max(0.0, v.total_mb - v.used_mb), 1) if v else 0.0,
                "held_mb": held.get(i, 0.0),
                "target_mb": t["target_mb"],
                "share_mb": t["share_mb"],
                "ch_used_mb": round(v.ch_used_mb, 1) if v else 0.0,
                "ch_holders": v.ch_holders if v else 0,
            }
        )
    return {
        "enabled": cfg.enabled,
        "size_mb": cfg.size_mb,
        "updated_by": cfg.updated_by,
        "updated_at": cfg.updated_at or None,
        "daemon_alive": st is not None,
        "daemon_note": (st or {}).get("note", ""),
        "held_total_mb": sum(held.values()) if cfg.enabled else 0.0,
        "ch_used_total_mb": round(sum(p["ch_used_mb"] for p in per), 1),
        "buffer_mb": settings.VRAM_POCKET_BUFFER_MB,
        "keep_free_mb": settings.VRAM_POCKET_KEEP_FREE_MB,
        "gpus": per,
        "borrow": _borrow_status(),
    }


def _borrow_status() -> dict:
    from app.services import vram_borrow

    try:
        return vram_borrow.status()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Status peminjam kantong gagal: %s", exc)
        return {"projects": []}


# ------------------------------------------------------------------ loop
_task: asyncio.Task | None = None


async def _loop() -> None:
    interval = max(0.5, float(settings.VRAM_POCKET_TICK_SECONDS))
    from app.services import vram_borrow

    while True:
        try:
            await asyncio.to_thread(vram_borrow.scan)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("Kantong VRAM: pindai peminjam gagal: %s", exc)
        try:
            await asyncio.to_thread(refresh)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Kantong VRAM: refresh gagal: %s", exc)
        await asyncio.sleep(interval)


async def start() -> None:
    global _task
    if _task is None:
        _task = asyncio.create_task(_loop(), name="vram-pocket")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _task = None
