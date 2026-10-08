"""Antrean permintaan operasional (backup / restore / uji pulih) menuju agen di HOST.

Backend berjalan di dalam container tanpa systemctl/gpg/rclone/restic, jadi ia tidak
mengeksekusi backup/restore sendiri. Ia hanya MENULIS berkas permintaan JSON ke
~/.computehub/ops-requests/pending/ (folder yang di-bind-mount read-write). Agen host
scripts/ops_agent.py (unit systemd --user computehub-ops-agent.service) mengerjakannya
satu per satu, menulis status ke running/ -> done/ dan log ke logs/<id>.log, serta
merangkum sumber pemulihan ke ~/.computehub/backup-sources.json. Modul ini membaca
kembali semuanya untuk ditampilkan di Pengaturan > Cadangan & Pemulihan.

Semua I/O adalah berkas kecil; fungsi sinkron, panggil lewat asyncio.to_thread dari router.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
from pathlib import Path

from app.core.config import settings

ACTIONS = ("backup", "restore", "drill", "refresh_sources", "delete_archive")
RESTORE_SOURCES = ("archive", "snapshot", "pre_restore", "offsite")
SCOPES = ("db", "users", "env")
CONFIRM_PHRASE = "YA PULIHKAN"
DELETE_PHRASE = "HAPUS"
AGENT_STALE_SECONDS = 30

_ARCHIVE_RE = re.compile(r"^computehub(-core)?-\d{8}-\d{6}\.tar\.gz(\.gpg)?$")
_SNAPSHOT_RE = re.compile(r"^[0-9a-f]{8,64}$")
_PRE_RESTORE_RE = re.compile(r"^pre-restore-\d{8}-\d{6}$")
_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def ch_home() -> Path:
    return settings.docker_user_data_root.parent


def requests_root() -> Path:
    return ch_home() / "ops-requests"


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _new_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def validate_restore_params(params: dict) -> dict:
    """Normalisasi + validasi parameter restore; ValueError bila tidak sah."""
    source_type = str(params.get("source_type") or "")
    source = str(params.get("source") or "").strip()
    if source_type not in RESTORE_SOURCES:
        raise ValueError("Jenis sumber pemulihan tidak dikenal.")
    pattern = {"archive": _ARCHIVE_RE, "offsite": _ARCHIVE_RE, "snapshot": _SNAPSHOT_RE, "pre_restore": _PRE_RESTORE_RE}[source_type]
    if not pattern.match(source) or (source_type == "offsite" and not source.endswith(".gpg")):
        raise ValueError("Nama sumber pemulihan tidak valid.")
    scope = [s for s in SCOPES if s in (params.get("scope") or [])]
    if not scope:
        raise ValueError("Pilih minimal satu cakupan (database / workspace / konfigurasi).")
    if str(params.get("confirm") or "") != CONFIRM_PHRASE:
        raise ValueError(f"Ketik persis “{CONFIRM_PHRASE}” untuk melanjutkan.")
    return {"source_type": source_type, "source": source, "scope": scope,
            "stop_sessions": bool(params.get("stop_sessions")), "confirm": CONFIRM_PHRASE}


def validate_drill_params(params: dict) -> dict:
    archive = str(params.get("archive") or "").strip()
    if archive and not (_ARCHIVE_RE.match(archive) and archive.endswith(".gpg")):
        raise ValueError("Nama arsip tidak valid.")
    return {"archive": archive or None}


def validate_delete_params(params: dict) -> dict:
    """Hapus arsip terenkripsi di server: nama harus persis pola arsip + frasa HAPUS."""
    archive = str(params.get("archive") or "").strip()
    if not (_ARCHIVE_RE.match(archive) and archive.endswith(".gpg")):
        raise ValueError("Nama arsip tidak valid.")
    if str(params.get("confirm") or "").strip().upper() != DELETE_PHRASE:
        raise ValueError(f"Ketik persis “{DELETE_PHRASE}” untuk menghapus arsip.")
    return {"archive": archive, "confirm": DELETE_PHRASE}


def has_active_request(action: str | None = None) -> dict | None:
    """Permintaan yang masih pending/running (opsional: untuk tindakan tertentu)."""
    root = requests_root()
    for state in ("running", "pending"):
        for path in sorted((root / state).glob("*.json")):
            req = _read_json(path)
            if req and (action is None or req.get("action") == action):
                req.setdefault("status", state)
                return req
    return None


def submit(action: str, params: dict, actor_id: int, actor_username: str, actor_email: str) -> dict:
    """Tulis permintaan ke antrean (atomik: tmp -> rename). Mengembalikan state awal."""
    if action not in ACTIONS:
        raise ValueError("Tindakan tidak dikenal.")
    if action == "restore":
        params = validate_restore_params(params)
    elif action == "drill":
        params = validate_drill_params(params)
    elif action == "delete_archive":
        params = validate_delete_params(params)
    else:
        params = {}
    root = requests_root()
    pending = root / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    rid = _new_id()
    req = {
        "id": rid,
        "action": action,
        "params": params,
        "requested_by": {"id": actor_id, "username": actor_username, "email": actor_email},
        "created_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": "pending",
    }
    tmp = pending / f"{rid}.json.tmp"
    tmp.write_text(json.dumps(req, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, pending / f"{rid}.json")
    return public_view(req)


def public_view(req: dict) -> dict:
    """Bentuk aman untuk UI: frasa konfirmasi & path internal tidak ikut."""
    params = dict(req.get("params") or {})
    params.pop("confirm", None)
    who = req.get("requested_by") or {}
    return {
        "id": req.get("id"),
        "action": req.get("action"),
        "params": params,
        "requested_by": {"id": who.get("id"), "username": who.get("username")},
        "created_at": req.get("created_at"),
        "started_at": req.get("started_at"),
        "finished_at": req.get("finished_at"),
        "updated_at": req.get("updated_at"),
        "status": req.get("status", "pending"),
        "exit_code": req.get("exit_code"),
        "message": req.get("message"),
        "last_line": req.get("last_line"),
        "result": req.get("result") or {},
    }


def list_requests(limit: int = 30) -> list[dict]:
    root = requests_root()
    rows: list[dict] = []
    for state in ("running", "pending", "done"):
        for path in (root / state).glob("*.json"):
            req = _read_json(path)
            if req and _ID_RE.match(str(req.get("id", ""))):
                req.setdefault("status", state)
                rows.append(public_view(req))
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[: max(1, min(limit, 200))]


def get_request(rid: str, log_tail_lines: int = 200) -> dict | None:
    if not _ID_RE.match(rid):
        return None
    root = requests_root()
    req = None
    for state in ("running", "pending", "done"):
        found = _read_json(root / state / f"{rid}.json")
        if found:
            found.setdefault("status", state)
            req = found
            break
    if req is None:
        return None
    view = public_view(req)
    log_path = root / "logs" / f"{rid}.log"
    tail = ""
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 64_000))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        pass
    lines = tail.splitlines()[-log_tail_lines:]
    view["log"] = "\n".join(lines)
    return view


def agent_status() -> dict:
    data = _read_json(ch_home() / "ops-agent.json") or {}
    last_seen = data.get("last_seen")
    alive = False
    age = None
    if last_seen:
        try:
            seen = dt.datetime.fromisoformat(str(last_seen))
            age = (dt.datetime.now(dt.timezone.utc) - seen.astimezone(dt.timezone.utc)).total_seconds()
            alive = age < AGENT_STALE_SECONDS and not data.get("stopping")
        except ValueError:
            pass
    pending = len(list((requests_root() / "pending").glob("*.json"))) if (requests_root() / "pending").is_dir() else 0
    return {
        "alive": alive,
        "last_seen": last_seen,
        "age_seconds": None if age is None else round(age),
        "version": data.get("version"),
        "busy_request": data.get("busy_request"),
        "pending": pending,
        "hostname": data.get("hostname"),
    }


def sources() -> dict:
    """Ringkasan sumber pemulihan yang ditulis agen (+ umur datanya)."""
    path = ch_home() / "backup-sources.json"
    data = _read_json(path)
    if not data:
        return {"available": False, "generated_at": None, "archives": [], "plain_archives": [],
                "pre_restore": [], "restic": {"available": False, "snapshots": []},
                "offsite": {"available": False, "archives": []}, "disk": {}}
    data["available"] = True
    return data
