"""Provisioning Docker per-user (1 user 1 docker) — OPT-IN, aman & berlingkup ketat.

ATURAN KERAS (sesuai instruksi dosen & pemilik):
  - HANYA menyentuh container/volume bernama PERSIS f"{prefix}{user_id}" (mis. ch-user-12).
  - TIDAK PERNAH `docker system prune`, rm/stop pola lebar, atau menyentuh container milik
    pengguna lain di daemon BERSAMA.
  - TIDAK mengubah daemon, grup, atau sudoers. Memakai biner `settings.DOCKER_CMD` apa adanya.
  - Default NONAKTIF (settings.DOCKER_PROVISION_ENABLED=False): SEMUA fungsi jadi no-op
    sehingga perilaku sistem live TIDAK berubah sampai diaktifkan secara eksplisit.

Container per-user bersifat DISPOSABLE (bisa dibuat ulang dari image + volume). Volume
(data) durable di settings.docker_user_data_root / <user_id>.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def hardening_argv() -> list[str]:
    """Argumen `docker run` utk hardening container yang menjalankan kode tak tepercaya.

    - --cap-drop ALL + --security-opt no-new-privileges: buang semua Linux capability &
      cegah eskalasi via setuid (Python/torch/pip tak butuh capability apa pun).
    - --user <uid>:<gid> host: proses non-root di container + file hasil dimiliki user host
      (bukan root) -> cleanup tanpa sudo. GPU tetap jalan (device /dev/nvidia* world-rw).
    Semua best-effort; bila flag dimatikan (config) -> tak menambah argumen (perilaku lama).
    """
    args: list[str] = []
    if settings.DOCKER_HARDENING:
        args += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    if settings.DOCKER_RUN_AS_HOST_USER:
        try:
            args += ["--user", f"{os.getuid()}:{os.getgid()}"]
        except Exception:  # noqa: BLE001  (mis. non-POSIX) -> lewati saja
            pass
    return args


def is_enabled() -> bool:
    """True bila provisioning Docker per-user diaktifkan (default False = inert)."""
    return bool(settings.DOCKER_PROVISION_ENABLED)


# --- Jaringan bridge ber-MTU rendah, dipakai BERSAMA devbox/job/kernel -------------
# CATATAN: bagian ini SENGAJA tidak ikut gerbang `is_enabled()` — devbox, job, dan kernel
# tetap jalan walau provisioning per-user mati, jadi jaringannya pun harus tetap tersedia.
#
# Diisi oleh `ensure_network()`. Container dipasang ke jaringan ini HANYA bila ia benar-benar
# ada; kalau gagal dibuat, semuanya kembali ke bridge bawaan (perilaku lama) alih-alih
# gagal total dengan "network not found".
_net_siap = False


def network_name() -> str:
    """Nama jaringan MILIK KITA; "" bila fitur dimatikan (MTU 0 / nama kosong)."""
    nama = (settings.CONTAINER_NETWORK or "").strip()
    try:
        mtu = int(settings.CONTAINER_NETWORK_MTU)
    except (TypeError, ValueError):
        return ""
    return nama if (nama and mtu > 0) else ""


def network_argv() -> list[str]:
    """`--network <nama>` bila jaringan SIAP; [] bila tidak -> pakai bridge bawaan."""
    nama = network_name()
    return ["--network", nama] if (nama and _net_siap) else []


async def ensure_network() -> bool:
    """Siapkan jaringan bridge ber-MTU rendah (idempoten, aman dipanggil berulang).

    Kenapa perlu: jalur kampus adalah PMTU black hole (lihat CONTAINER_NETWORK di config).
    Dengan MTU lebih kecil, MSS yang kita iklankan ikut mengecil sehingga lawan bicara
    mengirim paket yang muat lewat tanpa perlu ICMP "fragmentation needed".

    TIDAK PERNAH menghapus/mengubah jaringan yang sudah ada — hanya membuat bila belum ada.
    Return True bila jaringan siap dipakai.
    """
    global _net_siap
    nama = network_name()
    if not nama:
        _net_siap = False
        return False
    rc, icc = await _run(
        "network", "inspect", nama, "-f",
        '{{index .Options "com.docker.network.bridge.enable_icc"}}',
    )
    if rc == 0:
        _net_siap = True
        if settings.CONTAINER_NETWORK_ISOLATE and icc.strip() != "false":
            # SENGAJA tidak dibuat ulang otomatis: itu memutus container yang sedang
            # terhubung. Diperingatkan saja supaya tak diam-diam tak berlaku.
            logger.warning(
                "Jaringan %s belum terisolasi (enable_icc masih aktif). Buat ulang saat "
                "tak ada devbox/job/kernel berjalan agar CONTAINER_NETWORK_ISOLATE berlaku.",
                nama,
            )
        return True
    mtu = int(settings.CONTAINER_NETWORK_MTU)
    opsi = ["--opt", f"com.docker.network.driver.mtu={mtu}"]
    if settings.CONTAINER_NETWORK_ISOLATE:
        opsi += ["--opt", "com.docker.network.bridge.enable_icc=false"]
    rc, out = await _run("network", "create", "--driver", "bridge", *opsi, nama)
    if rc != 0:
        # Bisa jadi balapan dgn proses lain yang baru membuatnya -> pastikan sekali lagi.
        rc2, _ = await _run("network", "inspect", nama)
        _net_siap = rc2 == 0
        if not _net_siap:
            logger.warning("Jaringan %s gagal disiapkan: %s", nama, out.strip()[:200])
        return _net_siap
    _net_siap = True
    logger.info("Jaringan %s siap (bridge, MTU %d).", nama, mtu)
    return True


async def reattach_network(container: str) -> None:
    """Perbarui endpoint jaringan container yang menyimpan ID jaringan basi.

    Bila jaringan pernah dihapus & dibuat ulang (nama sama, ID baru), container lama
    yang berhenti gagal `docker start` dengan "network <id> not found". Menyambung
    ulang memperbaikinya TANPA menghapus container — data & kredensial tetap utuh.
    """
    nama = network_name()
    if not nama or not _net_siap:
        return
    await _run("network", "disconnect", "-f", nama, container)
    await _run("network", "connect", nama, container)


def provision_mode() -> str:
    """Mode provisioning: 'on_demand' (default, tanpa container idle) atau 'eager'."""
    return (settings.DOCKER_PROVISION_MODE or "on_demand").strip().lower()


def container_name(user_id: int) -> str:
    """Nama container MILIK KITA untuk user — selalu prefix + id (tak ada pola lebar)."""
    return f"{settings.DOCKER_USER_PREFIX}{int(user_id)}"


def _user_data_dir(user_id: int) -> Path:
    return settings.docker_user_data_root / str(int(user_id))


def _docker_argv(*args: str) -> list[str]:
    """Bangun argv docker dari DOCKER_CMD (di-split) + argumen. TANPA shell."""
    return [*settings.DOCKER_CMD.split(), *args]


async def _run_raw(argv: list[str]) -> tuple[int, str]:
    """Jalankan satu perintah (tanpa shell). Return (rc, output). TIDAK melempar."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out_b, _ = await asyncio.wait_for(
            proc.communicate(), timeout=settings.DOCKER_CMD_TIMEOUT_SECONDS
        )
        return proc.returncode or 0, (out_b or b"").decode(errors="replace").strip()
    except asyncio.TimeoutError:
        return 124, "timeout"
    except FileNotFoundError:
        return 127, f"perintah tidak ditemukan ({argv[:1]!r})"
    except Exception as exc:  # noqa: BLE001 — best-effort
        return 1, repr(exc)


