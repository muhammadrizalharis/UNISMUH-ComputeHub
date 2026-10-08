#!/usr/bin/env python3
"""Manifest backup ComputeHub — rincian isi arsip untuk Pengaturan > Cadangan & Pemulihan.

Dipanggil backup.sh dua kali (stdlib saja, python3 sistem):

  backup_manifest.py stage --staging DIR [--label manual-web] [--requested-by nama] [--request-id id]
      Memindai folder staging (users/, db.sql, globals.sql, env.backup, agent/, joblogs/),
      mengambil statistik basis data lewat psql di container Postgres, lalu menulis
      DIR/manifest.json (ikut masuk ke dalam arsip tar).

  backup_manifest.py finalize --manifest PATH --archive-name N --archive-bytes B
      [--archive-sha256 H] [--archive-form "terenkripsi (.gpg)"] [--offsite ok|gagal|dilewati]
      [--offsite-remote gdrive:ComputeHub-Backups] [--restic ok|gagal|dilewati] [--restic-snapshot ID]
      [--restic-check ok|gagal|-] [--restic-offsite ok|gagal|dilewati] [--duration DETIK]
      [--status ok|warn|fail] [--write PATH]
      Menambahkan hasil akhir (ukuran, hash, offsite, restic) ke manifest, menulis salinan
      ke --write (biasanya <arsip>.manifest.json di samping arsip), dan mencetak JSON ringkas
      ke stdout untuk kolom `data` ops_events.

Tidak pernah menggagalkan pemanggil: kesalahan apa pun -> keluar 0 dengan manifest seminimal mungkin.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PG_CONTAINER = os.environ.get("COMPUTEHUB_PG_CONTAINER", "ComputeHub-postgres")
VERSION = 1


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _docker_argv() -> list[str] | None:
    docker = shutil.which("docker") or "/usr/bin/docker"
    for argv in ([docker], ["sudo", "-n", docker]):
        try:
            ok = subprocess.run([*argv, "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if ok.returncode == 0 and PG_CONTAINER in ok.stdout.split():
            return argv
    return None


def _psql(docker: list[str], sql: str, timeout: int = 60) -> str | None:
    try:
        proc = subprocess.run(
            [*docker, "exec", "-i", PG_CONTAINER, "sh", "-c", 'psql -tA -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
            input=sql, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _db_facts(docker: list[str] | None) -> dict:
    facts: dict = {"container": PG_CONTAINER, "reachable": docker is not None}
    if docker is None:
        return facts
    rows = _psql(docker, "SELECT current_database() || '|' || pg_database_size(current_database()) || '|' || version();")
    if rows:
        name, size, ver = rows.strip().split("|", 2)
        facts.update({"name": name, "size_bytes": int(size), "server_version": ver.split(",")[0].strip()})
    tables = _psql(docker, "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")
    if tables and tables.strip().isdigit():
        facts["tables"] = int(tables.strip())
    rows_est = _psql(docker, "SELECT coalesce(sum(n_live_tup),0) FROM pg_stat_user_tables;")
    if rows_est and rows_est.strip().isdigit():
        facts["estimated_rows"] = int(rows_est.strip())
    per_table = _psql(docker, "SELECT relname || '|' || n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 12;")
    if per_table:
        facts["largest_tables"] = [
            {"table": r.split("|")[0], "rows": int(r.split("|")[1])}
            for r in per_table.strip().splitlines() if "|" in r
        ]
    try:
        ver = subprocess.run([*docker, "exec", PG_CONTAINER, "pg_dump", "--version"], capture_output=True, text=True, timeout=20, check=False)
        if ver.returncode == 0:
            facts["pg_dump_version"] = ver.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return facts


def _usernames(docker: list[str] | None) -> dict[str, dict]:
    if docker is None:
        return {}
    out = _psql(docker, "SELECT id || '|' || coalesce(username,'') || '|' || coalesce(role,'') FROM users;")
    result: dict[str, dict] = {}
    for line in (out or "").splitlines():
        parts = line.split("|")
        if len(parts) >= 3 and parts[0].isdigit():
            result[parts[0]] = {"username": parts[1], "role": parts[2]}
    return result


def _scan_dir(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path, onerror=lambda _e: None):
        for name in names:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            files += 1
            total += st.st_size
    return files, total


def _file_entry(path: Path, rel: str) -> dict:
    st = path.stat()
    return {"path": rel, "bytes": st.st_size, "mtime": dt.datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds")}


def cmd_stage(args: argparse.Namespace) -> int:
    staging = Path(args.staging)
    docker = _docker_argv()
    manifest: dict = {
        "manifest_version": VERSION,
        "label": args.label,
        "trigger": "web" if args.label.startswith("manual") else "timer",
        "requested_by": args.requested_by or None,
        "request_id": args.request_id or None,
        "started_at": args.started_at or _now(),
        "environment": {
            "hostname": socket.gethostname(),
            "mode": "host",
            "staging_dir": str(staging),
            "tool": "scripts/backup.sh",
        },
        "database": _db_facts(docker),
        "workspaces": {"accounts": [], "accounts_total": 0, "files_total": 0, "bytes_total": 0},
        "components": {},
        "files": [],
    }
    db_sql = staging / "db.sql"
    if db_sql.exists():
        manifest["database"]["dump_bytes"] = db_sql.stat().st_size
        try:
            with db_sql.open("rb") as fh:
                manifest["database"]["dump_lines"] = sum(1 for _ in fh)
        except OSError:
            pass
    globals_sql = staging / "globals.sql"
    manifest["database"]["globals_included"] = globals_sql.exists() and globals_sql.stat().st_size > 0
    err = staging / "db.err"
    if err.exists() and err.stat().st_size > 0:
        manifest["database"]["dump_warnings"] = err.read_text(errors="replace")[-2000:]

    users_dir = staging / "users"
    names = _usernames(docker)
    accounts = []
    if users_dir.is_dir():
        for entry in sorted(users_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            files, total = _scan_dir(entry)
            meta = names.get(entry.name, {})
            accounts.append({
                "user_id": int(entry.name) if entry.name.isdigit() else None,
                "dir": entry.name,
                "username": meta.get("username"),
                "role": meta.get("role"),
                "files": files,
                "bytes": total,
            })
    accounts.sort(key=lambda a: a["bytes"], reverse=True)
    manifest["workspaces"] = {
        "accounts": accounts,
        "accounts_total": len(accounts),
        "files_total": sum(a["files"] for a in accounts),
        "bytes_total": sum(a["bytes"] for a in accounts),
    }

    comp: dict = {}
    env_backup = staging / "env.backup"
    comp["env"] = {"included": env_backup.exists(), "bytes": env_backup.stat().st_size if env_backup.exists() else 0,
                   "note": "konfigurasi backend (.env) — berisi rahasia, hanya di arsip terenkripsi"}
    agent_dir = staging / "agent"
    a_files, a_bytes = _scan_dir(agent_dir) if agent_dir.is_dir() else (0, 0)
    comp["agent"] = {"included": a_files > 0, "files": a_files, "bytes": a_bytes, "note": "agen pemantau host + unit systemd"}
    joblogs = staging / "joblogs"
    j_files, j_bytes = _scan_dir(joblogs) if joblogs.is_dir() else (0, 0)
    comp["joblogs"] = {"included": j_files > 0, "files": j_files, "bytes": j_bytes, "note": "jejak audit eksekusi job & sesi notebook"}
    comp["redis"] = {"included": False, "note": "tidak dipakai ComputeHub (non-kritis)"}
    manifest["components"] = comp

    files = []
    for rel in ("db.sql", "globals.sql", "db.err", "env.backup", "manifest.json"):
        p = staging / rel
        if p.exists() and rel != "manifest.json":
            files.append(_file_entry(p, rel))
    for sub, (fc, fb) in (("users/", (manifest["workspaces"]["files_total"], manifest["workspaces"]["bytes_total"])),
                          ("agent/", (a_files, a_bytes)), ("joblogs/", (j_files, j_bytes))):
        if fc:
            files.append({"path": sub, "bytes": fb, "files": fc})
    manifest["files"] = files
    (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"accounts": len(accounts), "files_total": manifest["workspaces"]["files_total"], "bytes_total": manifest["workspaces"]["bytes_total"], "tables": manifest["database"].get("tables")}))
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {"manifest_version": VERSION, "database": {}, "workspaces": {}, "components": {}, "files": []}
    manifest["finished_at"] = _now()
    manifest["duration_seconds"] = args.duration
    manifest["status"] = args.status
    manifest["archive"] = {
        "name": args.archive_name,
        "bytes": args.archive_bytes,
        "sha256": args.archive_sha256 or None,
        "form": args.archive_form,
        "verified": bool(args.archive_sha256),
    }
    manifest["offsite"] = {"tar": args.offsite, "remote": args.offsite_remote or None,
                           "archive_name": args.archive_name if args.offsite == "ok" else None}
    manifest["restic"] = {"status": args.restic, "snapshot": args.restic_snapshot or None,
                          "check": args.restic_check, "offsite": args.restic_offsite}
    files = [f for f in manifest.get("files", []) if f.get("path") != "manifest.json"]
    files.append({"path": "manifest.json", "bytes": path.stat().st_size if path.exists() else 0})
    manifest["files"] = files
    text = json.dumps(manifest, ensure_ascii=False, indent=1) + "\n"
    if args.write:
        out = Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        try:
            out.chmod(0o600)
        except OSError:
            pass
    print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("stage")
    st.add_argument("--staging", required=True)
    st.add_argument("--label", default="terjadwal")
    st.add_argument("--requested-by", default="")
    st.add_argument("--request-id", default="")
    st.add_argument("--started-at", default="")
    fin = sub.add_parser("finalize")
    fin.add_argument("--manifest", required=True)
    fin.add_argument("--archive-name", default="")
    fin.add_argument("--archive-bytes", type=int, default=0)
    fin.add_argument("--archive-sha256", default="")
    fin.add_argument("--archive-form", default="")
    fin.add_argument("--offsite", default="dilewati")
    fin.add_argument("--offsite-remote", default="")
    fin.add_argument("--restic", default="dilewati")
    fin.add_argument("--restic-snapshot", default="")
    fin.add_argument("--restic-check", default="-")
    fin.add_argument("--restic-offsite", default="dilewati")
    fin.add_argument("--duration", type=int, default=0)
    fin.add_argument("--status", default="ok")
    fin.add_argument("--write", default="")
    args = ap.parse_args()
    return cmd_stage(args) if args.cmd == "stage" else cmd_finalize(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — manifest adalah pelengkap, jangan gagalkan backup
        sys.stderr.write(f"backup_manifest gagal: {exc!r}\n")
        print("{}")
        sys.exit(0)
