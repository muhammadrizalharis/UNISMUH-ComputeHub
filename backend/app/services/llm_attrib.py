"""Atribusi pemakai LAYANAN BERSAMA (Ollama/LLM, dsb) — jawab "siapa yang memakai".

Latar: beban Ollama tercatat atas nama AKUN LAYANAN (mis. `ollama`/`root`), bukan
mahasiswa yang memakainya. Akibatnya GPU bisa penuh tanpa satu pun laporan per-user
(kejadian nyata 2026-08). Modul ini menjembataninya: membaca tabel socket kernel
(`/proc/net/tcp{,6}` — memuat UID PEMILIK socket, dapat dibaca tanpa root) lalu
memetakan siapa saja yang sedang terhubung ke port layanan.

Klien dari container ComputeHub (job/kernel) dikenali lewat alamat IP docker dan
diterjemahkan menjadi nama container (ch-job-<id> / ch-kernel-<sesi>) supaya bisa
dirujuk ke pemilik job. Semua best-effort: kegagalan apa pun -> daftar kosong,
tidak pernah melempar.
"""

from __future__ import annotations

import ipaddress
import pwd
import subprocess
from collections import Counter

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Port layanan LLM/inferensi bersama yang dipantau (Ollama = 11434).
PORT_LAYANAN: tuple[int, ...] = (11434,)

_PROC_NET = ("/proc/net/tcp", "/proc/net/tcp6")
# Status socket yang TIDAK dihitung: 0A=LISTEN (socket layanan itu sendiri) dan
# 06=TIME_WAIT (sudah lepas dari proses, uid tak bermakna). Sisanya dihitung —
# termasuk 08=CLOSE_WAIT, yaitu koneksi yang MASIH dipegang proses klien; justru
# jejak berharga saat merekonstruksi "siapa tadi yang memakai".
_ST_ABAIKAN = {"0A", "06"}


def _ip_dari_hex(h: str) -> str:
    """Alamat hex little-endian ala /proc/net/tcp -> string IP."""
    try:
        if len(h) <= 8:
            return str(ipaddress.IPv4Address(int.from_bytes(bytes.fromhex(h), "little")))
        b = bytes.fromhex(h)
        b = b"".join(b[i : i + 4][::-1] for i in range(0, len(b), 4))
        addr = ipaddress.IPv6Address(b)
        return str(addr.ipv4_mapped or addr)
    except Exception:  # noqa: BLE001
        return "?"


def _baca_socket() -> list[dict]:
    """Semua socket TCP milik host.

    `antre` = tx_queue+rx_queue: >0 berarti ada data sedang mengalir pada socket
    itu. Inilah pembeda koneksi yang MENGANGGUR dari yang sedang dipakai --
    keep-alive Ollama bisa bertahan lama tanpa aktivitas apa pun.
    """
    rows: list[dict] = []
    for path in _PROC_NET:
        try:
            baris = open(path, encoding="utf-8").read().splitlines()[1:]
        except OSError:
            continue
        for ln in baris:
            f = ln.split()
            if len(f) < 8:
                continue
            try:
                lip, lport = f[1].rsplit(":", 1)
                rip, rport = f[2].rsplit(":", 1)
                tx, _, rx = f[4].partition(":")
                rows.append(
                    {
                        "lokal_ip": _ip_dari_hex(lip),
                        "lokal_port": int(lport, 16),
                        "remote_ip": _ip_dari_hex(rip),
                        "remote_port": int(rport, 16),
                        "uid": int(f[7]),
                        "state": f[3],
                        "antre": int(tx, 16) + int(rx, 16),
                    }
                )
            except (ValueError, IndexError):
                continue
    return rows


