from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pwd
import re
import shlex
import sys
import time
import uuid
from pathlib import Path


_CACHE_SECONDS = 10.0
_cache: dict | None = None
_cache_until = 0.0
_lock = asyncio.Lock()

# Drop-in runtime (di RAM, hilang saat reboot) vs permanen. Yang permanen dianggap milik IT.
_RUNTIME_DROPIN_DIR = "/run/systemd/system.control/"
_DEFAULT_DROPIN_DIR = "/usr/lib/systemd/system/"  # bawaan distro, bukan aturan siapa pun
_MANAGED_MARKER = "computehub-managed"
# Kunci yang boleh disentuh UI. VRAM sengaja tidak ada: bukan wewenang cgroup.
_PROPERTIES = {"cpu_cores": "CPUQuota", "memory_high_bytes": "MemoryHigh", "memory_max_bytes": "MemoryMax"}


class LinuxLimitError(RuntimeError):
    pass


def classify_dropins(show_output: str) -> dict:
    """Klasifikasi drop-in dari keluaran `systemctl show -p Description -p DropInPaths`.

    - managed       : drop-in RUNTIME pada slice yang Description-nya berpenanda ComputeHub
    - runtime_other : drop-in runtime tanpa penanda (dipasang orang lain lewat set-property)
    - permanent     : drop-in di /etc (aturan admin IT) — TIDAK boleh ditimpa/dihapus
    Drop-in bawaan distro (/usr/lib) diabaikan. Dibaca lewat systemd host, BUKAN filesystem
    container backend (yang tidak melihat /etc & /run host).
    """
    props: dict[str, str] = {}
    for line in show_output.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    ours = _MANAGED_MARKER in props.get("Description", "")
    managed: list[str] = []
    runtime_other: list[str] = []
    permanent: list[str] = []
    for path in props.get("DropInPaths", "").split():
        if path.startswith(_DEFAULT_DROPIN_DIR):
            continue
        if path.startswith(_RUNTIME_DROPIN_DIR):
            (managed if ours else runtime_other).append(path)
        else:
            permanent.append(path)
    return {"managed": managed, "runtime_other": runtime_other, "permanent": permanent}


async def dropins(uid: int) -> dict:
    out = await _systemctl(["show", f"user-{int(uid)}.slice", "-p", "Description", "-p", "DropInPaths"])
    return classify_dropins(out)


def validate_request(changes: dict, *, total_memory_bytes: int, cpu_count: int) -> dict[str, str]:
    """Ubah permintaan UI -> properti systemd. None = lepaskan batas itu."""
    unknown = set(changes) - set(_PROPERTIES)
    if unknown:
        raise LinuxLimitError(f"Properti tidak dikenal: {sorted(unknown)}")
    if not changes:
        raise LinuxLimitError("Tidak ada properti yang diubah.")
    props: dict[str, str] = {}
    for key, value in changes.items():
        prop = _PROPERTIES[key]
        if value is None:
            props[prop] = ""  # systemd: string kosong = kembali ke default (tanpa batas)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            raise LinuxLimitError(f"Nilai {key} harus angka.")
        if key == "cpu_cores":
            if not 0.1 <= value <= cpu_count:
                raise LinuxLimitError(f"Kuota CPU harus 0.1–{cpu_count} core.")
            props[prop] = f"{int(round(value * 100))}%"
        else:
            value = int(value)
            if not 256 * 1024 * 1024 <= value <= total_memory_bytes:
                raise LinuxLimitError("Batas RAM harus antara 256 MiB dan RAM total server.")
            props[prop] = str(value)
    high, mx = changes.get("memory_high_bytes"), changes.get("memory_max_bytes")
    if high is not None and mx is not None and high > mx:
        raise LinuxLimitError("RAM lunak tidak boleh melebihi RAM maksimum.")
    return props