async def _run(*args: str) -> tuple[int, str]:
    """Jalankan satu perintah docker (tanpa shell). Hanya dipanggil saat fitur aktif."""
    return await _run_raw(_docker_argv(*args))


def _sudo_prefix() -> list[str]:
    """Bagian `sudo ...` dari DOCKER_CMD (sebelum token 'docker'); [] bila tak pakai sudo.

    Mengenali baik biner relatif (`sudo`/`docker`) maupun absolut (`/usr/bin/sudo`).
    """
    base = settings.DOCKER_CMD.split()
    if not base or Path(base[0]).name != "sudo":
        return []
    for i, tok in enumerate(base):
        if Path(tok).name == "docker":
            return base[:i]
    return ["sudo", "-n"]


def _is_safe_user_data_dir(data: Path, user_id: int) -> bool:
    """Validasi KETAT: data HARUS persis <data_root>/<user_id> (cegah salah hapus)."""
    try:
        root = settings.docker_user_data_root.resolve()
        d = data.resolve()
    except Exception:  # noqa: BLE001
        return False
    return d.parent == root and d.name == str(int(user_id))


async def _remove_data_dir(user_id: int) -> bool:
    """Hapus folder data user dgn validasi ketat; fallback sudo bila ada file root-owned."""
    data = _user_data_dir(user_id)
    if not _is_safe_user_data_dir(data, user_id):
        logger.error("Tolak hapus data: path tak valid %s", data)
        return False
    if not data.exists():
        return True
    shutil.rmtree(data, ignore_errors=True)
    if not data.exists():
        logger.info("Volume data %s dihapus", data)
        return True
    # Sisa file root-owned (container jalan sbg root) -> hapus via sudo (path TERVALIDASI).
    sudo = _sudo_prefix()
    if sudo:
        rc, out = await _run_raw([*sudo, "rm", "-rf", str(data)])
        if rc == 0 and not data.exists():
            logger.info("Volume data %s dihapus (sudo)", data)
            return True
        logger.warning("Gagal hapus data %s (rc=%s): %s", data, rc, out)
    else:
        logger.warning("Sisa file di %s; tak ada sudo utk membersihkan", data)
    return False


