"""Pinjam VRAM dari kantong untuk aplikasi di luar ComputeHub (project Docker Compose).

Super admin mendaftarkan project compose (mis. ``local-ai``) sebagai *peminjam*.
Sejak itu VRAM yang dipakai container project tersebut diperlakukan seperti beban kerja
ComputeHub oleh kantong VRAM:

* otomatis — tiap tick kantong, proses GPU dipetakan PID -> cgroup -> container ->
  project. Selama container peminjam memakai VRAM, kantong melepas bagian itu (plus
  sisa bebas BUFFER agar model bisa tumbuh). Begitu VRAM-nya kembali 0 (model
  di-unload / container berhenti), kantong memegangnya lagi.
* pinjam di muka (opsional) — container peminjam memanggil ``POST
  /api/v1/vram-pocket/borrow`` sebelum memuat model agar VRAM sudah dilepas lebih
  dulu. Pinjaman TANPA batas waktu: selesai saat dikembalikan, atau otomatis setelah
  pemakaian GPU project berhenti (diam ``IDLE_RETURN_SECONDS``), atau bila model tak
  pernah dimuat dalam ``START_GRACE_SECONDS``.

Pinjaman tidak masuk registri reservasi (slot/admisi devbox & job tidak berubah);
kantong hanya menghitungnya sebagai "VRAM terpakai ComputeHub".
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)

IDLE_RETURN_SECONDS = 60.0
START_GRACE_SECONDS = 600.0
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_HOME_RE = re.compile(r"^/home/([^/]+)")


@dataclass
class Lease:
    id: str
    project: str
    gpu_index: int
    mb: float
    by: str
    created: float = field(default_factory=time.monotonic)
    created_wall: float = field(default_factory=time.time)
    seen_used: bool = False
    idle_since: float | None = None


_lock = threading.Lock()
_usage: dict[tuple[str, int], float] = {}
_containers: dict[str, set[str]] = {}
_owners: dict[str, str] = {}
_leases: dict[str, Lease] = {}


# ------------------------------------------------------------------ konfigurasi
def _path():
    from app.services import vram_pocket

    return vram_pocket.base_dir() / "borrowers.json"


def valid_project(name: str) -> bool:
    return bool(_PROJECT_RE.match(name or ""))


def get_projects() -> list[str]:
    from app.services import vram_pocket

    data = vram_pocket._read_json(_path()) or {}
    return sorted({p for p in data.get("projects", []) if valid_project(p)})


def set_projects(projects: list[str], actor: str) -> list[str]:
    from app.services import vram_pocket

    clean = sorted({p.strip().lower() for p in projects if valid_project(p.strip().lower())})
    vram_pocket._write_json(
        _path(), {"projects": clean, "updated_by": actor, "updated_at": time.time()}
    )
    with _lock:
        for lid in [lid for lid, l in _leases.items() if l.project not in clean]:
            _leases.pop(lid, None)
    return clean


# ------------------------------------------------------------------ pemindaian
def _owner_from_workdir(path: str) -> str:
    m = _HOME_RE.match(path or "")
    return m.group(1) if m else ""


def scan(procs: list[tuple[int, int, float]] | None = None, now: float | None = None) -> None:
    """Petakan VRAM proses GPU ke project peminjam + kelola umur pinjaman."""
    from app.services import container_identity

    projects = set(get_projects())
    now = time.monotonic() if now is None else now
    usage: dict[tuple[str, int], float] = {}
    conts: dict[str, set[str]] = {}
    owners: dict[str, str] = {}
    if projects:
        if procs is None:
            from app.services import gpu as gpu_svc

            procs = gpu_svc.all_gpu_processes()
        for gi, pid, mb in procs:
            cid = container_identity.container_id_for_pid(pid)
            if not cid:
                continue
            meta = container_identity.lookup(cid) or {}
            proj = meta.get("project", "")
            if proj not in projects:
                continue
            usage[(proj, gi)] = usage.get((proj, gi), 0.0) + float(mb or 0.0)
            conts.setdefault(proj, set()).add(meta.get("name", "") or cid[:12])
            owners.setdefault(proj, _owner_from_workdir(meta.get("working_dir", "")))

    with _lock:
        _usage.clear()
        _usage.update(usage)
        _containers.clear()
        _containers.update(conts)
        _owners.update(owners)
        for lid, l in list(_leases.items()):
            if l.project not in projects:
                _leases.pop(lid, None)
                continue
            if usage.get((l.project, l.gpu_index), 0.0) > 0:
                l.seen_used = True
                l.idle_since = None
            elif l.seen_used:
                if l.idle_since is None:
                    l.idle_since = now
                if now - l.idle_since >= IDLE_RETURN_SECONDS:
                    _leases.pop(lid, None)
                    logger.info("Pinjaman VRAM %s (%s) kembali ke kantong: GPU diam", lid, l.project)
            elif now - l.created >= START_GRACE_SECONDS:
                _leases.pop(lid, None)
                logger.info("Pinjaman VRAM %s (%s) kembali ke kantong: tak pernah dipakai", lid, l.project)


# ------------------------------------------------------------------ untuk kantong
def _per_project(gpu_index: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for (proj, gi), mb in _usage.items():
        if gi == gpu_index:
            out[proj] = mb
    for l in _leases.values():
        if l.gpu_index == gpu_index:
            out[l.project] = out.get(l.project, 0.0)
    for proj in list(out):
        leased = sum(l.mb for l in _leases.values() if l.project == proj and l.gpu_index == gpu_index)
        out[proj] = max(out[proj], leased)
    return out


def used_mb(gpu_index: int) -> float:
    """VRAM yang dipinjam peminjam di GPU ini (pemakaian nyata atau pinjaman, terbesar)."""
    with _lock:
        return sum(_per_project(gpu_index).values())


def holders(gpu_index: int) -> int:
    with _lock:
        return sum(1 for mb in _per_project(gpu_index).values() if mb > 0)


# ------------------------------------------------------------------ pinjaman API
def _pick_gpu(project: str) -> int | None:
    from app.services import gpu as gpu_svc
    from app.services import vram_pocket

    with _lock:
        running = sorted(
            ((mb, gi) for (p, gi), mb in _usage.items() if p == project), reverse=True
        )
    if running:
        return running[0][1]
    held = vram_pocket.held_map()
    gpus = [g.index for g in gpu_svc.list_gpus()]
    if not gpus:
        return None
    return max(gpus, key=lambda i: (held.get(i, 0.0), -i))


def borrow(project: str, mb: float, gpu_index: int | None, by: str) -> Lease:
    if project not in get_projects():
        raise PermissionError(f"Project '{project}' bukan peminjam cadangan VRAM")
    if gpu_index is None:
        gpu_index = _pick_gpu(project)
    if gpu_index is None:
        raise RuntimeError("Tidak ada GPU terlihat")
    lease = Lease(
        id=uuid.uuid4().hex[:12], project=project, gpu_index=int(gpu_index),
        mb=max(0.0, float(mb)), by=by,
    )
    with _lock:
        _leases[lease.id] = lease
    logger.info("Pinjam VRAM %s: %s %.0f MB di GPU %d (oleh %s)", lease.id, project, lease.mb, lease.gpu_index, by)
    _notify()
    return lease


def give_back(project: str, lease_id: str | None = None) -> int:
    """Kembalikan pinjaman project (satu id, atau semua). Mengembalikan jumlahnya."""
    with _lock:
        ids = [
            lid for lid, l in _leases.items()
            if l.project == project and (lease_id is None or lid == lease_id)
        ]
        for lid in ids:
            _leases.pop(lid, None)
    if ids:
        logger.info("Pinjaman VRAM %s dikembalikan: %s", project, ",".join(ids))
        _notify()
    return len(ids)


def _notify() -> None:
    try:
        from app.services import vram_pocket

        vram_pocket.on_claims_changed()
    except Exception:  # noqa: BLE001
        pass


def _lease_dict(l: Lease, now: float) -> dict:
    return {
        "id": l.id,
        "project": l.project,
        "gpu_index": l.gpu_index,
        "mb": round(l.mb, 1),
        "by": l.by,
        "since": l.created_wall,
        "dipakai": l.seen_used,
        "diam_detik": round(now - l.idle_since, 1) if l.idle_since else 0.0,
    }


def status(project: str | None = None) -> dict:
    now = time.monotonic()
    projects = get_projects()
    with _lock:
        rows = []
        for p in projects:
            if project and p != project:
                continue
            per_gpu = {gi: round(mb, 1) for (pp, gi), mb in sorted(_usage.items()) if pp == p}
            rows.append(
                {
                    "project": p,
                    "owner": _owners.get(p, ""),
                    "containers": sorted(_containers.get(p, set())),
                    "used_mb": per_gpu,
                    "used_total_mb": round(sum(per_gpu.values()), 1),
                    "leases": [
                        _lease_dict(l, now) for l in _leases.values() if l.project == p
                    ],
                }
            )
    return {
        "projects": rows,
        "idle_return_seconds": IDLE_RETURN_SECONDS,
        "start_grace_seconds": START_GRACE_SECONDS,
    }


def _reset_for_tests() -> None:
    with _lock:
        _usage.clear()
        _containers.clear()
        _owners.clear()
        _leases.clear()
