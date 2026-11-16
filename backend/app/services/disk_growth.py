"""Riwayat pertumbuhan disk "/" — dibaca dari file yang ditulis
scripts/disk_growth_watch.sh (timer tiap 10 menit, di host):

- ``~/.computehub/logs/disk/tren-YYYY-MM.csv``  : waktu,sisa_gb,terpakai_pct,turun_gb_per_jam
- ``~/.computehub/logs/disk/lonjakan/YYYYmmdd-HHMM.txt`` : rekaman pelaku saat lonjakan

Hanya untuk admin: file lonjakan memuat nama user & perintah proses lain.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path

from app.core.config import settings

MAX_DAYS = 30
MAX_POINTS = 360
SPIKE_NAME_RE = re.compile(r"^\d{8}-\d{4}$")
_RATE_RE = re.compile(r"turun ([\d.]+) GB dalam ~1 jam \(laju ([\d.]+) GB/jam\)")


def log_dir() -> Path:
    return settings.docker_user_data_root.parent / "logs" / "disk"


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read_trend(base: Path, since: dt.datetime) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(base.glob("tren-*.csv")):
        # Lewati bulan yang seluruhnya sebelum `since` (nama file = YYYY-MM).
        if p.stem[5:] < since.strftime("%Y-%m"):
            continue
        try:
            with p.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    try:
                        t = dt.datetime.strptime(r["waktu"], "%Y-%m-%d %H:%M:%S")
                    except (KeyError, ValueError):
                        continue
                    if t < since:
                        continue
                    free = _f(r.get("sisa_gb", ""))
                    if free is None:
                        continue
                    rows.append({
                        "t": t.isoformat(),
                        "free_gb": free,
                        "used_pct": _f(r.get("terpakai_pct", "")),
                        "drop_gb_per_h": _f(r.get("turun_gb_per_jam", "")),
                    })
        except OSError:
            continue
    return rows


def _downsample(rows: list[dict]) -> list[dict]:
    """Kurangi titik untuk grafik; per ember ambil sisa disk TERKECIL agar
    lonjakan (tebing) tidak hilang saat dirata-rata."""
    if len(rows) <= MAX_POINTS:
        return rows
    step = len(rows) / MAX_POINTS
    out = []
    for i in range(MAX_POINTS):
        chunk = rows[int(i * step): int((i + 1) * step)] or [rows[-1]]
        out.append(min(chunk, key=lambda r: r["free_gb"]))
    return out


def _parse_spike(p: Path) -> dict:
    drop = rate = None
    top = ""
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for i, ln in enumerate(lines):
        m = _RATE_RE.search(ln)
        if m:
            drop, rate = float(m.group(1)), float(m.group(2))
        if ln.startswith("== Proses penulis terbesar") and i + 1 < len(lines):
            top = lines[i + 1].strip()[:160]
    t = dt.datetime.strptime(p.stem, "%Y%m%d-%H%M")
    return {"name": p.stem, "t": t.isoformat(), "drop_gb": drop, "rate_gb_per_h": rate, "top_writer": top}


def growth(days: int = 7) -> dict:
    days = max(1, min(int(days), MAX_DAYS))
    base = log_dir()
    since = dt.datetime.now() - dt.timedelta(days=days)
    rows = _read_trend(base, since) if base.is_dir() else []
    spikes = []
    sdir = base / "lonjakan"
    if sdir.is_dir():
        for p in sdir.glob("*.txt"):
            if not SPIKE_NAME_RE.match(p.stem):
                continue
            try:
                s = _parse_spike(p)
            except ValueError:
                continue
            if s["t"] >= since.isoformat():
                spikes.append(s)
    spikes.sort(key=lambda s: s["t"], reverse=True)
    max_drop = max((r["drop_gb_per_h"] or 0 for r in rows), default=0)
    return {
        "days": days,
        "available": base.is_dir(),
        "points": _downsample(rows),
        "spikes": spikes,
        "max_drop_gb_per_h": max_drop,
        "latest": rows[-1] if rows else None,
    }


def spike_detail(name: str) -> str | None:
    if not SPIKE_NAME_RE.match(name):
        return None
    p = log_dir() / "lonjakan" / f"{name}.txt"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