def aktivitas(ports: tuple[int, ...] = PORT_LAYANAN) -> dict[int, dict]:
    """Cuplikan RINGAN per-uid: {uid: {"koneksi": n, "aktif": m}}.

    `aktif` HANYA menghitung socket ESTABLISHED yang antreannya berisi, yaitu
    yang benar-benar sedang mengalirkan data. CLOSE_WAIT sengaja dikecualikan:
    socket itu sudah ditutup sepihak oleh layanan dan antreannya berisi sisa data
    yang tak pernah dibaca -- kalau ikut dihitung, klien yang membocorkan socket
    akan tampak seperti pemakai terberat padahal sedang menganggur.

    Sengaja tanpa `docker inspect` supaya cukup murah dipanggil tiap belasan detik.
    """
    hasil: dict[int, dict] = {}
    try:
        for r in _baca_socket():
            if r["state"] in _ST_ABAIKAN or r["remote_port"] not in ports:
                continue
            e = hasil.setdefault(r["uid"], {"koneksi": 0, "aktif": 0})
            e["koneksi"] += 1
            if r["state"] == "01" and r["antre"] > 0:
                e["aktif"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("aktivitas gagal: %r", exc)
    return hasil


def _nama_user(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return f"uid{uid}"


def _peta_ip_container() -> dict[str, str]:
    """IP container -> nama container (best-effort; kosong bila docker tak terjangkau)."""
    try:
        keluar = subprocess.run(
            [
                *settings.DOCKER_CMD.split(),
                "ps",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        nama_list = [n.strip() for n in keluar.stdout.splitlines() if n.strip()]
        if not nama_list:
            return {}
        insp = subprocess.run(
            [
                *settings.DOCKER_CMD.split(),
                "inspect",
                "--format",
                "{{.Name}}|{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
                *nama_list,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        peta: dict[str, str] = {}
        for ln in insp.stdout.splitlines():
            if "|" not in ln:
                continue
            nama, ips = ln.split("|", 1)
            for ip in ips.split():
                if ip:
                    peta[ip] = nama.lstrip("/")
        return peta
    except Exception as exc:  # noqa: BLE001
        logger.debug("Peta IP container gagal: %r", exc)
        return {}


def peta_koneksi(ports: tuple[int, ...] = PORT_LAYANAN) -> dict:
    """Siapa saja yang terhubung ke port layanan (mis. Ollama 11434).

    Return {"ports", "total", "layanan_user", "klien": [...], "server": [...]}.
    `klien` = sisi PEMAKAI (uid pemilik socket = user manusia yang memakai layanan);
    `server` = socket milik layanan itu sendiri, dgn asal koneksi (host/container);
    `layanan_user` = akun OS yang MENJALANKAN layanan (pemilik socket LISTEN) ->
    dipakai mengambil beban resource layanan dari laporan per-user OS.
    """
    hasil = {
        "ports": list(ports),
        "total": 0,
        "layanan_user": "",
        "klien": [],
        "server": [],
    }
    try:
        semua = _baca_socket()
        # 0A = LISTEN. Pemilik socket ini sering root (induk layanan), sedangkan
        # proses pekerja yang memakai GPU berjalan sebagai akun lain -> utamakan
        # setelan eksplisit.
        hasil["layanan_user"] = (settings.LLM_SERVICE_USER or "").strip()
        if not hasil["layanan_user"]:
            listen = [
                r for r in semua if r["state"] == "0A" and r["lokal_port"] in ports
            ]
            if listen:
                hasil["layanan_user"] = _nama_user(listen[0]["uid"])
        rows = [r for r in semua if r["state"] not in _ST_ABAIKAN]
        terkait = [
            r for r in rows if r["remote_port"] in ports or r["lokal_port"] in ports
        ]
        hasil["total"] = len(terkait)
        if not terkait:
            return hasil

        # --- Sisi klien: uid socket = pemakai layanan (bukti atribusi utama) ---
        pemakai = Counter(
            r["uid"] for r in terkait if r["remote_port"] in ports
        )
        hasil["klien"] = [
            {"user": _nama_user(uid), "uid": uid, "koneksi": n}
            for uid, n in pemakai.most_common()
        ]

        # --- Sisi server: dari mana koneksi datang (localhost vs container) ---
        sisi_server = [r for r in terkait if r["lokal_port"] in ports]
        if sisi_server:
            ip_container = (
                _peta_ip_container()
                if any(not r["remote_ip"].startswith("127.") for r in sisi_server)
                else {}
            )
            asal = Counter()
            for r in sisi_server:
                ip = r["remote_ip"]
                asal[ip_container.get(ip) or ("host (localhost)" if ip.startswith("127.") else ip)] += 1
            hasil["server"] = [
                {"asal": a, "koneksi": n} for a, n in asal.most_common()
            ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("peta_koneksi gagal: %r", exc)
    return hasil


def ringkasan_teks(peta: dict) -> str:
    """Satu paragraf siap tempel ke pesan alert / laporan. Kosong bila tak ada data."""
    if not peta or not peta.get("total"):
        return ""
    bagian = []
    if peta.get("klien"):
        bagian.append(
            "Pemakai: "
            + ", ".join(f"{k['user']} ({k['koneksi']} koneksi)" for k in peta["klien"][:6])
        )
    if peta.get("server"):
        bagian.append(
            "Asal koneksi: "
            + ", ".join(f"{s['asal']} ({s['koneksi']})" for s in peta["server"][:6])
        )
    port = ", ".join(str(p) for p in peta.get("ports", []))
    return f"Port {port} — " + " | ".join(bagian) if bagian else ""
