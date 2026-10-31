#!/usr/bin/env python3
"""Jurnal operasional harian ComputeHub -> docs/ops-journal/YYYY/YYYY-MM-DD.md.

Hanya angka agregat dan status layanan; tanpa nama pengguna, email, path berkas
pengguna, token, atau isi backup. Backup tetap TIDAK pernah dipush.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "docs" / "ops-journal"
ZONE = zoneinfo.ZoneInfo("Asia/Makassar")
# Rencana commit harian acak (tersebar sepanjang hari) disimpan di luar repo.
PLAN_FILE = Path.home() / ".computehub" / "ops-journal-plan.json"
MIN_COMMITS = 2
MAX_COMMITS = 10
# Jendela jam (WITA) tempat commit boleh dijadwalkan: 07:00 s/d 21:59.
WINDOW_START_MIN = 7 * 60
WINDOW_END_MIN = 22 * 60
HEALTH_URLS = ("http://127.0.0.1:8088/health", "https://computehub.lab.if.unismuh.ac.id/health")
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(token|secret|password|passphrase|api[_-]?key)\s*[:=]"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"/home/[^\s]+"),
)


def run(argv: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def health(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
            return "ok" if response.status == 200 else f"http {response.status}"
    except Exception as exc:  # noqa: BLE001
        return f"gagal ({type(exc).__name__})"


def sql(query: str) -> str:
    code, out = run(["docker", "exec", "ComputeHub-postgres", "psql", "-X", "-At", "-U", "computehub", "-d", "computehub", "-c", query])
    return out if code == 0 else "tidak tersedia"


def unit_state(unit: str) -> str:
    code, out = run(["systemctl", "--user", "show", unit, "--property=ActiveState", "--property=Result", "--value"])
    return " / ".join(out.split()) if code == 0 and out else "tidak tersedia"


def timers() -> list[str]:
    code, out = run(["systemctl", "--user", "list-timers", "--all", "--no-pager", "--output=json"])
    if code != 0:
        return ["tidak tersedia"]
    try:
        rows = json.loads(out)
    except ValueError:
        return ["tidak tersedia"]
    return [
        f"{row['unit']}: aktif berikutnya {dt.datetime.fromtimestamp(row['next'] / 1_000_000, ZONE):%Y-%m-%d %H:%M}"
        if row.get("next") else f"{row['unit']}: tanpa jadwal"
        for row in rows if str(row.get("unit", "")).startswith("computehub-")
    ] or ["tidak ada timer computehub"]


def backend_tests() -> str:
    code, out = run(["docker", "exec", "-e", "PYTHONDONTWRITEBYTECODE=1", "ComputeHub-app", "python", "-m", "unittest", "tests.test_workspace", "tests.test_devbox"], timeout=600)
    summary = re.search(r"^Ran \d+ tests?.*$", out, re.M)
    status = "OK" if code == 0 else "GAGAL"
    return f"{status} ({summary.group(0) if summary else 'ringkasan tidak terbaca'})"


def gpu_summary() -> list[str]:
    code, out = run(["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"])
    if code != 0:
        return ["nvidia-smi tidak tersedia"]
    lines = []
    for line in out.splitlines():
        index, used, total, util = [part.strip() for part in line.split(",")]
        lines.append(f"GPU {index}: {used}/{total} MiB terpakai, utilisasi {util}%")
    return lines


def redact(text: str) -> str:
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            raise SystemExit(f"Jurnal dibatalkan: pola sensitif terdeteksi ({pattern.pattern[:24]}...)")
    return text


def build_snapshot(slot_time: str) -> str:
    """Blok snapshot ringan (health + status layanan + GPU) berlabel jam slot."""
    text = "\n".join([
        f"## Snapshot {slot_time} WITA",
        f"- Health lokal: {health(HEALTH_URLS[0])}",
        f"- computehub.service: {unit_state('computehub.service')}",
        *[f"- {line}" for line in gpu_summary()],
        "",
    ])
    return redact(text)


def build_journal(today: dt.date) -> str:
    since = f"{today - dt.timedelta(days=1)}T00:00:00+08:00"
    until = f"{today}T00:00:00+08:00"
    jobs = sql(
        "SELECT status, count(*) FROM jobs WHERE finished_at >= %s AND finished_at < %s GROUP BY status ORDER BY status;"
        % (f"'{since}'", f"'{until}'")
    )
    devbox = sql(
        "SELECT count(*) FROM jobs WHERE name='Devbox VS Code' AND started_at >= %s AND started_at < %s;"
        % (f"'{since}'", f"'{until}'")
    )
    active_users = sql(
        "SELECT count(DISTINCT user_id) FROM jobs WHERE submitted_at >= %s AND submitted_at < %s;"
        % (f"'{since}'", f"'{until}'")
    )
    samples = sql(
        "SELECT count(*) FROM resource_samples WHERE ts >= %s AND ts < %s AND scope='job';"
        % (f"'{since}'", f"'{until}'")
    )
    version = re.search(r"APP_VERSION = '([^']+)'", (ROOT / "frontend/src/lib/version.ts").read_text(encoding="utf-8"))
    job_lines = [f"- {line.replace('|', ': ')}" for line in jobs.splitlines()] or ["- tidak ada job selesai"]
    text = "\n".join([
        f"# Jurnal Operasional {today:%d %B %Y}",
        "",
        f"Dibuat otomatis {dt.datetime.now(ZONE):%Y-%m-%d %H:%M} WITA untuk periode {today - dt.timedelta(days=1)} (WITA).",
        "Hanya agregat dan status layanan; tidak memuat identitas pengguna, berkas pengguna, rahasia, atau isi backup.",
        "",
        "## Layanan",
        f"- Versi aplikasi: {version.group(1) if version else 'tidak terbaca'}",
        f"- Health lokal: {health(HEALTH_URLS[0])}",
        f"- Health domain kampus: {health(HEALTH_URLS[1])}",
        f"- computehub.service: {unit_state('computehub.service')}",
        f"- Backup terakhir: {unit_state('computehub-backup.service')}",
        f"- Watchdog terakhir: {unit_state('computehub-watchdog.service')}",
        "",
        "## Jadwal otomatis",
        *[f"- {line}" for line in timers()],
        "",
        "## Pemakaian kemarin",
        f"- Pengguna yang mengirim job/sesi: {active_users}",
        f"- Sesi Devbox dimulai: {devbox}",
        f"- Sampel resource job tercatat: {samples}",
        "- Job selesai per status:",
        *job_lines,
        "",
        "## GPU saat jurnal dibuat",
        *[f"- {line}" for line in gpu_summary()],
        "",
        "## Uji backend",
        f"- tests.test_workspace + tests.test_devbox: {backend_tests()}",
        "",
    ])
    return redact(text)


def ensure_clean_repo() -> None:
    code, out = run(["git", "-C", str(ROOT), "status", "--porcelain"])
    if code != 0:
        raise SystemExit("git status gagal")
    others = [line for line in out.splitlines() if "docs/ops-journal/" not in line]
    if others:
        raise SystemExit("Jurnal dibatalkan: ada perubahan lain yang belum di-commit")


def commit_and_push(path: Path, message: str) -> None:
    relative = path.relative_to(ROOT).as_posix()
    if os.environ.get("OPS_JOURNAL_NO_PUSH"):
        print(f"Jurnal ditulis tanpa push: {relative} ({message})")
        return
    ensure_clean_repo()
    for argv in (
        ["git", "-C", str(ROOT), "add", "--", relative],
        ["git", "-C", str(ROOT), "commit", "-m", message],
        ["git", "-C", str(ROOT), "push", "origin", "main"],
    ):
        code, out = run(argv, timeout=180)
        if code != 0:
            raise SystemExit(f"{' '.join(argv[3:5])} gagal: {out[-300:]}")
    print(f"Jurnal dipush: {relative} ({message})")


def _load_plan() -> dict:
    try:
        return json.loads(PLAN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_plan(plan: dict) -> None:
    PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def make_plan(today: dt.date) -> dict:
    """Pilih N acak (2-10) menit commit dalam jendela 07:00-22:00 untuk hari ini."""
    count = random.randint(MIN_COMMITS, MAX_COMMITS)
    minutes = sorted(random.sample(range(WINDOW_START_MIN, WINDOW_END_MIN), count))
    slots = [
        {"time": f"{m // 60:02d}:{m % 60:02d}", "kind": "full" if i == 0 else "snapshot", "done": False}
        for i, m in enumerate(minutes)
    ]
    return {"date": today.isoformat(), "slots": slots}


def _emit(slot: dict, today: dt.date, path: Path) -> None:
    """Jalankan satu slot: commit penuh (laporan harian) atau snapshot ringan."""
    if slot["kind"] == "full":
        path.write_text(build_journal(today), encoding="utf-8")
        commit_and_push(path, f"docs(ops): jurnal operasional {path.stem}")
    else:
        if not path.exists():
            # Snapshot tidak boleh mendahului laporan penuh; tulis laporan dulu.
            path.write_text(build_journal(today), encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + build_snapshot(slot["time"]))
        commit_and_push(path, f"docs(ops): snapshot {today.isoformat()} {slot['time']}")


def main() -> int:
    now = dt.datetime.now(ZONE)
    today = now.date()
    # Mode manual: beri argumen tanggal untuk membuat laporan penuh sekali (uji/backfill).
    if len(sys.argv) > 1:
        day = dt.date.fromisoformat(sys.argv[1])
        path = JOURNAL_DIR / f"{day:%Y}" / f"{day:%Y-%m-%d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_journal(day), encoding="utf-8")
        commit_and_push(path, f"docs(ops): jurnal operasional {path.stem}")
        return 0

    plan = _load_plan()
    cur_min = now.hour * 60 + now.minute
    if not (WINDOW_START_MIN <= cur_min < WINDOW_END_MIN):
        print("Di luar jendela commit (07:00-22:00); tidak ada aksi.")
        return 0
    if plan.get("date") != today.isoformat():
        plan = make_plan(today)
        _save_plan(plan)
        print(f"Rencana baru {today}: {len(plan['slots'])} commit — "
              + ", ".join(s["time"] for s in plan["slots"]))

    path = JOURNAL_DIR / f"{today:%Y}" / f"{today:%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = f"{now:%H:%M}"
    due = [s for s in plan["slots"] if not s["done"] and s["time"] <= current]
    if not due:
        print("Belum ada slot jatuh tempo; tidak ada commit.")
        return 0

    for slot in due:
        _emit(slot, today, path)
        slot["done"] = True
        _save_plan(plan)
        time.sleep(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
