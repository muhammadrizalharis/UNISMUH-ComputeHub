#!/usr/bin/env python3
"""Catat bukti operasional (backup / restore drill / offsite) ke tabel ops_events.

Dipanggil dari skrip host (backup.sh, restore_drill.sh, health_watchdog.sh) supaya
hasilnya TERSIMPAN DI DATABASE dan tampil di web (Pengaturan > Cadangan & Pemulihan),
bukan hanya lewat email/Telegram yang bisa terhapus.

Pemakaian:
  ops_event.py --kind backup --status ok --title "Backup selesai" \
      [--detail "teks" | --detail-file PATH] [--data '{"json":1}'] \
      [--duration 123] [--source backup.sh] [--at 2026-10-04T02:30:00+08:00] \
      [--dedup-key kunci-unik]
  ops_event.py --backfill          # rekonstruksi riwayat dari arsip .gpg + snapshot restic

Selalu exit 0 (best-effort). Setiap event juga ditulis ke berkas append-only
~/.computehub/ops-events.jsonl; bila DB tidak terjangkau, event diantrekan di
~/.computehub/ops-events.pending.jsonl dan dikirim ulang pada pemanggilan berikutnya.
Stdlib saja (dijalankan python3 sistem).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path(os.environ.get("HOME") or Path("~").expanduser())
CH_DIR = HOME / ".computehub"
LOG_FILE = CH_DIR / "ops-events.jsonl"
PENDING_FILE = CH_DIR / "ops-events.pending.jsonl"
PG_CONTAINER = os.environ.get("COMPUTEHUB_PG_CONTAINER", "ComputeHub-postgres")

# DDL identik dengan backend/app/models/ops_event.py (create_all melewati tabel yang ada).
DDL = """
CREATE TABLE IF NOT EXISTS ops_events (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    kind VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    title VARCHAR(200) NOT NULL,
    detail TEXT NOT NULL,
    data JSON,
    duration_seconds INTEGER,
    source VARCHAR(64) NOT NULL,
    dedup_key VARCHAR(128) UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_ops_events_created_at ON ops_events (created_at);
CREATE INDEX IF NOT EXISTS ix_ops_events_kind ON ops_events (kind);
"""


def _docker_argv() -> list[str] | None:
    """`docker` langsung bila boleh, kalau tidak `sudo -n docker` (pola backup.sh)."""
    docker = shutil.which("docker") or "/usr/bin/docker"
    for argv in ([docker], ["sudo", "-n", docker]):
        try:
            ok = subprocess.run(
                [*argv, "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=20, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if ok.returncode == 0 and PG_CONTAINER in ok.stdout.split():
            return argv
    return None


def _psql(docker: list[str], script: str) -> bool:
    proc = subprocess.run(
        [*docker, "exec", "-i", PG_CONTAINER, "sh", "-c",
         'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
        input=script, capture_output=True, text=True, timeout=60, check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.strip()[-400:] + "\n")
    return proc.returncode == 0


def _q(value: str) -> str:
    """Literal psql \\set satu baris: backslash & kutip tunggal dinetralkan,
    baris baru jadi urutan \\n (psql menafsirkannya kembali di dalam kutip tunggal)."""
    value = value.replace("\\", "\\\\").replace("'", "''")
    value = value.replace("\r", "").replace("\n", "\\n")
    return "'" + value + "'"


def _insert_sql(ev: dict) -> str:
    lines = [
        f"\\set kind {_q(ev['kind'])}",
        f"\\set status {_q(ev['status'])}",
        f"\\set title {_q(ev['title'][:200])}",
        f"\\set detail {_q(ev.get('detail') or '')}",
        f"\\set data {_q(json.dumps(ev.get('data') or {}, ensure_ascii=False))}",
        f"\\set duration {_q('' if ev.get('duration_seconds') is None else str(int(ev['duration_seconds'])))}",
        f"\\set source {_q((ev.get('source') or '')[:64])}",
        f"\\set at {_q(ev['created_at'])}",
        f"\\set dedup {_q(ev.get('dedup_key') or '')}",
        "INSERT INTO ops_events (created_at, kind, status, title, detail, data, duration_seconds, source, dedup_key)",
        "VALUES (:'at'::timestamptz, :'kind', :'status', :'title', :'detail', :'data'::json,",
        "        NULLIF(:'duration','')::int, :'source', NULLIF(:'dedup',''))",
        "ON CONFLICT (dedup_key) DO NOTHING;",
    ]
    return "\n".join(lines) + "\n"


def _append(path: Path, ev: dict) -> None:
    CH_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _flush_pending(docker: list[str]) -> None:
    if not PENDING_FILE.exists():
        return
    rows = [line for line in PENDING_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    sisa: list[str] = []
    for line in rows:
        try:
            ev = json.loads(line)
            if not _psql(docker, _insert_sql(ev)):
                sisa.append(line)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            sisa.append(line)
    if sisa:
        PENDING_FILE.write_text("\n".join(sisa) + "\n", encoding="utf-8")
    else:
        PENDING_FILE.unlink(missing_ok=True)


def record(ev: dict) -> bool:
    """Tulis ke berkas log + DB. Return True bila DB berhasil."""
    _append(LOG_FILE, ev)
    docker = _docker_argv()
    if docker is None or not _psql(docker, DDL):
        _append(PENDING_FILE, ev)
        return False
    _flush_pending(docker)
    if not _psql(docker, _insert_sql(ev)):
        _append(PENDING_FILE, ev)
        return False
    return True


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _backfill_events() -> list[dict]:
    """Rekonstruksi riwayat dari bukti fisik yang masih ada: arsip .gpg + snapshot restic."""
    events: list[dict] = []
    enc_dir = Path(os.environ.get("COMPUTEHUB_BACKUP_ENC_DIR") or CH_DIR / "backups_enc")
    seen: set[str] = set()
    for path in sorted(enc_dir.rglob("computehub-*.tar.gz.gpg")):
        if path.name in seen:
            continue
        seen.add(path.name)
        m = re.match(r"computehub-(\d{8})-(\d{6})", path.name)
        if m:
            at = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").astimezone()
        else:
            at = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        size = path.stat().st_size
        events.append({
            "created_at": at.isoformat(timespec="seconds"),
            "kind": "backup", "status": "ok",
            "title": "Arsip tar terenkripsi (rekonstruksi dari berkas)",
            "detail": f"{path.name} ({size / 1024**3:.2f} GB) masih tersimpan di server.",
            "data": {"archive": path.name, "archive_bytes": size, "backfill": True},
            "source": "ops_event.py --backfill",
            "dedup_key": f"archive:{path.name}",
        })
    restic = os.environ.get("RESTIC_BIN") or str(HOME / "bin" / "restic")
    repo = os.environ.get("COMPUTEHUB_RESTIC_REPO") or str(CH_DIR / "restic-repo")
    passfile = CH_DIR / "backup.pass"
    if Path(restic).exists() and passfile.exists():
        env = {**os.environ, "RESTIC_PASSWORD_FILE": str(passfile), "RESTIC_REPOSITORY": repo}
        try:
            out = subprocess.run(
                [restic, "snapshots", "--json", "--tag", "computehub"],
                capture_output=True, text=True, timeout=120, check=False, env=env,
            )
            snaps = json.loads(out.stdout or "[]") if out.returncode == 0 else []
        except (OSError, ValueError, subprocess.TimeoutExpired):
            snaps = []
        for snap in snaps:
            sid = str(snap.get("short_id") or snap.get("id", "")[:8])
            events.append({
                "created_at": snap["time"],
                "kind": "backup", "status": "ok",
                "title": "Snapshot restic (rekonstruksi dari repo)",
                "detail": f"Snapshot {sid} tersimpan di repo restic lokal.",
                "data": {"restic_snapshot": sid, "backfill": True},
                "source": "ops_event.py --backfill",
                "dedup_key": f"restic:{snap.get('id', sid)}",
            })
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=["backup", "restore", "restore_drill", "offsite", "watchdog"])
    ap.add_argument("--status", choices=["ok", "warn", "fail"])
    ap.add_argument("--title")
    ap.add_argument("--detail", default="")
    ap.add_argument("--detail-file")
    ap.add_argument("--data", default="{}", help="JSON objek")
    ap.add_argument("--duration", type=int)
    ap.add_argument("--source", default="")
    ap.add_argument("--at", help="ISO-8601; default sekarang")
    ap.add_argument("--dedup-key")
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()

    if args.backfill:
        events = _backfill_events()
        docker = _docker_argv()
        if docker is None or not _psql(docker, DDL):
            print("DB tidak terjangkau; backfill dibatalkan.")
            return 0
        ok = sum(1 for ev in events if _psql(docker, _insert_sql(ev)))
        print(f"Backfill: {ok}/{len(events)} event dikirim (duplikat diabaikan oleh dedup_key).")
        return 0

    if not (args.kind and args.status and args.title):
        ap.error("--kind, --status, --title wajib (atau --backfill)")
    detail = args.detail
    if args.detail_file:
        try:
            detail = Path(args.detail_file).read_text(encoding="utf-8", errors="replace")[-8000:]
        except OSError:
            pass
    try:
        data = json.loads(args.data or "{}")
        if not isinstance(data, dict):
            data = {"value": data}
    except ValueError:
        data = {"raw": args.data}
    ev = {
        "created_at": args.at or _now_iso(),
        "kind": args.kind,
        "status": args.status,
        "title": args.title,
        "detail": detail,
        "data": data,
        "duration_seconds": args.duration,
        "source": args.source,
        "dedup_key": args.dedup_key,
    }
    print("ops_event: tersimpan di DB" if record(ev) else "ops_event: DB belum terjangkau, diantrekan")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — jangan pernah menggagalkan skrip pemanggil
        sys.stderr.write(f"ops_event gagal: {exc!r}\n")
        sys.exit(0)