def _helper_argv(name: str, host_cmd: list[str]) -> list[str]:
    """Jalankan perintah HOST lewat nsenter ke PID 1. Tanpa jaringan & tanpa mount host;
    root hanya di dalam container; capability minimum untuk setns; apparmor dilepas karena
    profil docker-default memblokir setns (terukur), seccomp bawaan tetap dipakai."""
    from app.core.config import settings

    return [
        *shlex.split(settings.DOCKER_CMD), "run", "--rm", "--pull=never",
        "--name", name, "--label", "computehub.helper=linux-limits-write",
        "--network", "none", "--pid=host", "--read-only", "--user", "0:0",
        "--cap-drop", "ALL", "--cap-add", "SYS_ADMIN", "--cap-add", "SYS_PTRACE", "--cap-add", "SYS_CHROOT",
        "--security-opt", "no-new-privileges", "--security-opt", "apparmor=unconfined",
        "--pids-limit", "16", "--memory", "64m", "--cpus", "0.25",
        "--entrypoint", "nsenter", settings.DISK_SCAN_IMAGE,
        "-t", "1", "-m", "-u", "-i", "--", *host_cmd,
    ]


_RUNTIME_UNIT_DIR_RE = re.compile(r"^/run/systemd/system\.control/user-\d+\.slice\.d$")


async def _host_exec(host_cmd: list[str]) -> str:
    """Perintah host selain systemctl. Dibatasi keras: hanya `rm -rf` folder drop-in RUNTIME
    milik satu user slice (jalur diverifikasi regex) — tidak ada jalur lain yang diizinkan."""
    if not (len(host_cmd) == 3 and host_cmd[:2] == ["rm", "-rf"] and _RUNTIME_UNIT_DIR_RE.match(host_cmd[2])):
        raise LinuxLimitError("Perintah host tidak diizinkan.")
    return await _run_host(host_cmd)


async def _systemctl(args: list[str]) -> str:
    return await _run_host(["systemctl", "--no-pager", *args])


