#!/usr/bin/env python3
"""Agen operasional ComputeHub di HOST — menjalankan backup/restore atas permintaan web.

Backend berjalan di dalam container (user 1015, tanpa systemctl/gpg/rclone/restic), jadi ia
tidak bisa menjalankan backup.sh sendiri. Backend menulis permintaan sebagai berkas JSON ke
~/.computehub/ops-requests/pending/, agen ini (unit systemd --user computehub-ops-agent.service)
mengerjakannya SATU PER SATU di host dengan alat yang sudah ada, lalu menulis status + log yang
dibaca kembali oleh backend untuk ditampilkan di Pengaturan > Cadangan & Pemulihan.

Tindakan yang dikenal (semua parameter divalidasi ketat; tak ada string yang dieksekusi):
  backup          -> scripts/backup.sh (COMPUTEHUB_BACKUP_FORCE_TAR=1, label manual-web)
  restore         -> scripts/restore.sh --yes --<archive|snapshot|pre-restore|offsite> ... --scope ...
  drill           -> scripts/restore_drill.sh [--archive NAMA]
  refresh_sources -> tulis ~/.computehub/backup-sources.json (arsip + manifest, snapshot restic,
                     salinan Drive, titik rollback pre-restore-*)

Tata letak:
  ops-requests/pending/<id>.json   ditulis backend
  ops-requests/running/<id>.json   sedang dikerjakan (status diperbarui berkala)
  ops-requests/done/<id>.json      selesai: status ok|fail (100 terakhir disimpan)
  ops-requests/logs/<id>.log       keluaran skrip, mengalir baris demi baris
  ops-agent.json                   detak jantung agen (pid, last_seen, busy)
Stdlib saja; dijalankan python3 sistem.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.0"
HOME = Path(os.environ.get("HOME") or Path("~").expanduser())
ROOT = Path(os.environ.get("COMPUTEHUB_ROOT") or HOME / "DATA_ICAL" / "SERVER-KAMPUS")
CH = Path(os.environ.get("COMPUTEHUB_HOME") or HOME / ".computehub")
REQ = CH / "ops-requests"
PENDING, RUNNING, DONE, LOGS = REQ / "pending", REQ / "running", REQ / "done", REQ / "logs"
HEARTBEAT = CH / "ops-agent.json"
SOURCES = CH / "backup-sources.json"
ENC_DIR = Path(os.environ.get("COMPUTEHUB_BACKUP_ENC_DIR") or CH / "backups_enc")
PLAIN_DIR = Path(os.environ.get("COMPUTEHUB_BACKUP_DIR") or CH / "backups")
PASSFILE = CH / "backup.pass"
RESTIC_BIN = Path(os.environ.get("RESTIC_BIN") or HOME / "bin" / "restic")
RESTIC_REPO = os.environ.get("COMPUTEHUB_RESTIC_REPO") or str(CH / "restic-repo")
RCLONE_BIN = Path(os.environ.get("RCLONE_BIN") or HOME / "bin" / "rclone")
RCLONE_REMOTE = os.environ.get("COMPUTEHUB_RCLONE_REMOTE") or "gdrive:ComputeHub-Backups"
POLL_SECONDS = float(os.environ.get("COMPUTEHUB_OPS_POLL", "2"))
SOURCES_TTL = int(os.environ.get("COMPUTEHUB_SOURCES_TTL", str(6 * 3600)))
KEEP_DONE = 100
TIMEOUTS = {"backup": 6 * 3600, "restore": 3 * 3600, "drill": 2 * 3600, "refresh_sources": 20 * 60}

ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
ARCHIVE_RE = re.compile(r"^computehub-\d{8}-\d{6}\.tar\.gz(\.gpg)?$")
SNAPSHOT_RE = re.compile(r"^[0-9a-f]{8,64}$")
PRE_RESTORE_RE = re.compile(r"^pre-restore-\d{8}-\d{6}$")
SCOPES = {"db", "users", "env"}
CONFIRM = "YA PULIHKAN"

_stop = False


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _log(msg: str) -> None:
    print(f"{_now()} {msg}", flush=True)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def heartbeat(busy: str | None, extra: dict | None = None) -> None:
    data = {"pid": os.getpid(), "version": VERSION, "hostname": socket.gethostname(),
            "started_at": STARTED_AT, "last_seen": _now(), "busy_request": busy,
            "poll_seconds": POLL_SECONDS, **(extra or {})}
    try:
        _write_json(HEARTBEAT, data)
    except OSError as exc:
        _log(f"heartbeat gagal: {exc!r}")


# --------------------------------------------------------------------------- sumber pemulihan

def _archive_entry(path: Path, tier: str) -> dict:
    st = path.stat()
    entry = {"name": path.name, "tier": tier, "bytes": st.st_size, "encrypted": path.name.endswith(".gpg"),
             "mtime": dt.datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
             "sha256": None, "manifest": None}
    sha = Path(str(path) + ".sha256")
    if sha.exists():
        try:
            entry["sha256"] = sha.read_text().split()[0]
        except (OSError, IndexError):
            pass
    manifest = _read_json(Path(str(path) + ".manifest.json"))
    if manifest:
        entry["manifest"] = manifest
    return entry


def _restic_snapshots() -> dict:
    info: dict = {"available": False, "repo": RESTIC_REPO, "snapshots": [], "error": None}
    if not (RESTIC_BIN.exists() and PASSFILE.exists()):
        info["error"] = "restic atau passphrase tidak tersedia"
        return info
    env = {**os.environ, "RESTIC_PASSWORD_FILE": str(PASSFILE), "RESTIC_REPOSITORY": RESTIC_REPO}
    try:
        out = subprocess.run([str(RESTIC_BIN), "snapshots", "--json", "--tag", "computehub"],
                             capture_output=True, text=True, timeout=180, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        info["error"] = repr(exc)
        return info
    if out.returncode != 0:
        info["error"] = out.stderr.strip()[-300:]
        return info
    try:
        snaps = json.loads(out.stdout or "[]")
    except ValueError:
        snaps = []
    info["available"] = True
    info["snapshots"] = [
        {"id": s.get("id"), "short_id": s.get("short_id") or str(s.get("id", ""))[:8], "time": s.get("time"),
         "hostname": s.get("hostname"), "tags": s.get("tags") or [],
         "paths": len(s.get("paths") or []),
         "summary": {k: (s.get("summary") or {}).get(k) for k in ("total_files_processed", "total_bytes_processed", "data_added")}}
        for s in sorted(snaps, key=lambda s: s.get("time", ""), reverse=True)
    ]
    return info


def _offsite_archives() -> dict:
    info: dict = {"available": False, "remote": RCLONE_REMOTE, "archives": [], "error": None}
    if not RCLONE_BIN.exists():
        info["error"] = "rclone tidak tersedia"
        return info
    try:
        out = subprocess.run([str(RCLONE_BIN), "lsjson", RCLONE_REMOTE, "--files-only", "--timeout", "2m"],
                             capture_output=True, text=True, timeout=240, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        info["error"] = repr(exc)
        return info
    if out.returncode != 0:
        info["error"] = out.stderr.strip()[-300:]
        return info
    try:
        rows = json.loads(out.stdout or "[]")
    except ValueError:
        rows = []
    info["available"] = True
    info["archives"] = sorted(
        [{"name": r.get("Name"), "bytes": r.get("Size"), "mtime": r.get("ModTime")}
         for r in rows if ARCHIVE_RE.match(str(r.get("Name", "")))],
        key=lambda r: r["name"], reverse=True,
    )
    return info


def _pre_restore_points() -> list[dict]:
    points = []
    for d in sorted(CH.glob("pre-restore-*"), reverse=True):
        if not (d.is_dir() and PRE_RESTORE_RE.match(d.name)):
            continue
        total = 0
        files = []
        for f in sorted(d.iterdir()):
            if f.is_file():
                st = f.stat()
                total += st.st_size
                files.append({"path": f.name, "bytes": st.st_size})
        meta = _read_json(d / "meta.json") or {}
        m = re.match(r"pre-restore-(\d{8})-(\d{6})", d.name)
        created = meta.get("created_at") or (dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").astimezone().isoformat(timespec="seconds") if m else None)
        points.append({"name": d.name, "created_at": created, "bytes": total, "files": files,
                       "source": meta.get("source"), "scope": meta.get("scope"), "request_id": meta.get("request_id")})
    return points


def build_sources() -> dict:
    archives = []
    for tier, base in (("utama", ENC_DIR), ("weekly", ENC_DIR / "weekly"), ("monthly", ENC_DIR / "monthly")):
        if base.is_dir():
            for p in sorted(base.glob("computehub-*.tar.gz.gpg"), reverse=True):
                archives.append(_archive_entry(p, tier))
    plain = [_archive_entry(p, "polos") for p in sorted(PLAIN_DIR.glob("computehub-*.tar.gz"), reverse=True)] if PLAIN_DIR.is_dir() else []
    try:
        usage = shutil.disk_usage(CH)
        disk = {"free_bytes": usage.free, "total_bytes": usage.total}
    except OSError:
        disk = {}
    return {"generated_at": _now(), "agent_version": VERSION, "archives": archives, "plain_archives": plain,
            "pre_restore": _pre_restore_points(), "restic": _restic_snapshots(), "offsite": _offsite_archives(), "disk": disk}


def refresh_sources(log) -> dict:
    data = build_sources()
    _write_json(SOURCES, data)
    msg = (f"sumber diperbarui: {len(data['archives'])} arsip, {len(data['restic']['snapshots'])} snapshot restic, "
           f"{len(data['offsite']['archives'])} arsip Drive, {len(data['pre_restore'])} titik rollback")
    log(msg)
    return {"archives": len(data["archives"]), "restic_snapshots": len(data["restic"]["snapshots"]),
            "offsite_archives": len(data["offsite"]["archives"]), "pre_restore": len(data["pre_restore"])}


# --------------------------------------------------------------------------- eksekusi permintaan

class Invalid(Exception):
    pass


def _username(req: dict) -> str:
    who = req.get("requested_by") or {}
    name = str(who.get("username") or who.get("email") or "").strip()
    return re.sub(r"[^A-Za-z0-9._@-]", "", name)[:64]


def _command(req: dict) -> tuple[list[str], dict]:
    """Bangun argv + env dari permintaan; melempar Invalid bila parameter tak sah."""
    action = req.get("action")
    params = req.get("params") or {}
    env = {**os.environ, "COMPUTEHUB_REQUEST_ID": req["id"]}
    if action == "backup":
        env.update({"COMPUTEHUB_BACKUP_FORCE_TAR": "1", "COMPUTEHUB_BACKUP_LABEL": "manual-web",
                    "COMPUTEHUB_BACKUP_REQUESTED_BY": _username(req)})
        return ["nice", "-n", "10", "ionice", "-c2", "-n7", "bash", str(ROOT / "scripts" / "backup.sh")], env
    if action == "drill":
        argv = ["bash", str(ROOT / "scripts" / "restore_drill.sh"), "--request-id", req["id"]]
        archive = params.get("archive")
        if archive:
            if not ARCHIVE_RE.match(str(archive)):
                raise Invalid("nama arsip tidak valid")
            argv += ["--archive", str(archive)]
        return argv, env
    if action == "restore":
        if params.get("confirm") != CONFIRM:
            raise Invalid("frasa konfirmasi tidak cocok")
        source_type = params.get("source_type")
        source = str(params.get("source") or "")
        scope = params.get("scope") or ["db", "users"]
        if not isinstance(scope, list) or not scope or not set(scope) <= SCOPES:
            raise Invalid("cakupan tidak valid")
        argv = ["bash", str(ROOT / "scripts" / "restore.sh"), "--yes", "--scope", ",".join(s for s in ("db", "users", "env") if s in scope),
                "--request-id", req["id"]]
        if source_type == "archive":
            if not ARCHIVE_RE.match(source):
                raise Invalid("nama arsip tidak valid")
            argv += ["--archive", source]
        elif source_type == "snapshot":
            if not SNAPSHOT_RE.match(source):
                raise Invalid("id snapshot tidak valid")
            argv += ["--snapshot", source]
        elif source_type == "pre_restore":
            if not PRE_RESTORE_RE.match(source):
                raise Invalid("titik rollback tidak valid")
            argv += ["--pre-restore", source]
        elif source_type == "offsite":
            if not ARCHIVE_RE.match(source) or not source.endswith(".gpg"):
                raise Invalid("nama arsip Drive tidak valid")
            argv += ["--offsite", source]
        else:
            raise Invalid("jenis sumber tidak dikenal")
        if params.get("stop_sessions"):
            argv.append("--stop-sessions")
        env["COMPUTEHUB_RESTORE_CONFIRM"] = CONFIRM
        return argv, env
    raise Invalid(f"tindakan tidak dikenal: {action}")


def run_request(req: dict) -> None:
    rid = req["id"]
    state_path = RUNNING / f"{rid}.json"
    log_path = LOGS / f"{rid}.log"
    req.update({"status": "running", "started_at": _now(), "agent_pid": os.getpid(), "log_path": str(log_path)})
    _write_json(state_path, req)
    heartbeat(rid)

    with log_path.open("a", encoding="utf-8") as fh:
        try:
            log_path.chmod(0o600)
        except OSError:
            pass

        def log(line: str) -> None:
            fh.write(f"[{_now()}] {line}\n")
            fh.flush()

        log(f"permintaan {rid}: {req.get('action')} oleh {_username(req) or '?'}")
        exit_code: int | None = None
        result: dict = {}
        try:
            if req.get("action") == "refresh_sources":
                result = refresh_sources(log)
                exit_code = 0
            else:
                argv, env = _command(req)
                redacted = [a for a in argv if a not in (CONFIRM,)]
                log("menjalankan: " + " ".join(redacted))
                proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        env=env, cwd=str(ROOT), start_new_session=True)
                deadline = time.monotonic() + TIMEOUTS.get(str(req.get("action")), 3600)
                last_flush = 0.0
                assert proc.stdout is not None
                for line in proc.stdout:
                    fh.write(line)
                    fh.flush()
                    now = time.monotonic()
                    if now - last_flush > 5:
                        req["last_line"] = line.strip()[:300]
                        req["updated_at"] = _now()
                        _write_json(state_path, req)
                        heartbeat(rid)
                        last_flush = now
                    if now > deadline:
                        log("!!! batas waktu terlampaui — proses dihentikan")
                        os.killpg(proc.pid, signal.SIGTERM)
                        break
                exit_code = proc.wait(timeout=60)
                if req.get("action") in ("backup", "restore", "drill"):
                    try:
                        result = refresh_sources(log)
                    except Exception as exc:  # noqa: BLE001
                        log(f"(pembaruan sumber gagal: {exc!r})")
        except Invalid as exc:
            log(f"DITOLAK: {exc}")
            exit_code = 2
            req["message"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            log(f"GAGAL: {exc!r}")
            exit_code = 1
            req["message"] = repr(exc)
        req.update({"status": "ok" if exit_code == 0 else "fail", "exit_code": exit_code,
                    "finished_at": _now(), "result": result})
        log(f"selesai: status={req['status']} exit={exit_code}")
    _write_json(DONE / f"{rid}.json", req)
    state_path.unlink(missing_ok=True)
    heartbeat(None)
    _prune_done()


def _prune_done() -> None:
    files = sorted(DONE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_DONE:]:
        rid = old.stem
        old.unlink(missing_ok=True)
        (LOGS / f"{rid}.log").unlink(missing_ok=True)


def _recover_running() -> None:
    """Permintaan yang tertinggal di running/ saat agen mati -> ditandai gagal (tidak diulang
    otomatis: restore/backup bukan operasi yang aman untuk dijalankan ulang diam-diam)."""
    for path in RUNNING.glob("*.json"):
        req = _read_json(path) or {"id": path.stem}
        req.update({"status": "fail", "finished_at": _now(), "exit_code": -1,
                    "message": "agen berhenti saat permintaan berjalan; periksa log lalu ulangi bila perlu"})
        _write_json(DONE / f"{path.stem}.json", req)
        path.unlink(missing_ok=True)


def _next_pending() -> dict | None:
    files = sorted(PENDING.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for path in files:
        req = _read_json(path)
        if req is None or not ID_RE.match(str(req.get("id", ""))) or req["id"] != path.stem:
            _log(f"permintaan tidak sah dibuang: {path.name}")
            path.unlink(missing_ok=True)
            continue
        os.replace(path, RUNNING / path.name)
        return req
    return None


def _handle_signal(signum, _frame) -> None:  # noqa: ANN001
    global _stop
    _stop = True
    _log(f"sinyal {signum} diterima — berhenti setelah permintaan saat ini selesai")


def main() -> int:
    for d in (PENDING, RUNNING, DONE, LOGS):
        d.mkdir(parents=True, exist_ok=True)
        try:
            d.chmod(0o700)
        except OSError:
            pass
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    _recover_running()
    _log(f"ops_agent {VERSION} siap; antrean {REQ}")
    last_sources = 0.0
    while not _stop:
        try:
            if time.monotonic() - last_sources > SOURCES_TTL or not SOURCES.exists():
                try:
                    refresh_sources(_log)
                except Exception as exc:  # noqa: BLE001
                    _log(f"refresh sumber gagal: {exc!r}")
                last_sources = time.monotonic()
            req = _next_pending()
            if req is not None:
                run_request(req)
                last_sources = time.monotonic()
                continue
            heartbeat(None, {"pending": len(list(PENDING.glob('*.json')))})
        except Exception as exc:  # noqa: BLE001
            _log(f"loop galat: {exc!r}")
        time.sleep(POLL_SECONDS)
    heartbeat(None, {"stopping": True})
    return 0


STARTED_AT = _now()

if __name__ == "__main__":
    sys.exit(main())
