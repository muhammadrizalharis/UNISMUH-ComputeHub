"""TensorBoard per pengguna: grafik eksperimen (loss, akurasi, dst.) langsung di web.

Satu container CPU-saja per user (`ch-tb-<uid>`, image compute yang sudah memuat
tensorboard). Folder sumber di-mount READ-ONLY ke /logs, lalu backend mem-proxy-nya
di <domain>/tensorboard/<uid>/ (lihat routers/tensorboard_web.py).

KEAMANAN:
  - Sumber hanya folder milik user: /persist-nya sendiri atau folder kerja job miliknya.
    Path relatif ditolak bila memuat '..', karakter kontrol, atau komponen symlink.
  - Yang di-mount adalah AKAR sumber (bukan subfolder pilihan user), sehingga symlink
    yang ditanam user di dalamnya hanya ter-resolve di namespace container — tak bisa
    menunjuk berkas host. Mount read-only: TensorBoard tidak bisa mengubah apa pun.
  - Container tanpa GPU, cap-drop ALL, non-root, batas RAM/CPU/PID, di jaringan bridge
    ICC-off milik ComputeHub (hanya backend di host yang bisa menjangkaunya).
  - Mati otomatis bila tidak ada permintaan lewat proxy selama TENSORBOARD_IDLE_MINUTES.
    Selama tab terbuka, TensorBoard memuat ulang data tiap 30 detik sehingga tetap hidup.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services import provision
from app.services import workspace as workspace_svc

logger = get_logger(__name__)

CONTAINER_PREFIX = "ch-tb-"
_LABEL_USER = "ch-tb-user"
_LABEL_SOURCE = "ch-tb-source"
_LABEL_REL = "ch-tb-rel"
_MOUNT = "/logs"
_EVENT_MARK = "tfevents"
_RELOAD_SECONDS = 30
# Folder yang tak mungkin berisi log eksperimen tapi bisa sangat besar.
_SKIP_DIRS = {
    "__pycache__", "node_modules", "site-packages", "venv", "_pydeps", "Dokumen-AI",
}
_MAX_SCAN_ENTRIES = 20_000
_MAX_SCAN_DEPTH = 8
_MAX_RUNS = 100


class TensorboardError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(settings.TENSORBOARD_ENABLED)


def path_prefix() -> str:
    return "/" + (settings.TENSORBOARD_PATH or "/tensorboard").strip("/")


def base_path(user_id: int) -> str:
    return f"{path_prefix()}/{int(user_id)}/"


def container_name(user_id: int) -> str:
    return f"{CONTAINER_PREFIX}{int(user_id)}"


def normalize_rel(rel: str | None) -> str:
    """Path relatif aman ('' = akar). ValueError bila mencurigakan."""
    raw = (rel or "").replace("\\", "/").strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("Nama folder tidak valid.")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("Path di luar folder Anda.")
    if raw.startswith("/") and parts[:1] == ["persist"]:
        # Pengguna sering menyalin path dari kode (/persist/runs) — terima juga.
        parts = parts[1:]
    return "/".join(parts)


def check_folder(base: Path, rel: str) -> Path:
    """Folder `rel` di bawah `base`, tanpa komponen symlink. ValueError bila tidak sah."""
    if not base.is_dir() or base.is_symlink():
        raise ValueError("Folder sumber tidak ditemukan.")
    cur = base
    for part in [p for p in rel.split("/") if p]:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError("Folder berupa symlink tidak diizinkan.")
        if not cur.is_dir():
            raise ValueError(f"Folder '{rel}' tidak ditemukan.")
    return cur


def find_runs(base: Path, rel: str = "") -> dict:
    """Cari folder berisi berkas event TensorBoard di bawah base/rel (dibatasi, tanpa symlink)."""
    start = check_folder(base, rel)
    hasil: dict[str, float] = {}
    entri = 0
    truncated = False
    start_depth = len(start.parts)
    for root, dirs, files in os.walk(start, followlinks=False):
        depth = len(Path(root).parts) - start_depth
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in _SKIP_DIRS and depth < _MAX_SCAN_DEPTH
        ]
        entri += len(dirs) + len(files)
        terbaru = 0.0
        for f in files:
            if _EVENT_MARK in f and f.startswith("events.out."):
                try:
                    terbaru = max(terbaru, (Path(root) / f).lstat().st_mtime)
                except OSError:
                    continue
        if terbaru:
            hasil[Path(root).relative_to(base).as_posix()] = terbaru
        if entri > _MAX_SCAN_ENTRIES:
            truncated = True
            break
    runs = sorted(hasil.items(), key=lambda kv: kv[1], reverse=True)
    if len(runs) > _MAX_RUNS:
        truncated = True
    return {
        "runs": [
            {"path": "" if p == "." else p, "modified": m} for p, m in runs[:_MAX_RUNS]
        ],
        "truncated": truncated,
    }


async def _run(argv: list[str], timeout: float = 60) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="replace")
    except (OSError, asyncio.TimeoutError) as exc:
        return 1, str(exc)


def _docker(*args: str) -> list[str]:
    return [*settings.DOCKER_CMD.split(), *args]


@dataclass
class TbInstance:
    user_id: int
    source: str          # "persist" atau "job:<id>"
    rel: str
    ip: str
    started_at: float
    last_access: float

    def info(self) -> dict:
        idle = max(0, int(settings.TENSORBOARD_IDLE_MINUTES)) * 60
        return {
            "running": True,
            "source": self.source,
            "path": self.rel,
            "url": base_path(self.user_id),
            "started_at": self.started_at,
            "idle_seconds": int(time.time() - self.last_access),
            "idle_timeout_seconds": idle,
        }


class TensorboardManager:
    def __init__(self) -> None:
        self._inst: dict[int, TbInstance] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------ siklus hidup
    async def start(self) -> None:
        if not enabled():
            # Fitur dimatikan: jangan biarkan container sisa jalan tanpa reaper.
            rc, out = await _run(_docker("ps", "-aq", "--filter", f"label={_LABEL_USER}"))
            if rc == 0 and out.split():
                await _run(_docker("rm", "-f", *out.split()))
            return
        await self._adopt()
        self._task = asyncio.create_task(self._reaper(), name="tensorboard-reaper")

    async def stop(self) -> None:
        # Container dibiarkan hidup: diadopsi lagi saat backend menyala.
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _adopt(self) -> None:
        rc, out = await _run(_docker(
            "ps", "-a", "--filter", f"label={_LABEL_USER}", "--format",
            '{{.Names}}|{{.State}}|{{.Label "' + _LABEL_USER + '"}}|{{.Label "'
            + _LABEL_SOURCE + '"}}|{{.Label "' + _LABEL_REL + '"}}',
        ))
        if rc != 0:
            return
        now = time.time()
        for line in out.splitlines():
            parts = line.strip().split("|")
            if len(parts) != 5 or not parts[0].startswith(CONTAINER_PREFIX):
                continue
            name, state, uid_s, source, rel = parts
            try:
                uid = int(uid_s)
            except ValueError:
                continue
            if name != container_name(uid):
                continue
            ip = await self._container_ip(name) if state == "running" else ""
            if not ip:
                await _run(_docker("rm", "-f", name))
                continue
            self._inst[uid] = TbInstance(uid, source, rel, ip, now, now)
            logger.info("TensorBoard user #%d diadopsi (%s:%s).", uid, source, rel)

    async def _reaper(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
                await self.reap_idle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reaper TensorBoard gagal: %s", exc)

    async def reap_idle(self, now: float | None = None) -> list[int]:
        now = time.time() if now is None else now
        batas = max(1, int(settings.TENSORBOARD_IDLE_MINUTES)) * 60
        mati = [uid for uid, i in list(self._inst.items()) if now - i.last_access > batas]
        for uid in mati:
            logger.info("TensorBoard user #%d dimatikan (tidak dibuka %d menit).", uid, batas // 60)
            await self.shutdown(uid)
        return mati

    # ------------------------------------------------------------ akses
    def touch(self, user_id: int) -> None:
        inst = self._inst.get(int(user_id))
        if inst is not None:
            inst.last_access = time.time()

    def target(self, user_id: int) -> tuple[str, int] | None:
        inst = self._inst.get(int(user_id))
        if inst is None or not inst.ip:
            return None
        return inst.ip, int(settings.TENSORBOARD_PORT)

    def status(self, user_id: int) -> dict:
        inst = self._inst.get(int(user_id))
        if inst is None:
            return {"running": False, "enabled": enabled()}
        return {**inst.info(), "enabled": enabled()}

    def active_count(self) -> int:
        return len(self._inst)

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(int(user_id), asyncio.Lock())

    # ------------------------------------------------------------ nyalakan / matikan
    async def ensure(self, user_id: int, base: Path, source: str, rel: str) -> dict:
        """Nyalakan (atau pakai ulang) TensorBoard user untuk folder base/rel."""
        if not enabled():
            raise TensorboardError("Fitur TensorBoard sedang dinonaktifkan admin.")
        uid = int(user_id)
        async with self._lock(uid):
            inst = self._inst.get(uid)
            if inst is not None and inst.source == source and inst.rel == rel:
                if await self._is_running(container_name(uid)):
                    inst.last_access = time.time()
                    return inst.info()
                self._inst.pop(uid, None)
            if inst is not None:
                await self.shutdown(uid, locked=True)
            if self.active_count() >= max(1, int(settings.TENSORBOARD_MAX_ACTIVE)):
                raise TensorboardError(
                    "Kapasitas TensorBoard sedang penuh. Coba lagi beberapa menit lagi."
                )
            await provision.ensure_network()
            name = container_name(uid)
            await _run(_docker("rm", "-f", name))
            rc, out = await _run(self.run_argv(uid, base, source, rel), timeout=120)
            if rc != 0:
                logger.warning("TensorBoard user #%d gagal dibuat: %s", uid, out.strip()[-500:])
                raise TensorboardError("TensorBoard gagal dinyalakan. Coba lagi sebentar lagi.")
            ip = await self._container_ip(name)
            if not ip or not await self._wait_ready(uid, ip):
                rc_l, logs = await _run(_docker("logs", "--tail", "20", name))
                logger.warning("TensorBoard user #%d tidak siap: %s", uid, logs.strip()[-800:])
                await _run(_docker("rm", "-f", name))
                raise TensorboardError("TensorBoard tidak merespons. Coba lagi sebentar lagi.")
            now = time.time()
            inst = TbInstance(uid, source, rel, ip, now, now)
            self._inst[uid] = inst
            logger.info("TensorBoard user #%d menyala (%s:%s).", uid, source, rel or ".")
            return inst.info()

    async def shutdown(self, user_id: int, locked: bool = False) -> bool:
        uid = int(user_id)

        async def _do() -> bool:
            ada = self._inst.pop(uid, None) is not None
            rc, _ = await _run(_docker("rm", "-f", container_name(uid)))
            return ada or rc == 0

        if locked:
            return await _do()
        async with self._lock(uid):
            return await _do()

    def run_argv(self, user_id: int, base: Path, source: str, rel: str) -> list[str]:
        logdir = f"{_MOUNT}/{rel}" if rel else _MOUNT
        args = [
            "run", "-d", "--rm",
            "--name", container_name(user_id),
            "--label", f"{_LABEL_USER}={int(user_id)}",
            "--label", f"{_LABEL_SOURCE}={source}",
            "--label", f"{_LABEL_REL}={rel}",
            "--init",
            *provision.network_argv(),
            *provision.hardening_argv(),
            "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
            "--pids-limit", "256",
            "--cpus", str(max(0.25, float(settings.TENSORBOARD_CPUS))),
            "--memory", f"{max(512, int(settings.TENSORBOARD_MEMORY_MB))}m",
            "-e", "HOME=/tmp",
            "-e", "PYTHONUNBUFFERED=1",
            "-e", "TF_CPP_MIN_LOG_LEVEL=2",
            "-e", "CUDA_VISIBLE_DEVICES=",
            "-e", "OMP_NUM_THREADS=1",
            "-v", f"{base}:{_MOUNT}:ro",
            "-w", "/tmp",
            settings.DOCKER_USER_IMAGE,
            "tensorboard",
            "--logdir", logdir,
            "--host", "0.0.0.0",
            "--port", str(int(settings.TENSORBOARD_PORT)),
            "--path_prefix", base_path(user_id).rstrip("/"),
            "--reload_interval", str(_RELOAD_SECONDS),
        ]
        return _docker(*args)

    async def _container_ip(self, name: str) -> str:
        rc, out = await _run(_docker(
            "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", name,
        ))
        if rc != 0:
            return ""
        ips = out.split()
        return ips[0] if ips else ""

    async def _is_running(self, name: str) -> bool:
        rc, out = await _run(_docker("inspect", "-f", "{{.State.Running}}", name))
        return rc == 0 and out.strip() == "true"

    async def _wait_ready(self, user_id: int, ip: str) -> bool:
        url = f"http://{ip}:{int(settings.TENSORBOARD_PORT)}{base_path(user_id)}data/environment"
        batas = time.monotonic() + max(10, int(settings.TENSORBOARD_START_TIMEOUT))
        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.monotonic() < batas:
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return True
                except httpx.HTTPError:
                    pass
                if not await self._is_running(container_name(user_id)):
                    return False
                await asyncio.sleep(1.5)
        return False


def persist_base(user_id: int) -> Path:
    return workspace_svc.ensure_root(user_id)


tensorboard_manager = TensorboardManager()
