"""Identitas container Docker untuk sebuah PID host (laporan proses).

PID -> /proc/<pid>/cgroup -> container ID -> nama + label compose (Docker API via
/var/run/docker.sock, hanya GET). Satu panggilan `GET /containers/json` memetakan
semua container sekaligus dan di-cache, jadi refresh laporan tidak membebani Docker.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import threading
import time

from app.core.logging import get_logger

logger = get_logger(__name__)

DOCKER_SOCK = "/var/run/docker.sock"
CACHE_TTL = 45.0
# Container baru (belum ada di cache) memicu muat ulang paling cepat tiap N detik.
_MISS_REFRESH = 10.0
UNAVAILABLE_LABEL = "Docker (nama tidak tersedia)"

_CID_RE = re.compile(r"(?:docker-([0-9a-f]{64})\.scope|/docker/([0-9a-f]{64}))")

_lock = threading.Lock()
_cache: dict[str, dict] = {}
_loaded_at = 0.0
_ok = False


def _read_cgroup(pid: int) -> str:
    try:
        with open(f"/proc/{int(pid)}/cgroup", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def container_id_for_pid(pid: int) -> str | None:
    m = _CID_RE.search(_read_cgroup(pid))
    if not m:
        return None
    return m.group(1) or m.group(2)


# Unit yang tak menjelaskan proses (pemicu/induk generik) -> tak ditampilkan.
_SKIP_UNITS = {"cron", "crond", "anacron", "atd", "init", "ssh", "sshd"}


def _unit_from_cgroup(data: str) -> dict | None:
    """Unit systemd terdalam dari isi cgroup: {'name', 'user'} atau None."""
    for line in data.splitlines():
        path = line.split(":", 2)[-1]
        parts = [p for p in path.split("/") if p]
        for i in range(len(parts) - 1, -1, -1):
            comp = parts[i]
            if comp.endswith(".scope") or comp.endswith(".slice"):
                if i == len(parts) - 1:
                    break  # sesi login/scope transien: bukan service bernama
                continue
            if not comp.endswith(".service"):
                continue
            name = comp[: -len(".service")].replace("\\x2d", "-").removesuffix("@-")
            if name.startswith("user@") or name in _SKIP_UNITS:
                return None
            is_user = any(p.startswith("user@") and p.endswith(".service") for p in parts[:i])
            return {"name": name, "user": is_user}
        return None
    return None


def systemd_unit_for_pid(pid: int) -> dict | None:
    """Service systemd (sistem atau --user) tempat proses berjalan, bila bermakna."""
    data = _read_cgroup(pid)
    if not data or _CID_RE.search(data):
        return None
    return _unit_from_cgroup(data)


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 3.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


def _fetch_containers() -> list[dict]:
    conn = _UnixHTTPConnection(DOCKER_SOCK)
    try:
        conn.request("GET", "/containers/json")
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"Docker API {resp.status}")
        return json.loads(body)
    finally:
        conn.close()


def _refresh(now: float) -> None:
    global _cache, _loaded_at, _ok
    _loaded_at = now
    try:
        items = _fetch_containers()
    except Exception as exc:  # noqa: BLE001
        if _ok:
            logger.warning("Docker API tak terjangkau untuk identitas container: %s", exc)
        _ok = False
        return
    fresh: dict[str, dict] = {}
    for c in items:
        cid = c.get("Id") or ""
        names = c.get("Names") or []
        labels = c.get("Labels") or {}
        fresh[cid] = {
            "id": cid[:12],
            "name": (names[0] if names else "").lstrip("/"),
            "project": labels.get("com.docker.compose.project", ""),
            "service": labels.get("com.docker.compose.service", ""),
        }
    _cache = fresh
    _ok = True


def lookup(cid: str) -> dict | None:
    """Metadata container (cache); None bila Docker tak terjangkau / ID tak dikenal."""
    now = time.monotonic()
    with _lock:
        age = now - _loaded_at
        if age >= CACHE_TTL or (cid not in _cache and age >= _MISS_REFRESH):
            _refresh(now)
        return _cache.get(cid)


def workload_label(meta: dict | None) -> str:
    if not meta or not meta.get("name"):
        return UNAVAILABLE_LABEL
    if meta.get("project") and meta.get("service"):
        return f"Docker / {meta['project']} / {meta['service']}"
    return f"Docker / {meta['name']}"


def for_pid(pid: int) -> dict | None:
    """Identitas container untuk PID, atau None bila proses bukan di container."""
    cid = container_id_for_pid(pid)
    if not cid:
        return None
    meta = lookup(cid)
    return {
        "id": cid[:12],
        "name": (meta or {}).get("name", ""),
        "project": (meta or {}).get("project", ""),
        "service": (meta or {}).get("service", ""),
        "label": workload_label(meta),
    }
