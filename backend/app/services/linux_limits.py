from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pwd
import shlex
import sys
import time
import uuid
from pathlib import Path


_CACHE_SECONDS = 10.0
_cache: dict | None = None
_cache_until = 0.0
_lock = asyncio.Lock()


def _parse_limit(text: str, resource: str) -> float | int | None:
    fields = text.split()
    if resource == "cpu.max":
        if len(fields) != 2 or int(fields[1]) <= 0:
            raise ValueError("Invalid CPU quota")
        if fields[0] == "max":
            return None
        quota = int(fields[0])
        if quota < 0:
            raise ValueError("Invalid CPU quota")
        return quota / int(fields[1])
    if len(fields) != 1:
        raise ValueError("Invalid resource limit")
    if fields[0] == "max":
        return None
    value = int(fields[0])
    if value < 0:
        raise ValueError("Invalid resource limit")
    return value


def _read_value(group: Path, resource: str) -> float | int | None:
    try:
        return _parse_limit((group / resource).read_text(encoding="ascii"), resource)
    except FileNotFoundError:
        controllers = (group / "cgroup.controllers").read_text(encoding="ascii").split()
        if resource.split(".")[0] not in controllers:
            return None
        raise


def _allowed_cpus(root: Path, group: Path) -> str | None:
    current = group
    while True:
        try:
            return (current / "cpuset.cpus.effective").read_text(encoding="ascii").strip() or None
        except FileNotFoundError:
            if current == root:
                return None
            current = current.parent
        except OSError:
            return None


def _limit(root: Path, group: Path, resource: str) -> dict:
    result = {
        "state": "unavailable", "value": None, "local_value": None,
        "source": None, "inherited": False,
    }
    values: list[tuple[float | int, Path]] = []
    current = group
    try:
        while current != root:
            value = _read_value(current, resource)
            if current == group:
                result["local_value"] = value
            if value is not None:
                values.append((value, current))
            current = current.parent
    except (OSError, ValueError):
        return result
    if not values:
        result["state"] = "unlimited"
        return result
    value, source = min(values, key=lambda item: item[0])
    result.update(
        state="limited", value=value,
        source="/" + source.relative_to(root).as_posix(), inherited=source != group,
    )
    return result


def collect_limits(root: Path, user_ids: list[int]) -> dict:
    if not (root / "cgroup.controllers").is_file():
        return {"available": False, "reason": "cgroup_v2_unavailable", "users": []}
    users = []
    for uid in user_ids:
        if not isinstance(uid, int) or isinstance(uid, bool) or uid < 1000:
            raise ValueError("Invalid Linux UID")
        group = root / "user.slice" / f"user-{uid}.slice"
        active = group.is_dir()
        users.append({
            "uid": uid,
            "active": active,
            "cgroup": "/user.slice/" + group.name,
            "allowed_cpus": _allowed_cpus(root, group) if active else None,
            "limits": {
                key: _limit(root, group, filename)
                for key, filename in (
                    ("cpu_cores", "cpu.max"),
                    ("memory_high_bytes", "memory.high"),
                    ("memory_max_bytes", "memory.max"),
                    ("tasks", "pids.max"),
                )
            } if active else None,
        })
    return {"available": True, "reason": None, "users": users}


def _reader_argv(user_ids: list[int], name: str) -> list[str]:
    from app.core.config import settings

    return [
        *shlex.split(settings.DOCKER_CMD), "run", "--rm", "--pull=never",
        "--name", name, "--label", "computehub.reader=linux-limits",
        "--network", "none", "--read-only", "--cgroupns=host",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "32", "--memory", "64m", "--cpus", "0.25",
        "--mount", "type=bind,source=/sys/fs/cgroup,target=/host-cgroup,readonly",
        "--mount", f"type=bind,source={Path(__file__).resolve()},target=/reader.py,readonly",
        "--entrypoint", "python", settings.DISK_SCAN_IMAGE,
        "-B", "/reader.py", "/host-cgroup", json.dumps(user_ids),
    ]


async def _collect_host(user_ids: list[int]) -> dict:
    from app.core.config import settings

    if not Path("/.dockerenv").exists():
        return await asyncio.to_thread(collect_limits, Path("/sys/fs/cgroup"), user_ids)
    name = f"ch-linux-limits-{uuid.uuid4().hex[:12]}"
    proc = await asyncio.create_subprocess_exec(
        *_reader_argv(user_ids, name),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        cleanup = await asyncio.create_subprocess_exec(
            *shlex.split(settings.DOCKER_CMD), "rm", "-f", name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(cleanup.wait(), timeout=5)
        except asyncio.TimeoutError:
            cleanup.kill()
            await cleanup.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError(f"Linux limits reader exited {proc.returncode}")
    result = json.loads(output)
    if not isinstance(result, dict) or not isinstance(result.get("users"), list):
        raise ValueError("Invalid Linux limits snapshot")
    return result


async def snapshot() -> dict:
    from app.core.logging import get_logger
    from app.services.report import is_human_user

    global _cache, _cache_until
    async with _lock:
        if _cache is not None and time.monotonic() < _cache_until:
            return _cache
        accounts = {
            account.pw_uid: account.pw_name
            for account in pwd.getpwall()
            if account.pw_uid >= 1000 and is_human_user(account.pw_name)
        }
        try:
            result = await _collect_host(sorted(accounts))
            users = [
                {**row, "username": accounts[row["uid"]]}
                for row in result["users"] if row["uid"] in accounts
            ]
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, asyncio.TimeoutError) as exc:
            get_logger(__name__).warning("Batas cgroup Linux tidak terbaca: %s", exc)
            result = {"available": False, "reason": "reader_unavailable"}
            users = []
        payload = {
            "available": result["available"],
            "reason": result.get("reason"),
            "read_only": True,
            "source": "cgroup_v2",
            "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "users": sorted(users, key=lambda row: (not row["active"], row["username"])),
        }
        _cache = payload
        _cache_until = time.monotonic() + _CACHE_SECONDS
        return payload


if __name__ == "__main__":
    print(json.dumps(collect_limits(Path(sys.argv[1]), json.loads(sys.argv[2]))))