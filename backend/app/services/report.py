"""Laporan penggunaan resource untuk admin.

Menggabungkan DUA sudut pandang:
  1. OS-level (server-wide): siapa (user OS) memakai GPU/CPU/RAM saat ini —
     termasuk proses di luar platform. Mirip `nvidia-smi`/`top`.
  2. Platform-level: statistik job per akun ComputeHub.

Plus: laporan DETAIL per-user (13 bagian) dengan ANALISIS WORKLOAD otomatis
(fleksibel — mendeteksi apa yang dikerjakan: OCR, training, diffusion, API,
notebook, dll.) dan ekspor HTML (siap cetak ke PDF).

Catatan CPU: scan proses di-cache (REPORT_CACHE_TTL) agar polling admin tidak
membebani CPU server bersama.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html as html_mod
import os
import platform
import socket
import time

import psutil
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services import gpu as gpu_svc

logger = get_logger(__name__)

_MB = 1024 * 1024
_TOP_LIMIT = 12


# --------------------------------------------------------------------------- #
#  Pemakaian DISK per user (du /home) — MAHAL, jadi DI-CACHE + refresh latar   #
# --------------------------------------------------------------------------- #
_DISK_TTL = 1800.0  # 30 menit: du /home mahal -> jangan dihitung tiap poll
_disk_cache: dict = {"ts": 0.0, "data": None, "computing": False}


def _sudo_prefix_du() -> list[str]:
    """['sudo','-n'] bila sudo ada (utk baca home user lain) else []."""
    import shutil as _sh

    return ["sudo", "-n"] if _sh.which("sudo") else []


async def _compute_disk() -> dict:
    """Hitung total disk (df /) + ukuran tiap home user (du -bxd1 /home). BLOKIR ~menit."""
    import shutil as _sh

    total, used, free = _sh.disk_usage("/")
    users: list[dict] = []
    argv = [*_sudo_prefix_du(), "du", "-bxd1", "/home"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=900)
        for line in (out or b"").decode(errors="replace").splitlines():
            parts = line.split("\t")
            if len(parts) != 2 or not parts[0].strip().isdigit():
                continue
            path = parts[1].rstrip("/")
            if path in ("/home", ""):
                continue
            users.append({"user": os.path.basename(path), "bytes": int(parts[0])})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hitung disk per-user gagal: %s", exc)
    users.sort(key=lambda u: u["bytes"], reverse=True)
    return {
        "total_bytes": int(total),
        "used_bytes": int(used),
        "free_bytes": int(free),
        "used_percent": round(used / total * 100, 1) if total else 0.0,
        "users": users,
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


async def disk_usage() -> dict:
    """Pemakaian disk total + per-user (home). Hasil DI-CACHE 30 mnt; bila basi,
    dihitung ULANG DI LATAR (kembalikan data lama dulu agar endpoint tak nge-hang).
    """
    now = time.time()
    data = _disk_cache["data"]
    fresh = data is not None and now - _disk_cache["ts"] < _DISK_TTL
    if not fresh and not _disk_cache["computing"]:
        _disk_cache["computing"] = True

        async def _bg() -> None:
            try:
                _disk_cache["data"] = await _compute_disk()
                _disk_cache["ts"] = time.time()
            finally:
                _disk_cache["computing"] = False

        asyncio.create_task(_bg())
    if data is not None:
        return {**data, "computing": _disk_cache["computing"]}
    return {
        "total_bytes": 0,
        "used_bytes": 0,
        "free_bytes": 0,
        "used_percent": 0.0,
        "users": [],
        "computed_at": None,
        "computing": True,
    }


# --------------------------------------------------------------------------- #
#  Analisis workload (deteksi "apa yang dikerjakan")                          #
# --------------------------------------------------------------------------- #
# (type, label, [keyword pada command/exe])
_WORKLOAD_RULES: list[tuple[str, str, list[str]]] = [
    ("ocr", "Ekstraksi / OCR", ["easyocr", "paddleocr", "tesseract", "extract_ocr", "craft", "ocr"]),
    ("diffusion", "Generatif gambar (diffusion)", ["comfyui", "stable-diffusion", "sd-webui", "automatic1111", "invokeai", "wgp.py", "diffusers", "flux", "fooocus"]),
    ("llm", "LLM (inferensi/training)", ["vllm", "llama", "mistral", "ollama", "text-generation", "peft", "trl", "bitsandbytes"]),
    ("training", "Training model", ["train", "--epoch", "finetune", "fine-tune", "lightning", "accelerate launch", "xgboost", "sklearn"]),
    ("jupyter", "Jupyter / Notebook", ["ipykernel", "jupyter", "jupyterlab", "notebook"]),
    ("api", "API / Web server", ["uvicorn", "gunicorn", "hypercorn", "flask", "fastapi", "waitress", "celery"]),
    ("vscode", "VS Code Remote", ["vscode-server", ".vscode-server", "pylance", "code-server", "copilot", "tsserver", "eslintserver"]),
    ("frontend", "Node / Frontend", ["vite", "webpack", "next", "nuxt", "npm", "yarn", "pnpm", "node "]),
    ("scraping", "Scraping / Otomasi", ["scrapy", "selenium", "playwright", "crawl", "scrape"]),
    ("media", "Media / Computer Vision", ["ffmpeg", "opencv", "cv2", "moviepy"]),
    ("data", "Pengolahan data", ["pandas", "numpy", "preprocess", "dask", "spark", "etl"]),
    ("service", "Service sistem", ["redis", "postgres", "mysql", "mongod", "nginx", "containerd", "dockerd", "systemd", "sshd"]),
]

_WORKLOAD_HINT: dict[str, str] = {
    "ocr": "Pipeline OCR (deteksi+pengenalan teks). Biasanya CPU-intensive saat preprocessing.",
    "diffusion": "Image generation (Stable Diffusion / ComfyUI). VRAM besar, GPU-bound.",
    "llm": "Model bahasa besar — butuh VRAM besar; throughput bergantung batching.",
    "training": "Pelatihan model — idealnya GPU-bound; pastikan DataLoader tidak jadi bottleneck CPU.",
    "jupyter": "Sesi interaktif Jupyter/IPython kernel.",
    "api": "Server API/web (long-running). CPU idle saat tidak ada request.",
    "frontend": "Proses Node.js (dev server/bundler).",
    "vscode": "VS Code Remote-SSH (editor + language server).",
    "scraping": "Otomasi/scraping web.",
    "media": "Pemrosesan media/computer-vision (FFmpeg/OpenCV).",
    "data": "Pemrosesan data numerik (pandas/numpy).",
    "service": "Layanan sistem latar belakang.",
    "python": "Skrip Python umum.",
    "other": "Proses umum.",
}


def _python_script(command: str) -> str:
    for tok in command.replace("=", " ").split():
        if tok.endswith(".py"):
            return tok.split("/")[-1]
    return ""


def analyze_workload(command: str, name: str = "") -> dict:
    """Deteksi jenis pekerjaan dari command/nama proses (fleksibel)."""
    text = f"{command} {name}".lower()
    for wtype, label, kws in _WORKLOAD_RULES:
        if any(kw in text for kw in kws):
            return {"type": wtype, "label": label, "hint": _WORKLOAD_HINT.get(wtype, "")}
    script = _python_script(command)
    if script:
        return {"type": "python", "label": f"Skrip Python ({script})", "hint": _WORKLOAD_HINT["python"]}
    if "python" in text:
        return {"type": "python", "label": "Skrip Python", "hint": _WORKLOAD_HINT["python"]}
    base = (name or "proses").split("/")[-1]
    return {"type": "other", "label": base or "Lainnya", "hint": _WORKLOAD_HINT["other"]}


# --------------------------------------------------------------------------- #
#  Pengumpulan data OS (BLOCKING) + cache                                     #
# --------------------------------------------------------------------------- #
def _os_pretty_name() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def _cmdline(pid: int) -> str:
    try:
        return " ".join(psutil.Process(pid).cmdline())[:220]
    except Exception:  # noqa: BLE001
        return ""


# Snapshot cpu_time per-proses dari scan sebelumnya. Dipakai menghitung %CPU dari
# SELISIH cpu_time antar-scan (1x iterasi), menggantikan pola lama prime+sleep+baca
# (2x iterasi + tidur 0.2s yang memicu lonjakan CPU saat halaman laporan polling).
_prev_cpu_snapshot: dict = {"pid_cpu": {}, "wall": 0.0}
_CPU_DELTA_MAX_SECONDS = 120.0  # jeda antar-scan terlalu lama -> mulai baseline lagi


def _gather_os() -> dict:
    """Scan OS (BLOCKING psutil/NVML) — dipanggil via to_thread + cache."""
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    disk = _safe(lambda: psutil.disk_usage("/"))
    load = _safe(os.getloadavg, (0.0, 0.0, 0.0))
    boot = _safe(psutil.boot_time, time.time())
    gpus = gpu_svc.list_gpus()
    drv = gpu_svc.driver_info()
    cores = psutil.cpu_count(logical=True) or 1

    system = {
        "hostname": socket.gethostname(),
        "os": _os_pretty_name(),
        "cpu_cores": cores,
        "cpu_physical_cores": psutil.cpu_count(logical=False) or 0,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "load_avg": [round(float(x), 2) for x in load],
        "memory_total_mb": vm.total / _MB,
        "memory_used_mb": (vm.total - vm.available) / _MB,
        "memory_available_mb": vm.available / _MB,
        "swap_total_mb": sm.total / _MB,
        "swap_used_mb": sm.used / _MB,
        "disk_total_gb": (disk.total / 1e9) if disk else 0.0,
        "disk_used_gb": (disk.used / 1e9) if disk else 0.0,
        "disk_percent": (disk.percent) if disk else 0.0,
        "gpus": [g.as_dict() for g in gpus],
        "driver_version": drv.get("driver_version", ""),
        "cuda_version": drv.get("cuda_version", ""),
        "uptime_seconds": max(0.0, time.time() - boot),
        "boot_time": dt.datetime.fromtimestamp(boot, dt.timezone.utc).isoformat(),
    }

    # Scan proses SEKALI jalan (hemat CPU): %CPU dihitung dari selisih cpu_time
    # antar-scan, BUKAN prime cpu_percent + sleep(0.2) + baca ulang (yang butuh
    # 2x iterasi seluruh proses + tidur — penyebab lonjakan CPU saat polling).
    now_wall = time.time()
    prev = _prev_cpu_snapshot["pid_cpu"]
    d_wall = now_wall - _prev_cpu_snapshot["wall"]
    use_prev = bool(prev) and 0.0 < d_wall <= _CPU_DELTA_MAX_SECONDS

    procs = list(psutil.process_iter(["pid", "name", "username"]))
    rows: list[dict] = []
    by_pid: dict[int, dict] = {}
    cur_cpu: dict[int, float] = {}
    for p in procs:
        try:
            with p.oneshot():
                info = p.info
                mem = p.memory_info().rss / _MB
                ctimes = p.cpu_times()
                created = p.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:  # noqa: BLE001
            continue
        pid = info.get("pid")
        cpu_sec = float(ctimes.user + ctimes.system)
        cur_cpu[pid] = cpu_sec
        if use_prev and pid in prev:
            cpu = max(0.0, cpu_sec - prev[pid]) / d_wall * 100.0
        else:
            cpu = 0.0
        row = {
            "pid": pid,
            "username": info.get("username") or "?",
            "name": info.get("name") or "",
            "cpu_percent": round(cpu, 1),
            "cpu_cores_eq": round(cpu / 100.0, 1),
            "memory_mb": round(mem, 1),
            "cpu_time": round(cpu_sec, 1),
            "create_time": created,
        }
        rows.append(row)
        by_pid[pid] = row
    _prev_cpu_snapshot["pid_cpu"] = cur_cpu
    _prev_cpu_snapshot["wall"] = now_wall

    # Proses GPU (siapa memakai GPU) — baca cmdline hanya utk PID GPU (sedikit).
    gpu_processes: list[dict] = []
    gpu_by_pid: dict[int, dict] = {}
    for gpu_index, pid, vram_mb in gpu_svc.all_gpu_processes():
        cached = by_pid.get(pid, {})
        username = cached.get("username", "?")
        name = cached.get("name", "")
        command = _cmdline(pid)
        try:
            proc = psutil.Process(pid)
            username = proc.username() or username
            name = name or proc.name()
        except Exception:  # noqa: BLE001
            pass
        wl = analyze_workload(command, name)
        gp = {
            "gpu_index": gpu_index,
            "pid": pid,
            "username": username,
            "name": name,
            "command": command or name,
            "vram_mb": round(vram_mb, 1),
            "workload": wl["label"],
        }
        gpu_processes.append(gp)
        gpu_by_pid[pid] = gp

    # Top proses (CPU) + label workload (baca cmdline utk subset kecil).
    top_sorted = sorted(rows, key=lambda r: (r["cpu_percent"], r["memory_mb"]), reverse=True)
    top_processes = []
    for r in top_sorted[:_TOP_LIMIT]:
        cmd = _cmdline(r["pid"])
        wl = analyze_workload(cmd, r["name"])
        top_processes.append({**r, "command": cmd or r["name"], "workload": wl["label"]})

    # Agregasi per user OS (mirip PDF bagian 12).
    agg: dict[str, dict] = {}

    def _bucket(user: str) -> dict:
        return agg.setdefault(
            user,
            {
                "username": user,
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "vram_mb": 0.0,
                "gpu_indices": set(),
                "processes": 0,
                "_top_pid": None,
                "_top_cpu": -1.0,
            },
        )

    for r in rows:
        b = _bucket(r["username"])
        b["cpu_percent"] += r["cpu_percent"]
        b["memory_mb"] += r["memory_mb"]
        b["processes"] += 1
        if r["cpu_percent"] > b["_top_cpu"]:
            b["_top_cpu"] = r["cpu_percent"]
            b["_top_pid"] = r["pid"]

    for gp in gpu_processes:
        b = _bucket(gp["username"])
        b["vram_mb"] += gp["vram_mb"]
        b["gpu_indices"].add(gp["gpu_index"])

    os_users = []
    for b in agg.values():
        # Aktivitas = workload dari proses GPU (kalau ada) atau proses CPU teratas.
        activity = ""
        user_gpu = [g for g in gpu_processes if g["username"] == b["username"]]
        if user_gpu:
            activity = max(user_gpu, key=lambda g: g["vram_mb"])["workload"]
        elif b["_top_pid"] is not None:
            cmd = _cmdline(b["_top_pid"])
            nm = by_pid.get(b["_top_pid"], {}).get("name", "")
            activity = analyze_workload(cmd, nm)["label"]
        os_users.append(
            {
                "username": b["username"],
                "cpu_percent": round(b["cpu_percent"], 1),
                "cpu_cores_eq": round(b["cpu_percent"] / 100.0, 1),
                "memory_mb": round(b["memory_mb"], 1),
                "vram_mb": round(b["vram_mb"], 1),
                "gpu_indices": sorted(b["gpu_indices"]),
                "processes": b["processes"],
                "activity": activity or "—",
            }
        )
    os_users.sort(key=lambda u: (u["vram_mb"], u["cpu_percent"]), reverse=True)

    return {
        "system": system,
        "gpu_processes": sorted(gpu_processes, key=lambda g: g["vram_mb"], reverse=True),
        "top_processes": top_processes,
        "os_users": os_users,
        "_rows": rows,
        "_gpu_by_pid": gpu_by_pid,
    }


# Cache scan OS (hemat CPU saat polling admin).
_os_cache: dict = {"ts": 0.0, "data": None}


def _gather_os_cached() -> dict:
    now = time.monotonic()
    ttl = max(1.0, float(settings.REPORT_CACHE_TTL_SECONDS))
    if _os_cache["data"] is not None and (now - _os_cache["ts"]) < ttl:
        return _os_cache["data"]
    data = _gather_os()
    _os_cache["ts"] = now
    _os_cache["data"] = data
    return data


# --------------------------------------------------------------------------- #
#  Data platform (akun ComputeHub)                                            #
# --------------------------------------------------------------------------- #
async def _platform_data(session: AsyncSession) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    day_ago = now - dt.timedelta(hours=24)

    rows = (
        await session.execute(
            select(
                User.id,
                User.name,
                User.email,
                User.role,
                func.count(Job.id),
                func.coalesce(func.sum(case((Job.status == JobStatus.succeeded, 1), else_=0)), 0),
                func.coalesce(func.sum(case((Job.status == JobStatus.failed, 1), else_=0)), 0),
                func.coalesce(func.sum(case((Job.status == JobStatus.cancelled, 1), else_=0)), 0),
                func.coalesce(func.sum(case((Job.status == JobStatus.running, 1), else_=0)), 0),
                func.coalesce(func.sum(case((Job.status == JobStatus.queued, 1), else_=0)), 0),
                func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0),
                func.max(Job.peak_ram_mb),
                func.max(Job.peak_vram_mb),
                func.max(Job.peak_cpu_percent),
                func.max(Job.submitted_at),
            )
            .select_from(User)
            .join(Job, Job.user_id == User.id, isouter=True)
            .group_by(User.id)
            .order_by(User.id)
        )
    ).all()

    used24 = dict(
        (
            await session.execute(
                select(Job.user_id, func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0))
                .where(Job.finished_at >= day_ago, Job.actual_runtime_seconds.is_not(None))
                .group_by(Job.user_id)
            )
        ).all()
    )

    users = []
    for (uid, name, email, role, total, succ, failed, cancelled, running, queued, secs_total, peak_ram, peak_vram, peak_cpu, last_at) in rows:
        users.append(
            {
                "user_id": uid,
                "name": name,
                "email": email,
                "role": role.value if hasattr(role, "value") else str(role),
                "jobs_total": int(total),
                "jobs_succeeded": int(succ),
                "jobs_failed": int(failed),
                "jobs_cancelled": int(cancelled),
                "jobs_running": int(running),
                "jobs_queued": int(queued),
                "gpu_seconds_24h": float(used24.get(uid, 0.0)),
                "gpu_seconds_total": float(secs_total),
                "peak_ram_mb": float(peak_ram) if peak_ram is not None else None,
                "peak_vram_mb": float(peak_vram) if peak_vram is not None else None,
                "peak_cpu_percent": float(peak_cpu) if peak_cpu is not None else None,
                "last_activity": last_at.isoformat() if last_at else None,
            }
        )

    run_rows = (
        await session.execute(
            select(Job, User)
            .join(User, Job.user_id == User.id)
            .where(Job.status == JobStatus.running)
            .order_by(Job.started_at)
        )
    ).all()

    running_jobs = []
    for job, owner in run_rows:
        started = job.started_at
        runtime = None
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=dt.timezone.utc)
            runtime = max(0.0, (now - started).total_seconds())
        running_jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "owner_name": owner.name,
                "owner_email": owner.email,
                "role": owner.role.value if hasattr(owner.role, "value") else str(owner.role),
                "gpu_index": job.gpu_index,
                "pid": job.pid,
                "source_type": job.source_type.value if hasattr(job.source_type, "value") else str(job.source_type),
                "runtime_seconds": runtime,
                "peak_ram_mb": job.peak_ram_mb,
                "peak_vram_mb": job.peak_vram_mb,
                "avg_gpu_util_percent": job.avg_gpu_util_percent,
                "started_at": started.isoformat() if started else None,
            }
        )

    total_users = await session.scalar(select(func.count(User.id)))
    return {
        "users": users,
        "running_jobs": running_jobs,
        "platform_users": int(total_users or 0),
        "now": now.isoformat(),
    }


async def build_report(session: AsyncSession) -> dict:
    """Laporan ringkas (OS-level + platform-level)."""
    os_data = await asyncio.to_thread(_gather_os_cached)
    plat = await _platform_data(session)

    os_data["system"]["platform_users"] = plat["platform_users"]
    os_data["system"]["now"] = plat["now"]

    running_pids = {j["pid"]: j["id"] for j in plat["running_jobs"] if j["pid"] is not None}
    gpu_procs = []
    for gp in os_data["gpu_processes"]:
        gpu_procs.append(
            {**gp, "job_id": running_pids.get(gp["pid"]), "is_platform_job": gp["pid"] in running_pids}
        )

    return {
        "system": os_data["system"],
        "gpu_processes": gpu_procs,
        "top_processes": os_data["top_processes"],
        "os_users": os_data["os_users"],
        "running_jobs": plat["running_jobs"],
        "users": plat["users"],
    }


# --------------------------------------------------------------------------- #
#  Laporan DETAIL per-user OS (13 bagian)                                      #
# --------------------------------------------------------------------------- #
def _fmt_dt(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch).astimezone().strftime("%d %b %Y %H:%M:%S")


def _user_report_sync(username: str) -> dict:
    osd = _gather_os_cached()
    system = dict(osd["system"])
    rows = [r for r in osd["_rows"] if r["username"] == username]
    gpu_rows = [g for g in osd["gpu_processes"] if g["username"] == username]

    # --- Profil user OS ---
    profile = {"username": username, "uid": None, "home": "", "shell": ""}
    try:
        import pwd

        pw = pwd.getpwnam(username)
        profile.update({"uid": pw.pw_uid, "home": pw.pw_dir, "shell": pw.pw_shell})
    except Exception:  # noqa: BLE001
        pass
    sessions = []
    for s in _safe(psutil.users, []) or []:
        if s.name == username:
            sessions.append(
                {
                    "terminal": s.terminal or "",
                    "host": s.host or "",
                    "started": _fmt_dt(s.started) if s.started else "",
                }
            )

    # --- Enrich proses user dgn cmdline + workload (jumlah kecil) ---
    enriched = []
    for r in rows:
        cmd = _cmdline(r["pid"])
        gp = next((g for g in gpu_rows if g["pid"] == r["pid"]), None)
        wl = analyze_workload(cmd, r["name"])
        enriched.append(
            {
                **r,
                "command": cmd or r["name"],
                "workload": wl["label"],
                "workload_type": wl["type"],
                "gpu_index": gp["gpu_index"] if gp else None,
                "gpu_vram_mb": gp["vram_mb"] if gp else 0.0,
                "started": _fmt_dt(r["create_time"]) if r.get("create_time") else "",
                "runtime_seconds": max(0.0, time.time() - r["create_time"]) if r.get("create_time") else None,
            }
        )

    # Proses utama: prioritas yang pakai GPU (VRAM terbesar), lalu CPU tertinggi.
    main = None
    if enriched:
        on_gpu = [e for e in enriched if e["gpu_vram_mb"] > 0]
        main = (
            max(on_gpu, key=lambda e: e["gpu_vram_mb"])
            if on_gpu
            else max(enriched, key=lambda e: e["cpu_percent"])
        )
    supporting = [e for e in enriched if main is None or e["pid"] != main["pid"]]
    supporting = sorted(supporting, key=lambda e: e["cpu_percent"], reverse=True)[:8]

    # --- Agregat status ---
    total_cpu = round(sum(e["cpu_percent"] for e in enriched), 1)
    cores_eq = round(total_cpu / 100.0, 1)
    total_ram = round(sum(e["memory_mb"] for e in enriched), 1)
    total_cpu_time = round(sum(e["cpu_time"] for e in enriched), 1)
    total_vram = round(sum(g["vram_mb"] for g in gpu_rows), 1)
    gpu_indices = sorted({g["gpu_index"] for g in gpu_rows})

    cores = system["cpu_cores"] or 1
    gpu_status = []
    for g in system["gpus"]:
        if g["index"] in gpu_indices:
            uvram = sum(x["vram_mb"] for x in gpu_rows if x["gpu_index"] == g["index"])
            gpu_status.append(
                {
                    "index": g["index"],
                    "name": g["name"],
                    "util_percent": g["util_percent"],
                    "temperature_c": g["temperature_c"],
                    "power_w": g["power_w"],
                    "user_vram_mb": round(uvram, 1),
                    "total_vram_mb": g["mem_total_mb"],
                }
            )

    # --- Analisis workload (gabungan) ---
    types = {}
    for e in enriched:
        types[e["workload_type"]] = types.get(e["workload_type"], 0) + 1
    primary = main["workload"] if main else "—"
    primary_type = main["workload_type"] if main else "other"
    workload = {
        "primary": primary,
        "primary_type": primary_type,
        "hint": _WORKLOAD_HINT.get(primary_type, ""),
        "signals": sorted(types.keys()),
    }

    # --- Temuan & rekomendasi (rule-based, fleksibel) ---
    findings: list[dict] = []
    rec_high: list[str] = []
    rec_med: list[str] = []
    rec_low: list[str] = []

    main_pid = main["pid"] if main else None
    heavy_threshold = max(8.0, cores * 0.25)
    if cores_eq >= heavy_threshold:
        findings.append({"level": "warn", "text": f"CPU SANGAT TINGGI: {total_cpu:.0f}% (~{cores_eq:.0f} dari {cores} core) — membebani server bersama."})
        if main_pid:
            rec_high.append(f"Batasi core proses utama: `taskset -pc 0-7 {main_pid}` (atau set OMP_NUM_THREADS/MKL_NUM_THREADS=8 + torch.set_num_threads(8) di skrip).")
            rec_high.append(f"Turunkan prioritas agar mengalah: `renice +15 -p {main_pid}`.")
    elif cores_eq >= 4:
        findings.append({"level": "warn", "text": f"CPU cukup tinggi: {total_cpu:.0f}% (~{cores_eq:.0f} core)."})
        rec_med.append("Pertimbangkan membatasi jumlah worker/thread agar tidak mengganggu user lain.")
    else:
        findings.append({"level": "ok", "text": f"CPU wajar: {total_cpu:.0f}% (~{cores_eq:.1f} core)."})

    if gpu_rows:
        low_util = all(g["util_percent"] < 30 for g in gpu_status) if gpu_status else False
        findings.append({"level": "ok", "text": f"Memakai GPU {gpu_indices}: total {total_vram:.0f} MiB VRAM."})
        if low_util and cores_eq >= 4:
            findings.append({"level": "warn", "text": "GPU underutilized (SM rendah) padahal CPU tinggi — bottleneck di CPU preprocessing."})
            rec_med.append("Pindahkan preprocessing ke GPU / tambah batching (batch_size) / pakai DataLoader num_workers wajar.")
    else:
        findings.append({"level": "ok", "text": "Tidak memakai GPU saat ini."})

    if primary_type == "ocr" and cores_eq >= 4:
        rec_med.append("OCR sangat CPU-intensive: pakai batch_size pada readtext, batasi bahasa OCR seperlunya, dan gunakan worker terbatas.")
    if system["swap_used_mb"] > 1024:
        findings.append({"level": "warn", "text": f"Swap terpakai {system['swap_used_mb']/1024:.1f} GB — ada tekanan memori."})
    if total_ram < 4096:
        findings.append({"level": "ok", "text": f"RAM hemat: {total_ram/1024:.1f} GB."})

    rec_low.append("Bersihkan cache yang tidak perlu (mis. `pip cache purge`, `~/.cache`).")
    rec_low.append("Simpan checkpoint/weights agar tidak perlu komputasi ulang.")

    # --- Ringkasan & kesimpulan ---
    summary = {
        "processes": len(enriched),
        "cpu_percent": total_cpu,
        "cpu_cores_eq": cores_eq,
        "cpu_time_seconds": total_cpu_time,
        "memory_mb": total_ram,
        "vram_mb": total_vram,
        "gpu_indices": gpu_indices,
    }
    conclusion = (
        f"User {username} menjalankan {primary}. "
        f"Pemakaian CPU ~{cores_eq:.0f} core ({total_cpu:.0f}%), RAM {total_ram/1024:.1f} GB"
        + (f", GPU {gpu_indices} {total_vram:.0f} MiB VRAM. " if gpu_rows else ". ")
    )
    if cores_eq >= heavy_threshold:
        conclusion += "Pemakaian CPU tergolong berat — disarankan dibatasi agar tidak mengganggu user lain."
    else:
        conclusion += "Pemakaian resource dalam batas wajar."

    return {
        "username": username,
        "generated_at": dt.datetime.now().astimezone().strftime("%d %b %Y %H:%M:%S %Z"),
        "generated_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
        "profile": {**profile, "sessions": sessions, "processes_count": len(enriched)},
        "system": system,
        "status": {
            "gpu": gpu_status,
            "ram": {
                "user_rss_mb": total_ram,
                "percent_of_total": round(total_ram / (system["memory_total_mb"] or 1) * 100, 2),
                "system_total_mb": system["memory_total_mb"],
                "system_used_mb": system["memory_used_mb"],
                "system_available_mb": system["memory_available_mb"],
                "swap_used_mb": system["swap_used_mb"],
            },
            "cpu": {
                "user_cpu_percent": total_cpu,
                "cores_eq": cores_eq,
                "cpu_time_seconds": total_cpu_time,
                "load_avg": system["load_avg"],
                "system_cores": cores,
            },
            "disk": {
                "fs_total_gb": system["disk_total_gb"],
                "fs_used_gb": system["disk_used_gb"],
                "fs_percent": system["disk_percent"],
                "home": profile["home"],
            },
        },
        "workload": workload,
        "processes": {"main": main, "supporting": supporting},
        "gpu_processes": gpu_rows,
        "findings": findings,
        "recommendations": {"high": rec_high, "medium": rec_med, "low": rec_low},
        "summary": summary,
        "comparison": osd["os_users"],
        "conclusion": conclusion,
    }


async def user_report(username: str) -> dict:
    """Laporan detail per-user OS (fleksibel sesuai workload)."""
    return await asyncio.to_thread(_user_report_sync, username)


async def os_usage() -> dict:
    """Snapshot ringan {system, os_users} (untuk mesin peringatan, tanpa DB)."""
    osd = await asyncio.to_thread(_gather_os_cached)
    return {"system": osd["system"], "os_users": osd["os_users"]}


# --------------------------------------------------------------------------- #
#  Render HTML (siap cetak ke PDF)                                            #
# --------------------------------------------------------------------------- #
_CSS = """
*{box-sizing:border-box} body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2937;margin:0;padding:32px;background:#fff;line-height:1.5}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:26px 0 8px;padding-bottom:6px;border-bottom:2px solid #e5e7eb;color:#111827}
h3{font-size:13px;margin:16px 0 6px;color:#374151} .muted{color:#6b7280;font-size:12px}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:12px} th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #eef0f3}
th{color:#6b7280;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em} td.r,th.r{text-align:right}
.kv{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 24px;font-size:13px} .kv div{padding:4px 0;border-bottom:1px solid #f3f4f6}
.kv b{color:#6b7280;font-weight:600;margin-right:8px}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600}
.ok{background:#ecfdf5;color:#047857} .warn{background:#fef2f2;color:#b91c1c} .info{background:#eff6ff;color:#1d4ed8}
.hr{height:1px;background:#e5e7eb;margin:18px 0} ul{margin:6px 0 6px 18px;padding:0;font-size:12.5px} li{margin:3px 0}
.foot{margin-top:28px;color:#9ca3af;font-size:11px;text-align:center;border-top:1px solid #e5e7eb;padding-top:12px}
code{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-size:11.5px}
"""


def _e(x) -> str:
    return html_mod.escape(str(x if x is not None else "—"))


def _mib(mb: float) -> str:
    return f"{mb:,.0f} MiB"


def _gb(mb: float) -> str:
    return f"{mb/1024:.1f} GB"


def render_user_html(r: dict) -> str:
    s = r["system"]
    st = r["status"]
    p = r["profile"]
    wl = r["workload"]
    main = r["processes"]["main"]

    def rows_html(items, cols):
        out = []
        for it in items:
            tds = "".join(f"<td class='{c[2]}'>{c[1](it)}</td>" for c in cols)
            out.append(f"<tr>{tds}</tr>")
        return "".join(out)

    gpu_tbl = ""
    if st["gpu"]:
        body = "".join(
            f"<tr><td>GPU {g['index']}</td><td>{_e(g['name'])}</td>"
            f"<td class='r'>{_mib(g['user_vram_mb'])} / {_mib(g['total_vram_mb'])}</td>"
            f"<td class='r'>{g['util_percent']:.0f}%</td><td class='r'>{g['temperature_c']:.0f}°C</td>"
            f"<td class='r'>{g['power_w']:.0f} W</td></tr>"
            for g in st["gpu"]
        )
        gpu_tbl = (
            "<table><thead><tr><th>GPU</th><th>Model</th><th class='r'>VRAM (user/total)</th>"
            "<th class='r'>Util</th><th class='r'>Suhu</th><th class='r'>Power</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
    else:
        gpu_tbl = "<p class='muted'>User ini tidak memakai GPU saat ini.</p>"

    main_html = "<p class='muted'>Tidak ada proses aktif.</p>"
    if main:
        main_html = (
            "<div class='kv'>"
            f"<div><b>PID</b>{_e(main['pid'])}</div>"
            f"<div><b>Status</b>{_e(main.get('status', 'aktif'))}</div>"
            f"<div><b>Mulai</b>{_e(main['started'])}</div>"
            f"<div><b>Runtime</b>{(main['runtime_seconds'] or 0)/60:.0f} menit</div>"
            f"<div><b>CPU</b>{main['cpu_percent']:.0f}% (~{main['cpu_cores_eq']:.0f} core)</div>"
            f"<div><b>CPU time</b>{main['cpu_time']/60:.0f} menit</div>"
            f"<div><b>RAM</b>{_gb(main['memory_mb'])}</div>"
            f"<div><b>GPU VRAM</b>{_mib(main['gpu_vram_mb']) if main['gpu_vram_mb'] else '—'}</div>"
            "</div>"
            f"<p style='margin-top:8px'><b>Command:</b> <code>{_e(main['command'])}</code></p>"
        )

    support_tbl = "".join(
        f"<tr><td>{_e(e['pid'])}</td><td>{_e(e['name'])}</td><td>{_e(e['workload'])}</td>"
        f"<td class='r'>{e['cpu_percent']:.0f}%</td><td class='r'>{_gb(e['memory_mb'])}</td></tr>"
        for e in r["processes"]["supporting"]
    ) or "<tr><td colspan='5' class='muted'>—</td></tr>"

    findings_html = "".join(
        f"<li><span class='badge {f['level'] if f['level'] in ('ok','warn') else 'info'}'>"
        f"{'OK' if f['level']=='ok' else 'PERHATIAN'}</span> {_e(f['text'])}</li>"
        for f in r["findings"]
    )

    def rec_list(items):
        return "".join(f"<li>{_e(x)}</li>" for x in items) or "<li class='muted'>—</li>"

    comparison = "".join(
        f"<tr><td>{_e(u['username'])}</td><td class='r'>{_mib(u['vram_mb']) if u['vram_mb'] else '—'}</td>"
        f"<td class='r'>{u['cpu_percent']:.0f}% (~{u['cpu_cores_eq']:.0f})</td>"
        f"<td class='r'>{_gb(u['memory_mb'])}</td><td>{_e(u['activity'])}</td></tr>"
        for u in r["comparison"][:15]
    )

    sessions = "".join(
        f"<tr><td>{_e(x['terminal'])}</td><td>{_e(x['host'])}</td><td>{_e(x['started'])}</td></tr>"
        for x in p["sessions"]
    ) or "<tr><td colspan='3' class='muted'>Tidak ada sesi aktif terdeteksi.</td></tr>"

    return f"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<title>Laporan {_e(r['username'])}</title><style>{_CSS}</style></head><body>
<h1>LAPORAN LENGKAP PENGGUNAAN RESOURCE — USER: {_e(r['username'].upper())}</h1>
<p class="muted">Server {_e(s['hostname'])} · dibuat {_e(r['generated_at'])}</p>

<h2>1. Informasi Sistem</h2>
<div class="kv">
<div><b>Hostname</b>{_e(s['hostname'])}</div><div><b>OS</b>{_e(s['os'])}</div>
<div><b>CPU</b>{s['cpu_cores']} core</div><div><b>RAM</b>{_gb(s['memory_total_mb'])}</div>
<div><b>GPU</b>{len(s['gpus'])} × {_e(s['gpus'][0]['name']) if s['gpus'] else '—'}</div>
<div><b>Driver / CUDA</b>{_e(s['driver_version'])} / CUDA {_e(s['cuda_version'])}</div>
<div><b>Disk (/)</b>{s['disk_used_gb']:.0f} / {s['disk_total_gb']:.0f} GB ({s['disk_percent']:.0f}%)</div>
<div><b>Uptime</b>{s['uptime_seconds']/3600:.0f} jam</div>
</div>

<h2>2. Profil User</h2>
<div class="kv">
<div><b>Username</b>{_e(p['username'])}</div><div><b>UID</b>{_e(p['uid'])}</div>
<div><b>Home</b>{_e(p['home'])}</div><div><b>Shell</b>{_e(p['shell'])}</div>
<div><b>Proses aktif</b>{p['processes_count']}</div>
</div>
<h3>Sesi / Login</h3>
<table><thead><tr><th>Terminal</th><th>IP / Host</th><th>Mulai</th></tr></thead><tbody>{sessions}</tbody></table>

<h2>3. Status Resource Saat Ini <span class="muted">({_e(r['generated_at'])})</span></h2>
<h3>3.1 Penggunaan GPU</h3>{gpu_tbl}
<h3>3.2 Penggunaan RAM</h3>
<div class="kv">
<div><b>RAM user</b>{_gb(st['ram']['user_rss_mb'])} ({st['ram']['percent_of_total']:.1f}%)</div>
<div><b>Sistem</b>{_gb(st['ram']['system_used_mb'])} / {_gb(st['ram']['system_total_mb'])}</div>
<div><b>Swap</b>{_gb(st['ram']['swap_used_mb'])}</div>
</div>
<h3>3.3 Penggunaan CPU</h3>
<div class="kv">
<div><b>CPU user</b>{st['cpu']['user_cpu_percent']:.0f}% (~{st['cpu']['cores_eq']:.0f} core)</div>
<div><b>CPU time</b>{st['cpu']['cpu_time_seconds']/60:.0f} menit</div>
<div><b>Load average</b>{' / '.join(str(x) for x in st['cpu']['load_avg'])}</div>
<div><b>Total core</b>{st['cpu']['system_cores']}</div>
</div>
<h3>3.4 Penggunaan Disk</h3>
<div class="kv">
<div><b>Filesystem /</b>{st['disk']['fs_used_gb']:.0f} / {st['disk']['fs_total_gb']:.0f} GB ({st['disk']['fs_percent']:.0f}%)</div>
<div><b>Home</b>{_e(st['disk']['home'])}</div>
</div>

<h2>4. Analisis Pekerjaan (Workload)</h2>
<p><span class="badge info">{_e(wl['primary'])}</span></p>
<p class="muted">{_e(wl['hint'])}</p>
<p class="muted">Sinyal terdeteksi: {_e(', '.join(wl['signals']) or '—')}</p>

<h2>5. Proses yang Sedang Berjalan</h2>
<h3>5.1 Proses Utama</h3>{main_html}
<h3>5.3 Proses Pendukung</h3>
<table><thead><tr><th>PID</th><th>Proses</th><th>Workload</th><th class="r">CPU</th><th class="r">RAM</th></tr></thead>
<tbody>{support_tbl}</tbody></table>

<h2>9. Temuan</h2><ul>{findings_html}</ul>

<h2>10. Rekomendasi</h2>
<h3>Prioritas Tinggi</h3><ul>{rec_list(r['recommendations']['high'])}</ul>
<h3>Prioritas Sedang</h3><ul>{rec_list(r['recommendations']['medium'])}</ul>
<h3>Prioritas Rendah</h3><ul>{rec_list(r['recommendations']['low'])}</ul>

<h2>11. Ringkasan Statistik</h2>
<div class="kv">
<div><b>Total proses</b>{r['summary']['processes']}</div>
<div><b>CPU</b>{r['summary']['cpu_percent']:.0f}% (~{r['summary']['cpu_cores_eq']:.0f} core)</div>
<div><b>CPU time</b>{r['summary']['cpu_time_seconds']/60:.0f} menit</div>
<div><b>RAM</b>{_gb(r['summary']['memory_mb'])}</div>
<div><b>VRAM</b>{_mib(r['summary']['vram_mb']) if r['summary']['vram_mb'] else '—'}</div>
<div><b>GPU</b>{_e(r['summary']['gpu_indices'] or '—')}</div>
</div>

<h2>12. Perbandingan dengan User Lain</h2>
<table><thead><tr><th>User OS</th><th class="r">VRAM</th><th class="r">CPU</th><th class="r">RAM</th><th>Aktivitas</th></tr></thead>
<tbody>{comparison}</tbody></table>

<h2>13. Kesimpulan</h2>
<p>{_e(r['conclusion'])}</p>

<div class="foot">Laporan dibuat oleh UNISMUH ComputeHub · {_e(r['generated_at'])} · server {_e(s['hostname'])}</div>
</body></html>"""


def render_full_html(rep: dict) -> str:
    s = rep["system"]
    gpu_rows = "".join(
        f"<tr><td>GPU {g['gpu_index']}</td><td>{_e(g['pid'])}</td><td>{_e(g['username'])}</td>"
        f"<td>{_e(g['workload'])}</td><td><code>{_e(g['command'])}</code></td><td class='r'>{_mib(g['vram_mb'])}</td></tr>"
        for g in rep["gpu_processes"]
    ) or "<tr><td colspan='6' class='muted'>—</td></tr>"

    os_rows = "".join(
        f"<tr><td>{_e(u['username'])}</td><td class='r'>{_mib(u['vram_mb']) if u['vram_mb'] else '—'}</td>"
        f"<td class='r'>{u['cpu_percent']:.0f}% (~{u['cpu_cores_eq']:.0f})</td><td class='r'>{_gb(u['memory_mb'])}</td>"
        f"<td class='r'>{u['processes']}</td><td>{_e(u['activity'])}</td></tr>"
        for u in rep["os_users"]
    )

    top_rows = "".join(
        f"<tr><td>{_e(p['pid'])}</td><td>{_e(p['username'])}</td><td>{_e(p['name'])}</td>"
        f"<td>{_e(p['workload'])}</td><td class='r'>{p['cpu_percent']:.0f}%</td><td class='r'>{_gb(p['memory_mb'])}</td></tr>"
        for p in rep["top_processes"]
    )

    user_rows = "".join(
        f"<tr><td>{_e(u['name'])}<br><span class='muted'>{_e(u['email'])}</span></td><td>{_e(u['role'])}</td>"
        f"<td class='r'>{u['jobs_total']}</td><td class='r'>{u['jobs_running']}</td>"
        f"<td class='r'>{u['gpu_seconds_total']/60:.0f} m</td></tr>"
        for u in rep["users"]
    )

    return f"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<title>Laporan Penggunaan Server</title><style>{_CSS}</style></head><body>
<h1>LAPORAN PENGGUNAAN RESOURCE SERVER</h1>
<p class="muted">Server {_e(s['hostname'])} · {_e(s.get('now',''))}</p>

<h2>1. Informasi Sistem</h2>
<div class="kv">
<div><b>Hostname</b>{_e(s['hostname'])}</div><div><b>OS</b>{_e(s['os'])}</div>
<div><b>CPU</b>{s['cpu_cores']} core · util {s['cpu_percent']:.0f}% · load {' / '.join(str(x) for x in s['load_avg'])}</div>
<div><b>RAM</b>{_gb(s['memory_used_mb'])} / {_gb(s['memory_total_mb'])}</div>
<div><b>Disk (/)</b>{s['disk_used_gb']:.0f} / {s['disk_total_gb']:.0f} GB ({s['disk_percent']:.0f}%)</div>
<div><b>GPU</b>{len(s['gpus'])} × {_e(s['gpus'][0]['name']) if s['gpus'] else '—'} · Driver {_e(s['driver_version'])} / CUDA {_e(s['cuda_version'])}</div>
<div><b>Uptime</b>{s['uptime_seconds']/3600:.0f} jam</div><div><b>Akun ComputeHub</b>{s.get('platform_users','—')}</div>
</div>

<h2>2. Penggunaan GPU Langsung</h2>
<table><thead><tr><th>GPU</th><th>PID</th><th>User OS</th><th>Workload</th><th>Program</th><th class="r">VRAM</th></tr></thead>
<tbody>{gpu_rows}</tbody></table>

<h2>3. Pengguna Server (OS)</h2>
<table><thead><tr><th>User OS</th><th class="r">VRAM</th><th class="r">CPU</th><th class="r">RAM</th><th class="r">Proses</th><th>Aktivitas</th></tr></thead>
<tbody>{os_rows}</tbody></table>

<h2>4. Proses CPU Teratas</h2>
<table><thead><tr><th>PID</th><th>User</th><th>Proses</th><th>Workload</th><th class="r">CPU</th><th class="r">RAM</th></tr></thead>
<tbody>{top_rows}</tbody></table>

<h2>5. Statistik per Akun ComputeHub</h2>
<table><thead><tr><th>Pengguna</th><th>Role</th><th class="r">Job</th><th class="r">Jalan</th><th class="r">GPU total</th></tr></thead>
<tbody>{user_rows}</tbody></table>

<div class="foot">Laporan dibuat oleh UNISMUH ComputeHub · server {_e(s['hostname'])}</div>
</body></html>"""