async def _run_host(host_cmd: list[str]) -> str:
    from app.core.config import settings

    if Path("/.dockerenv").exists():
        name = f"ch-linux-limits-w-{uuid.uuid4().hex[:12]}"
        argv = _helper_argv(name, host_cmd)
    else:
        name = ""
        argv = ["sudo", "-n", *host_cmd]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        if name:
            rm = await asyncio.create_subprocess_exec(
                *shlex.split(settings.DOCKER_CMD), "rm", "-f", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await rm.wait()
        raise LinuxLimitError("systemctl tidak merespons (timeout).")
    if proc.returncode != 0:
        raise LinuxLimitError(f"systemctl gagal: {err.decode(errors='replace').strip()[:300]}")
    return out.decode(errors="replace")


async def apply_runtime_limits(uid: int, username: str, changes: dict) -> dict:
    """Pasang batas RUNTIME pada user-<uid>.slice (drop-in di /run; hilang saat reboot).

    Menolak bila akun sudah punya aturan permanen ATAU runtime yang bukan buatan
    ComputeHub — itu aturan admin IT dan tidak boleh ditimpa dari UI.
    """
    if isinstance(uid, bool) or not isinstance(uid, int) or uid < 1000:
        raise LinuxLimitError("UID tidak valid.")
    total_mem = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    props = validate_request(changes, total_memory_bytes=total_mem, cpu_count=os.cpu_count() or 1)
    info = await dropins(uid)
    if info["permanent"] or info["runtime_other"]:
        milik_lain = ", ".join(Path(p).name for p in info["permanent"] + info["runtime_other"])
        raise LinuxLimitError(
            f"Akun {username} sudah punya aturan systemd dari luar ComputeHub ({milik_lain}). "
            "Tidak ditimpa — koordinasikan dengan admin IT."
        )
    unit = f"user-{uid}.slice"
    # Penanda dipasang SEBELUM batas: bila langkah kedua gagal, drop-in yang tersisa
    # tetap dikenali sebagai milik ComputeHub sehingga bisa dikembalikan.
    await _systemctl(["--runtime", "set-property", unit,
                      f"Description=User Slice of UID {uid} [{_MANAGED_MARKER}]"])
    await _systemctl(["--runtime", "set-property", unit, *[f"{k}={v}" for k, v in props.items()]])
    invalidate()
    after = await dropins(uid)
    return {"unit": unit, "properties": props, "dropins": [Path(p).name for p in after["managed"]]}


async def revert_runtime_limits(uid: int) -> dict:
    """Lepas SEMUA batas runtime buatan ComputeHub -> akun kembali ke aturan sistem/IT.

    `systemctl revert` SENGAJA tidak dipakai: ia juga menghapus drop-in permanen milik IT.
    """
    if isinstance(uid, bool) or not isinstance(uid, int) or uid < 1000:
        raise LinuxLimitError("UID tidak valid.")
    unit = f"user-{uid}.slice"
    info = await dropins(uid)
    if not info["managed"]:
        return {"unit": unit, "removed": [], "note": "tidak ada aturan ComputeHub pada akun ini"}
    # set-property kosong mengembalikan nilai default seketika (cgroup ikut), tetapi
    # menyisakan berkas drop-in kosong -> hapus berkasnya (HANYA folder runtime unit ini)
    # lalu daemon-reload agar DropInPaths bersih seperti sebelum disentuh.
    props = sorted({Path(p).stem.split("-", 1)[1] for p in info["managed"]})
    await _systemctl(["--runtime", "set-property", unit, *[f"{p}=" for p in props]])
    await _host_exec(["rm", "-rf", f"{_RUNTIME_DROPIN_DIR}{unit}.d"])
    await _systemctl(["daemon-reload"])
    invalidate()
    return {"unit": unit, "removed": [Path(p).name for p in info["managed"]]}


def invalidate() -> None:
    global _cache_until
    _cache_until = 0.0


async def _ownership_map(uids: list[int]) -> dict[int, dict]:
    """Kepemilikan aturan untuk banyak akun dalam SATU panggilan systemctl (hemat helper).
    Best-effort: gagal -> {} (UI menampilkan 'belum diketahui', bukan 'bebas')."""
    if not uids:
        return {}
    try:
        out = await _systemctl(["show", *[f"user-{u}.slice" for u in uids], "-p", "Id", "-p", "Description", "-p", "DropInPaths"])
    except LinuxLimitError:
        return {}
    result: dict[int, dict] = {}
    for block in out.strip().split("\n\n"):
        unit = next((l.partition("=")[2].strip() for l in block.splitlines() if l.startswith("Id=")), "")
        if not unit.startswith("user-"):
            continue
        try:
            uid = int(unit[len("user-"):-len(".slice")])
        except ValueError:
            continue
        info = classify_dropins(block)
        result[uid] = {
            "by_computehub": bool(info["managed"]),
            "external": [Path(p).name for p in info["permanent"] + info["runtime_other"]],
        }
    return result


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
    from app.core.config import settings
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
            # Kepemilikan aturan butuh helper ber-hak (nsenter). Hanya dijalankan bila mode
            # tulis aktif; dalam mode baca-saja info ini tidak diperlukan UI.
            owners = await _ownership_map(sorted(accounts)) if settings.LINUX_LIMITS_WRITE_ENABLED else {}
            users = [
                {**row, "username": accounts[row["uid"]], "managed": owners.get(row["uid"])}
                for row in result["users"] if row["uid"] in accounts
            ]
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, asyncio.TimeoutError) as exc:
            get_logger(__name__).warning("Batas cgroup Linux tidak terbaca: %s", exc)
            result = {"available": False, "reason": "reader_unavailable"}
            users = []
        payload = {
            "available": result["available"],
            "reason": result.get("reason"),
            # Tulis hanya lewat endpoint terpisah (super admin, runtime). Snapshot ini tetap baca.
            "read_only": True,
            "writable": bool(settings.LINUX_LIMITS_WRITE_ENABLED) and result["available"],
            "source": "cgroup_v2",
            "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "users": sorted(users, key=lambda row: (not row["active"], row["username"])),
        }
        _cache = payload
        _cache_until = time.monotonic() + _CACHE_SECONDS
        return payload


if __name__ == "__main__":
    print(json.dumps(collect_limits(Path(sys.argv[1]), json.loads(sys.argv[2]))))