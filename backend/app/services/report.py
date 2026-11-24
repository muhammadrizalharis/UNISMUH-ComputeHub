"""Laporan penggunaan resource untuk admin.

Menggabungkan DUA sudut pandang:
  1. OS-level (server-wide): siapa (user OS) memakai GPU/CPU/RAM saat ini —
     termasuk proses di luar platform. Mirip `nvidia-smi`/`top`.
  2. Platform-level: statistik job per akun ComputeHub.

Plus: laporan DETAIL per-user (13 bagian) dengan ANALISIS WORKLOAD otomatis
(fleksibel — mendeteksi apa yang dikerjakan: OCR, training, diffusion, API,
notebook, dll.) dan ekspor HTML (siap cetak ke PDF).

Catatan CPU: selama Laporan dibuka, sampler latar belakang memindai proses tiap
~1 dtk (≈0,25 dtk CPU per scan) dan berhenti sendiri bila tak ada yang melihat.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html as html_mod
import re
import os
import platform
import socket
import threading
import time

import psutil
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.job import Job, JobStatus
from app.models.monitoring import ResourceSample, SampleScope
from app.models.user import User
from app.schemas.monitoring import ResourceSampleOut
from app.services import gpu as gpu_svc
from app.services import assistant_usage as assistant_usage_svc
from app.services import llm_attrib
from app.services import container_identity

logger = get_logger(__name__)

_MB = 1024 * 1024
_TOP_LIMIT = 12


async def _running_job_metrics(
    session: AsyncSession, job_ids: list[int], now: dt.datetime,
) -> dict[int, dict]:
    if not job_ids:
        return {}
    latest_ids = (
        select(func.max(ResourceSample.id))
        .where(ResourceSample.job_id.in_(job_ids), ResourceSample.scope == SampleScope.job)
        .group_by(ResourceSample.job_id)
    )
    samples = (await session.scalars(
        select(ResourceSample).where(ResourceSample.id.in_(latest_ids))
    )).all()
    result = {}
    max_age = max(30.0, float(settings.DEVBOX_SAMPLE_INTERVAL_SECONDS) * 2.5)
    for sample in samples:
        measured = ResourceSampleOut.model_validate(sample)
        sampled_at = measured.ts
        if sampled_at.tzinfo is None:
            sampled_at = sampled_at.replace(tzinfo=dt.timezone.utc)
        result[sample.job_id] = {
            "resource_sample": measured.model_dump(mode="json"),
            "metrics_stale": (now - sampled_at).total_seconds() > max_age,
        }
    return result


# --------------------------------------------------------------------------- #
#  Pemakaian DISK per user (du /home) — MAHAL, jadi DI-CACHE + refresh latar   #
# --------------------------------------------------------------------------- #
_DISK_TTL = 900.0  # rincian per user dihitung ulang paling lambat tiap 15 menit
# Total disk (df) dibaca LANGSUNG tiap request (murah). Bila "Terpakai" bergeser
# >= _RESCAN_DELTA dari saat rincian dihitung, rincian per user dihitung ulang segera.
_RESCAN_DELTA = 500_000_000  # 0,5 GB
_RESCAN_MIN_GAP = 30.0       # jeda minimum antar-pemindaian (dtk)
_disk_cache: dict = {"ts": 0.0, "data": None, "computing": False, "finished": 0.0}


def _sudo_prefix_du() -> list[str]:
    """['sudo','-n'] bila sudo ada (utk baca home user lain) else []."""
    import shutil as _sh

    return ["sudo", "-n"] if _sh.which("sudo") else []


# Pemakai besar di LUAR /home yang dirinci terpisah agar jumlah baris = "Terpakai".
# (path di host; dipindai lewat mount "/" read-only di container helper)
# Kunci yang sama boleh muncul >1 kali (ukurannya dijumlah, mis. /tmp + /var/tmp).
_OUTSIDE_HOME = (
    ("docker", "Docker (image, container, volume)", "/var/lib/docker"),
    ("ollama", "Model Ollama", "/usr/share/ollama"),
    ("usr", "Program & library sistem (tanpa Ollama)", "/usr"),
    ("log", "Log sistem", "/var/log"),
    ("opt", "Aplikasi tambahan", "/opt"),
    ("root", "Home root", "/root"),
    ("tmp", "File sementara", "/tmp"),
    ("tmp", "File sementara", "/var/tmp"),
)
# /usr/share/ollama ada DI DALAM /usr -> dikurangkan dari "usr" agar tak terhitung dua kali.
_NESTED = (("usr", "ollama"),)
_SCAN_TIMEOUT = 1500  # detik; ditegakkan `timeout` DI DALAM container (lihat bawah)


def _parse_du(text: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0].strip().isdigit():
            rows.append((int(parts[0]), parts[1].rstrip("/") or "/"))
    return rows


async def _run(argv: list[str], timeout: float) -> tuple[int | None, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def _scan_via_container() -> dict | None:
    """Pindai /home per user + pemakai besar di luar /home sebagai ROOT, lewat
    container sekali-pakai: "/" host di-mount READ-ONLY, tanpa jaringan, hanya `du`.

    Backend berjalan sebagai user biasa tanpa sudo, sehingga `du` langsung tak bisa
    membaca isi home user lain (angkanya KURANG tanpa ketahuan). `-x` = berhenti di
    batas filesystem: share NFS (data workspace ComputeHub di VM penyimpanan) TIDAK
    ikut terhitung karena memang tidak memakan disk server ini.

    `timeout` dijalankan DI DALAM container: membunuh proses `docker run` dari luar
    tidak menghentikan container-nya.
    """
    if not settings.DOCKER_CMD:
        return None
    extra = " ".join(f"/host{p}" for _, _, p in _OUTSIDE_HOME)
    script = (
        "nice -n 19 du -bxd1 /host/home 2>>/tmp/e; "
        f"for p in {extra}; do [ -d \"$p\" ] && nice -n 19 du -bxs \"$p\" 2>>/tmp/e; done; "
        "printf 'DENIED\\t%s\\n' \"$(grep -c 'Permission denied' /tmp/e)\""
    )
    argv = [
        *settings.DOCKER_CMD.split(), "run", "--rm",
        "--user", "0:0", "--network", "none",
        "-v", "/:/host:ro",
        settings.DISK_SCAN_IMAGE,
        "timeout", str(_SCAN_TIMEOUT), "sh", "-c", script,
    ]
    try:
        _, out, _ = await _run(argv, timeout=_SCAN_TIMEOUT + 120)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hitung disk via container gagal: %s", exc)
        return None

    denied: int | None = None
    for line in out.splitlines():
        if line.startswith("DENIED\t"):
            denied = int(line.split("\t", 1)[1].strip() or 0)
    rows = _parse_du(out)
    users: list[dict] = []
    home_total: int | None = None
    outside: dict[str, int] = {}
    for size, path in rows:
        if path == "/host/home":
            home_total = size
        elif path.startswith("/host/home/"):
            users.append({"user": os.path.basename(path), "bytes": size})
        else:
            for key, _, host_path in _OUTSIDE_HOME:
                if path == f"/host{host_path}":
                    outside[key] = outside.get(key, 0) + size
    for outer, inner in _NESTED:
        if outer in outside and inner in outside:
            outside[outer] = max(0, outside[outer] - outside[inner])
    if home_total is None:  # pemindaian /home tidak selesai (timeout/gagal)
        return None
    return {
        "users": users,
        "home_total_bytes": home_total,
        "outside": outside,
        # Lengkap HANYA bila marker tercetak (tak kena timeout) & tak ada izin ditolak.
        "complete": denied == 0,
    }


async def _scan_direct() -> dict:
    """Cadangan bila container helper tak tersedia: `du` langsung (sudo bila ada).
    Tanpa root, home user lain bisa terbaca sebagian -> ditandai TIDAK lengkap."""
    users: list[dict] = []
    home_total = 0
    complete = False
    try:
        rc, out, err = await _run([*_sudo_prefix_du(), "du", "-bxd1", "/home"], timeout=900)
        for size, path in _parse_du(out):
            if path == "/home":
                home_total = size
            else:
                users.append({"user": os.path.basename(path), "bytes": size})
        complete = rc == 0 and "Permission denied" not in err
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hitung disk per-user gagal: %s", exc)
    return {"users": users, "home_total_bytes": home_total, "outside": {}, "complete": complete}


async def _compute_disk() -> dict:
    """Disk server (df /) + ukuran tiap home (du -bx /home) + rincian di luar /home.
    BLOKIR beberapa menit — panggil lewat :func:`disk_usage` (latar + cache).

    Semua angka dalam BYTE; frontend menampilkannya sebagai GB desimal (1 GB = 10^9 B),
    satuan yang sama dengan kapasitas disk & `df -H`.
    """
    import shutil as _sh

    total, used, free = _sh.disk_usage("/")
    scan = await _scan_via_container() or await _scan_direct()
    users = sorted(scan["users"], key=lambda u: u["bytes"], reverse=True)

    home_total = scan["home_total_bytes"] or sum(u["bytes"] for u in users)
    outside_home: list[dict] = []
    for key, label, _ in _OUTSIDE_HOME:
        if key in scan["outside"] and all(o["key"] != key for o in outside_home):
            paths = ", ".join(p for k, _, p in _OUTSIDE_HOME if k == key)
            outside_home.append({"key": key, "label": label, "path": paths, "bytes": scan["outside"][key]})
    outside_home.sort(key=lambda o: o["bytes"], reverse=True)
    if scan["outside"]:
        # Sisa = sistem operasi, log, paket, metadata filesystem & berkas terhapus yang
        # masih dibuka proses -> dihitung dari df agar total PERSIS sama dgn "Terpakai".
        sisa = int(used) - home_total - sum(o["bytes"] for o in outside_home)
        outside_home.append({
            "key": "other",
            "label": "Sistem & lainnya (/var lainnya, /boot, metadata filesystem, dll)",
            "path": "/",
            "bytes": max(0, sisa),
        })
    return {
        "total_bytes": int(total),
        "used_bytes": int(used),
        "free_bytes": int(free),
        # Rumus df / psutil / ambang alert: used / (used + free). Blok cadangan khusus
        # root (reserved, biasanya 5%) tidak bisa dipakai user -> tak masuk penyebut.
        "used_percent": round(used / (used + free) * 100, 1) if used + free else 0.0,
        "reserved_bytes": max(0, int(total) - int(used) - int(free)),
        "users": users,
        "home_total_bytes": int(home_total),
        "outside_home": outside_home,
        "complete": bool(scan["complete"]),
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        # "Terpakai" saat rincian dihitung -> pembanding perubahan disk sesudahnya.
        "scan_used_bytes": int(used),
    }


def _live_df() -> dict | None:
    """Total/terpakai/sisa disk "/" saat INI (statvfs, instan)."""
    import shutil as _sh

    try:
        total, used, free = _sh.disk_usage("/")
    except OSError:
        return None
    return {
        "total_bytes": int(total),
        "used_bytes": int(used),
        "free_bytes": int(free),
        "used_percent": round(used / (used + free) * 100, 1) if used + free else 0.0,
        "reserved_bytes": max(0, int(total) - int(used) - int(free)),
    }


async def disk_usage(force: bool = False) -> dict:
    """Pemakaian disk: total LANGSUNG (df saat ini) + rincian per user dari pemindaian
    terakhir. Rincian dihitung ulang DI LATAR (tanpa memblokir) bila diminta (force),
    bila disk berubah >= 0,5 GB sejak rincian dihitung, atau bila sudah 15 menit.
    Data lama tetap dikembalikan dengan flag ``computing: true`` selama menghitung.
    """
    now = time.time()
    data = _disk_cache["data"]
    live = _live_df()
    scan_used = None
    if data is not None:
        scan_used = int(data.get("scan_used_bytes", data.get("used_bytes", 0)))
    changed = (
        live is not None and scan_used is not None
        and abs(live["used_bytes"] - scan_used) >= _RESCAN_DELTA
        and now - _disk_cache.get("finished", 0.0) >= _RESCAN_MIN_GAP
    )
    stale = data is None or now - _disk_cache["ts"] >= _DISK_TTL
    if (force or stale or changed) and not _disk_cache["computing"]:
        _disk_cache["computing"] = True

        async def _bg() -> None:
            try:
                _disk_cache["data"] = await _compute_disk()
                _disk_cache["ts"] = time.time()
            finally:
                _disk_cache["computing"] = False
                _disk_cache["finished"] = time.time()

        asyncio.create_task(_bg())
    if data is not None:
        out = {**data, "scan_used_bytes": scan_used}
        if live is not None:
            out.update(live)
            out["changed_since_scan_bytes"] = live["used_bytes"] - (scan_used or 0)
        out["computing"] = _disk_cache["computing"]
        return out
    empty = {
        "total_bytes": 0,
        "used_bytes": 0,
        "free_bytes": 0,
        "used_percent": 0.0,
        "reserved_bytes": 0,
        "users": [],
        "home_total_bytes": 0,
        "outside_home": [],
        "complete": False,
        "computed_at": None,
        "scan_used_bytes": None,
        "changed_since_scan_bytes": 0,
        "computing": True,
    }
    if live is not None:
        empty.update(live)
    return empty


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


_ASGI_APP_RE = re.compile(r"(?:^|\s)([A-Za-z_][\w.]*:[A-Za-z_]\w*)(?=\s|$)")


def _app_detail(command: str, name: str, wtype: str) -> str:
    """Rincian singkat aplikasi untuk label generik (mis. 'server:app', 'Next.js v16')."""
    cmd = command or ""
    if wtype == "api":
        m = _ASGI_APP_RE.search(cmd)
        if m:
            return m.group(1)
    if wtype == "frontend":
        m = re.search(r"next-server \(v([\d.]+)\)", cmd)
        if m:
            return f"Next.js v{m.group(1)}"
        for tok in cmd.split()[1:]:
            if tok.endswith((".js", ".mjs", ".cjs", ".ts")):
                return tok.split("/")[-1]
    return ""


# Proses pendukung ComputeHub di host: tampil sebagai layanan platform, bukan skrip biasa.
_COMPUTEHUB_PROCS = (
    ("computehub_devbox.py", "ComputeHub · Devbox"),
    ("computehub_kantong_vram.py", "ComputeHub · Devbox"),
    ("vram_pocket_daemon.py", "ComputeHub · Devbox"),
)


def _workload_for(pid: int, command: str, name: str = "") -> tuple[dict, dict | None]:
    """analyze_workload + identitas runtime, berlaku untuk proses SEMUA user.

    - Container Docker -> 'Docker / <project> / <service>'.
    - Service systemd (sistem / --user) -> '<jenis> (<detail>) · service <unit>'.
    Tipe workload asli dipertahankan agar klasifikasi sistem & sinyal tetap sama.
    """
    wl = analyze_workload(command, name)
    for marker, label in _COMPUTEHUB_PROCS:
        if marker in (command or ""):
            return {**wl, "label": label}, None
    try:
        ctr = container_identity.for_pid(pid)
    except Exception:  # noqa: BLE001
        ctr = None
    if ctr:
        return {**wl, "label": ctr["label"]}, ctr
    label = wl["label"]
    detail = _app_detail(command, name, wl["type"])
    if detail and "(" not in label:
        label = f"{label} ({detail})"
    try:
        unit = container_identity.systemd_unit_for_pid(pid)
    except Exception:  # noqa: BLE001
        unit = None
    if unit and unit["name"].lower() not in label.lower():
        kind = "service user" if unit["user"] else "service"
        if wl["type"] == "service":
            label = f"Service {'user' if unit['user'] else 'sistem'} ({unit['name']})"
        else:
            label = f"{label} · {kind} {unit['name']}"
    return {**wl, "label": label}, ctr


# --------------------------------------------------------------------------- #
#  Klasifikasi 'default/sistem' vs 'non-default' (workload nyata user)         #
# --------------------------------------------------------------------------- #
# Kata kunci proses INFRASTRUKTUR/bawaan (di luar akun sistem UID<1000).
_SYSTEM_PROC_KEYWORDS = (
    "systemd", "sshd", "cron", "dbus", "udev", "rsyslog", "snapd", "polkit",
    "accounts-daemon", "networkd", "resolved", "agetty", "irqbalance", "chronyd",
    "dockerd", "containerd", "docker-proxy",
    "postgres", "mysqld", "mariadbd", "mongod", "redis-server", "nginx",
    # Kubernetes / SLURM / container infra (UID container tinggi di host: pause/coredns/dll).
    "kube", "kubelet", "coredns", "pause", "containerd-shim", "runc",
    "node_exporter", "kube-state", "etcd", "flannel", "calico", "cri-o", "k3s", "slurm",
)
_VSCODE_KEYWORDS = (
    "vscode-server", ".vscode-server", "code-server", "pylance", "tsserver",
    "eslintserver", "copilot",
)


def _uid_of(username: str) -> int | None:
    # Username numerik (proses kontainer tanpa entri passwd host) = UID langsung.
    if username.isdigit():
        return int(username)
    try:
        import pwd

        return pwd.getpwnam(username).pw_uid
    except Exception:  # noqa: BLE001
        return None


_NOLOGIN_SHELLS = ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false")


def _is_service_account(username: str) -> bool:
    """Akun LAYANAN tanpa login interaktif (shell nologin/false) -> BUKAN user manusia.
    Menangkap nobody/slurm/www-data dll yang UID-nya bisa >= 1000."""
    try:
        import pwd

        shell = (pwd.getpwnam(username).pw_shell or "").strip()
    except Exception:  # noqa: BLE001
        return False
    return shell.endswith(("nologin", "false"))


def _is_system_user(username: str) -> bool:
    """Akun BAWAAN/sistem (BUKAN user login manusia). Mencakup: username NUMERIK (UID proses
    container tanpa entri passwd host, mis. 65532 coredns, 65535/10001 pause k8s); UID < 1000
    (root/systemd-*/sshd/messagebus/...); akun LAYANAN nologin (nobody, slurm, www-data)."""
    if username.isdigit():
        return True
    uid = _uid_of(username)
    if uid is not None and uid < 1000:
        return True
    return _is_service_account(username)


def is_human_user(username: str) -> bool:
    """User login MANUSIA nyata (bukan akun sistem/layanan/container). Kebalikan
    _is_system_user; dipakai laporan & alerts agar klasifikasi KONSISTEN."""
    return not _is_system_user(username)


def _groups_of(username: str) -> set[str]:
    """Nama grup Linux milik user (termasuk grup utama). Kosong bila tak terbaca."""
    try:
        import grp
        import pwd

        names = {g.gr_name for g in grp.getgrall() if username in g.gr_mem}
        try:
            names.add(grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name)
        except Exception:  # noqa: BLE001  (grup utama hilang -> abaikan)
            pass
        return names
    except Exception:  # noqa: BLE001  (/etc/group tak ter-mount)
        return set()


def is_server_manager(username: str) -> bool:
    """User Linux PENGELOLA server: punya sudo dan/atau akses Docker.

    Mereka memang berhak memakai mesin di luar batas mahasiswa (menjalankan layanan,
    memelihara server), sehingga ambang peringatannya dibedakan — kalau tidak,
    peringatan pelanggaran akan membanjir tanpa guna. Daftar grup & nama tambahan
    dapat diatur lewat ADMIN_OS_GROUPS / ADMIN_OS_USERS.
    """
    nama = (username or "").strip()
    if not nama:
        return False
    manual = {
        u.strip() for u in (settings.ADMIN_OS_USERS or "").split(",") if u.strip()
    }
    if nama in manual:
        return True
    grup_admin = {
        g.strip() for g in (settings.ADMIN_OS_GROUPS or "").split(",") if g.strip()
    }
    return bool(grup_admin & _groups_of(nama))


def _is_system_process(
    username: str, command: str = "", name: str = "", workload_type: str = ""
) -> bool:
    """True bila proses = 'default/sistem' (infrastruktur), BUKAN workload user nyata.

    Mencakup: akun UID<1000, layanan inti OS, Docker daemon/containerd, VS Code Remote
    server, dan backend ComputeHub sendiri (uvicorn app.main:app).
    """
    if _is_system_user(username):
        return True
    text = f"{command} {name}".lower()
    if "app.main:app" in text and "server-kampus" in text:  # backend ComputeHub KITA (bukan uvicorn user lain)
        return True
    if workload_type in ("service", "vscode"):
        return True
    if any(k in text for k in _VSCODE_KEYWORDS):
        return True
    if any(k in text for k in _SYSTEM_PROC_KEYWORDS):
        return True
    return False


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

_PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def _mem_split_mb(pid: int, rss_mb: float) -> tuple[float, float]:
    """(RAM privat, RSS) dalam MB untuk satu proses.

    RSS menghitung PENUH berkas yang dipetakan bersama (bobot model AI, pustaka) di
    SETIAP proses, jadi menjumlahkannya per user melebih-lebihkan berkali lipat: dua
    instance ComfyUI pernah tampak memakai 95 GB padahal sistem hanya memakai 37 GB.
    RAM privat = RSS dikurangi halaman bersama -> inilah yang benar-benar menekan
    memori. /proc/<pid>/statm terbaca semua orang, jadi tak perlu hak istimewa.
    """
    try:
        with open(f"/proc/{pid}/statm", "rb") as fh:
            bagian = fh.read().split()
        resident = int(bagian[1]) * _PAGE_SIZE
        bersama = int(bagian[2]) * _PAGE_SIZE
        return max(0.0, (resident - bersama) / _MB), resident / _MB
    except Exception:  # noqa: BLE001  (proses hilang / bukan Linux) -> pakai RSS apa adanya
        return rss_mb, rss_mb


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
                mem_rss = p.memory_info().rss / _MB
                ctimes = p.cpu_times()
                created = p.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:  # noqa: BLE001
            continue
        pid = info.get("pid")
        mem, mem_rss = _mem_split_mb(pid, mem_rss)
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
            "memory_rss_mb": round(mem_rss, 1),
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
        wl, ctr = _workload_for(pid, command, name)
        gp = {
            "gpu_index": gpu_index,
            "pid": pid,
            "username": username,
            "name": name,
            "command": command or name,
            "vram_mb": round(vram_mb, 1),
            "workload": wl["label"],
            "container": ctr,
        }
        gpu_processes.append(gp)
        gpu_by_pid[pid] = gp

    # Top proses (CPU) + label workload (baca cmdline utk subset kecil).
    top_sorted = sorted(rows, key=lambda r: (r["cpu_percent"], r["memory_mb"]), reverse=True)
    top_processes = []
    for r in top_sorted[:_TOP_LIMIT]:
        cmd = _cmdline(r["pid"])
        wl, ctr = _workload_for(r["pid"], cmd, r["name"])
        top_processes.append({
            **r,
            "command": cmd or r["name"],
            "workload": wl["label"],
            "container": ctr,
            "workload_type": wl["type"],
            "is_system": _is_system_process(r["username"], cmd, r["name"], wl["type"]),
        })

    # Agregasi per user OS (mirip PDF bagian 12).
    agg: dict[str, dict] = {}

    def _bucket(user: str) -> dict:
        return agg.setdefault(
            user,
            {
                "username": user,
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "memory_rss_mb": 0.0,
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
        b["memory_rss_mb"] += r.get("memory_rss_mb", r["memory_mb"])
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
            activity = _workload_for(b["_top_pid"], cmd, nm)[0]["label"]
        os_users.append(
            {
                "username": b["username"],
                "cpu_percent": round(b["cpu_percent"], 1),
                "cpu_cores_eq": round(b["cpu_percent"] / 100.0, 1),
                "memory_mb": round(b["memory_mb"], 1),
                # RSS mentah (berkas bersama dihitung berulang) — hanya utk pembanding.
                "memory_rss_mb": round(b["memory_rss_mb"], 1),
                "vram_mb": round(b["vram_mb"], 1),
                "gpu_indices": sorted(b["gpu_indices"]),
                "processes": b["processes"],
                "activity": activity or "—",
                "is_system": _is_system_user(b["username"]),
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


# Snapshot OS "hidup": selama ada admin membuka Laporan, sampler latar belakang
# memindai ulang tiap _OS_SAMPLE_INTERVAL detik sehingga request cukup membaca
# snapshot terbaru (tanpa menunggu scan). Satu scan ~0,25 dtk CPU (1 dari 64 core);
# sampler berhenti sendiri bila tak ada yang melihat selama _OS_IDLE_STOP detik.
_os_cache: dict = {"ts": 0.0, "data": None, "wall": 0.0}
_os_lock = threading.Lock()
_OS_SAMPLE_INTERVAL = 1.0
_OS_IDLE_STOP = 20.0
_os_last_access = 0.0
_os_sampler: asyncio.Task | None = None


def _refresh_os() -> dict:
    with _os_lock:
        data = _gather_os()
        _os_cache["ts"] = time.monotonic()
        _os_cache["wall"] = time.time()
        _os_cache["data"] = data
        return data


def _gather_os_cached() -> dict:
    global _os_last_access
    now = time.monotonic()
    _os_last_access = now
    # Sampler aktif -> snapshot berumur <= ~1 dtk; batas di bawah hanya cadangan.
    max_age = max(_OS_SAMPLE_INTERVAL * 2.5, 1.0)
    if _os_cache["data"] is not None and (now - _os_cache["ts"]) < max_age:
        return _os_cache["data"]
    return _refresh_os()


async def _os_sampler_loop() -> None:
    global _os_sampler
    try:
        while time.monotonic() - _os_last_access < _OS_IDLE_STOP:
            try:
                await asyncio.to_thread(_refresh_os)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Sampler OS gagal: %s", exc)
            await asyncio.sleep(_OS_SAMPLE_INTERVAL)
    finally:
        _os_sampler = None


def _ensure_os_sampler() -> None:
    global _os_sampler
    if _os_sampler is None or _os_sampler.done():
        _os_sampler = asyncio.get_running_loop().create_task(_os_sampler_loop())


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
                User.is_local,
                User.sso_sub,
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
                User.last_seen_at,
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
    # Pemakaian /persist per akun: pakai snapshot storage_guard (du tiap 5 menit),
    # bukan du baru per request. Impor malas: storage_guard -> alerts -> report.
    from app.services import storage_guard as storage_guard_svc

    disk_snap = storage_guard_svc.usage_snapshot()
    for (uid, name, email, role, is_local, sso_sub, total, succ, failed, cancelled, running, queued, secs_total, peak_ram, peak_vram, peak_cpu, last_at, last_seen) in rows:
        disk = disk_snap.get(uid) if disk_snap else None
        users.append(
            {
                "user_id": uid,
                "name": name,
                "email": email,
                "role": role.value if hasattr(role, "value") else str(role),
                "is_local": bool(is_local),
                "is_sso": bool(sso_sub),
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
                "last_seen_at": last_seen.isoformat() if last_seen else None,
                # Sudah dipindai tapi folder user belum ada = benar-benar 0.
                "storage_used_mb": (float(disk["used_mb"]) if disk else 0.0) if disk_snap else None,
                "storage_quota_mb": float(disk["quota_mb"]) if disk else None,
                "storage_scanned_at": (
                    dt.datetime.fromtimestamp(disk["scanned_at"], dt.timezone.utc).isoformat()
                    if disk and disk.get("scanned_at") else None
                ),
                "storage_scanning": storage_guard_svc.is_scanning(uid),
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

    devbox_ids = [
        job.id for job, _owner in run_rows
        if job.is_interactive and job.name == "Devbox VS Code"
    ]
    latest_metrics = await _running_job_metrics(session, devbox_ids, now)
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
                "is_local": bool(owner.is_local),
                "is_sso": bool(owner.sso_sub),
                "gpu_index": job.gpu_index,
                "pid": job.pid,
                "source_type": job.source_type.value if hasattr(job.source_type, "value") else str(job.source_type),
                "runtime_seconds": runtime,
                "peak_ram_mb": job.peak_ram_mb,
                "peak_vram_mb": job.peak_vram_mb,
                "peak_cpu_percent": job.peak_cpu_percent,
                "avg_gpu_util_percent": job.avg_gpu_util_percent,
                "started_at": started.isoformat() if started else None,
                "is_devbox": job.id in devbox_ids,
                **latest_metrics.get(job.id, {}),
            }
        )

    total_users = await session.scalar(select(func.count(User.id)))
    known = {u["user_id"] for u in users}
    orphans = [v for k, v in disk_snap.items() if k not in known]
    scan = storage_guard_svc.scan_status()
    storage = {
        "total_bytes": int(sum(int(v.get("bytes", v["used_mb"] * 1024 * 1024)) for v in disk_snap.values())),
        "accounts": sum(1 for k in disk_snap if k in known),
        "orphan_bytes": int(sum(int(v.get("bytes", v["used_mb"] * 1024 * 1024)) for v in orphans)),
        "orphan_count": len(orphans),
        "folders": scan.get("folders"),
        "full_running": scan["full_running"],
        "full_finished_at": (
            dt.datetime.fromtimestamp(scan["full_finished_at"], dt.timezone.utc).isoformat()
            if scan["full_finished_at"] else None
        ),
    }
    return {
        "users": users,
        "storage": storage,
        "running_jobs": running_jobs,
        "platform_users": int(total_users or 0),
        "now": now.isoformat(),
    }


async def build_report(session: AsyncSession) -> dict:
    """Laporan ringkas (OS-level + platform-level)."""
    os_data = await asyncio.to_thread(_gather_os_cached)
    _ensure_os_sampler()
    plat = await _platform_data(session)

    os_data["system"]["platform_users"] = plat["platform_users"]
    os_data["system"]["now"] = plat["now"]
    os_data["system"]["sampled_at"] = dt.datetime.fromtimestamp(
        _os_cache["wall"] or time.time(), dt.timezone.utc
    ).isoformat()

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
        "storage": plat["storage"],
        # Siapa yang memakai layanan LLM bersama: sisi USER LINUX (pemilik socket)
        # dan sisi AKUN ComputeHub (catatan permintaan asisten).
        "llm_connections": llm_attrib.peta_koneksi(),
        "llm_users": await assistant_usage_svc.ringkasan(session, days=30, limit=25),
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
        wl, ctr = _workload_for(r["pid"], cmd, r["name"])
        enriched.append(
            {
                **r,
                "command": cmd or r["name"],
                "workload": wl["label"],
                "container": ctr,
                "workload_type": wl["type"],
                "is_system": _is_system_process(username, cmd, r["name"], wl["type"]),
                "gpu_index": gp["gpu_index"] if gp else None,
                "gpu_vram_mb": gp["vram_mb"] if gp else 0.0,
                "started": _fmt_dt(r["create_time"]) if r.get("create_time") else "",
                "runtime_seconds": max(0.0, time.time() - r["create_time"]) if r.get("create_time") else None,
            }
        )

    # Proses utama: utamakan WORKLOAD nyata user (non-default), prioritas GPU lalu CPU.
    main = None
    if enriched:
        pool = [e for e in enriched if not e["is_system"]] or enriched
        on_gpu = [e for e in pool if e["gpu_vram_mb"] > 0]
        main = (
            max(on_gpu, key=lambda e: e["gpu_vram_mb"])
            if on_gpu
            else max(pool, key=lambda e: e["cpu_percent"])
        )
    supporting = [e for e in enriched if main is None or e["pid"] != main["pid"]]
    supporting = sorted(supporting, key=lambda e: e["cpu_percent"], reverse=True)[:15]

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
        findings.append({"level": "warn", "text": f"Swap terpakai {system['swap_used_mb']/1024:.1f} GiB — ada tekanan memori."})
    if total_ram < 4096:
        findings.append({"level": "ok", "text": f"RAM hemat: {total_ram/1024:.1f} GiB."})

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
        f"Pemakaian CPU ~{cores_eq:.0f} core ({total_cpu:.0f}%), RAM {total_ram/1024:.1f} GiB"
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
        # Siapa yang terhubung ke layanan LLM bersama (Ollama dsb) saat laporan
        # dibuat — menjembatani beban akun layanan ke pemakai sebenarnya.
        "llm_connections": llm_attrib.peta_koneksi(),
        "findings": findings,
        "recommendations": {"high": rec_high, "medium": rec_med, "low": rec_low},
        "summary": summary,
        "comparison": osd["os_users"],
        "conclusion": conclusion,
    }


async def user_report(
    username: str, session: AsyncSession | None = None, *, days: int = 30
) -> dict:
    """Laporan detail per-user OS (fleksibel sesuai workload).

    Bila `session` diberikan, potret sesaat dilengkapi RIWAYAT dari arsip:
    rekap harian, rincian per jam, dan pemakaian layanan LLM.
    """
    rep = await asyncio.to_thread(_user_report_sync, username)
    if session is None:
        return rep
    # Impor lokal: usage_history mengimpor modul ini -> hindari lingkaran impor.
    from app.services import usage_history as usage_history_svc

    rep["days"] = days
    rep["harian"] = await usage_history_svc.daily_summary(
        session, days=days, username=username
    )
    rep["jam"] = await usage_history_svc.hourly_detail(
        session, username=username, days=min(days, 7)
    )
    rep["llm_harian"] = await usage_history_svc.daily_summary_llm(
        session, days=days, nama=username
    )

    # Job adalah konsep ComputeHub. Ditampilkan HANYA bila akun Linux ini memang
    # terkait sebuah akun platform -- kalau tidak, bagiannya sengaja dihilangkan
    # daripada memajang tabel kosong yang menyesatkan.
    from app.models.user import User as _User

    akun = (
        await session.execute(select(_User).where(_User.username == username))
    ).scalars().first()
    if akun is not None:
        rep["computehub"] = {
            "user_id": akun.id,
            "nama": akun.name,
            "email": akun.email,
            "role": akun.role.value if hasattr(akun.role, "value") else str(akun.role),
        }
        rep["harian_job"] = await usage_history_svc.daily_summary_computehub(
            session, days=days, user_id=akun.id
        )
    return rep


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
    return f"{mb/1024:.1f} GiB"


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
        if main.get("container"):
            c = main["container"]
            main_html += (
                f"<p class='muted'><b>Container:</b> {_e(c['label'])}"
                f"{' · ' + _e(c['name']) if c.get('name') else ''} ({_e(c['id'])})</p>"
            )

    support_tbl = "".join(
        f"<tr><td>{_e(e['pid'])}</td><td>{_e(e['name'])}"
        f"{'<br><span class=muted>' + _e(e['container']['name']) + '</span>' if (e.get('container') or {}).get('name') else ''}"
        f"</td><td>{_e(e['workload'])}</td>"
        f"<td class='r'>{e['cpu_percent']:.0f}%</td><td class='r'>{_gb(e['memory_mb'])}</td></tr>"
        for e in r["processes"]["supporting"]
    ) or "<tr><td colspan='5' class='muted'>—</td></tr>"

    findings_html = "".join(
        f"<li><span class='badge {f['level'] if f['level'] in ('ok','warn') else 'info'}'>"
        f"{'OK' if f['level']=='ok' else 'PERHATIAN'}</span> {_e(f['text'])}</li>"
        for f in r["findings"]
    )

    # Seksi atribusi layanan LLM bersama — hanya dirender bila ada koneksi.
    llm = r.get("llm_connections") or {}
    llm_html = ""
    if llm.get("total"):
        klien = "".join(
            f"<tr><td>{_e(k['user'])}</td><td>{_e(k['uid'])}</td>"
            f"<td class='r'>{_e(k['koneksi'])}</td></tr>"
            for k in llm.get("klien", [])
        ) or "<tr><td colspan='3' class='muted'>—</td></tr>"
        asal = "".join(
            f"<tr><td>{_e(s['asal'])}</td><td class='r'>{_e(s['koneksi'])}</td></tr>"
            for s in llm.get("server", [])
        ) or "<tr><td colspan='2' class='muted'>—</td></tr>"
        llm_html = f"""
<h2>6. Pihak Terhubung ke Layanan LLM Bersama</h2>
<p class="muted">Snapshot socket kernel saat laporan dibuat (port
{_e(', '.join(str(p) for p in llm.get('ports', [])))}). Menjembatani beban akun layanan
ke pemakai sebenarnya.</p>
<h3>6.1 Pemakai (pemilik socket klien)</h3>
<table><thead><tr><th>User</th><th>UID</th><th class="r">Koneksi</th></tr></thead>
<tbody>{klien}</tbody></table>
<h3>6.2 Asal koneksi masuk</h3>
<table><thead><tr><th>Asal (host / container)</th><th class="r">Koneksi</th></tr></thead>
<tbody>{asal}</tbody></table>"""

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
{llm_html}
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
        f"<tr><td>{_e(u['name'])}<br><span class='muted'>{_e(u['email'])}"
        f" · {'Lokal' if u.get('is_local') else 'ComputeHub'}</span></td><td>{_e(u['role'])}</td>"
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