async def _exists(user_id: int) -> bool:
    name = container_name(user_id)
    rc, out = await _run(
        "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"
    )
    return rc == 0 and name in out.splitlines()


def _run_args(user_id: int) -> list[str]:
    """Argumen `docker run` membuat container per-user (scoped, berbatas resource)."""
    name = container_name(user_id)
    data = _user_data_dir(user_id)
    args = ["run", "-d", "--name", name, "--restart", "unless-stopped"]
    if settings.DOCKER_USER_GPUS:
        if settings.DOCKER_GPU_MODE == "legacy":
            args += ["--runtime", "nvidia", "-e", f"NVIDIA_VISIBLE_DEVICES={settings.DOCKER_USER_GPUS}"]
        else:
            args += ["--gpus", settings.DOCKER_USER_GPUS]
    if settings.DOCKER_USER_MEMORY:
        args += ["--memory", settings.DOCKER_USER_MEMORY]
    if settings.DOCKER_USER_CPUS:
        args += ["--cpus", settings.DOCKER_USER_CPUS]
    if settings.DOCKER_USER_PIDS_LIMIT > 0:
        args += ["--pids-limit", str(settings.DOCKER_USER_PIDS_LIMIT)]
    args += ["-v", f"{data}:/work", "-w", "/work"]
    args += [settings.DOCKER_USER_IMAGE, "sleep", "infinity"]
    return args


def plan_provision(user_id: int) -> str:
    """Pratinjau perintah provisioning (TANPA mengeksekusi) — untuk audit/demo."""
    return " ".join(_docker_argv(*_run_args(user_id)))


async def provision_user(user_id: int) -> bool:
    """Siapkan workspace per-user. No-op bila fitur nonaktif. Best-effort (TIDAK melempar).

    Mode 'on_demand' (default, EFISIEN): cukup PASTIKAN folder data user ada — TANPA
    container idle. Eksekusi memakai container efemeral (ch-job-*/ch-kernel-*) yang mount
    volume ini (/persist) saat dipakai saja, lalu auto-hapus. Mode 'eager': juga buat
    container persisten ch-user-<id> (idempoten, lewati bila sudah ada).
    """
    if not is_enabled():
        return False
    try:
        _user_data_dir(user_id).mkdir(parents=True, exist_ok=True)
        if provision_mode() != "eager":
            return True  # on-demand: folder data cukup; tak ada container idle (hemat resource)
        if await _exists(user_id):
            return True
        rc, out = await _run(*_run_args(user_id))
        if rc != 0:
            logger.warning(
                "Provision %s gagal (rc=%s): %s", container_name(user_id), rc, out
            )
            return False
        logger.info("Provision container %s OK", container_name(user_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Provision %s error: %r", container_name(user_id), exc)
        return False


async def deprovision_user(user_id: int, *, remove_data: bool = False) -> bool:
    """Hapus container per-user (by-name PERSIS). Bila remove_data: hapus volume juga.

    Dipakai untuk: NONAKTIF (remove_data=False -> data TETAP) & HAPUS akun
    (remove_data=True -> purge). No-op bila fitur nonaktif. Best-effort.
    """
    if not is_enabled():
        return False
    name = container_name(user_id)
    ok = True
    rc, out = await _run("rm", "-f", name)  # by-name PERSIS, BUKAN pola lebar
    if rc != 0 and "No such container" not in out:
        logger.warning("Deprovision %s rc=%s: %s", name, rc, out)
        ok = False
    else:
        logger.info("Container %s dihapus (atau memang tak ada)", name)

    if remove_data:
        if not await _remove_data_dir(user_id):
            ok = False
    return ok
