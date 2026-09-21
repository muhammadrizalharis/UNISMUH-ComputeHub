#!/usr/bin/env python3
"""ProxyCommand SSH: salurkan stdin/stdout ke WebSocket ComputeHub (macOS/Linux).

Dipakai otomatis oleh ~/.ssh/config yang dipasang ComputeHub:

    Host computehub-19
        ProxyCommand python3 ~/.ssh/computehub/devbox_ssh_proxy.py wss://.../devbox-ssh/19 <token>

Sengaja STDLIB SAJA (tanpa pip install): laptop mahasiswa tidak boleh perlu menyiapkan
apa pun, dan jaringan kampus ke internet luar sedang tidak dapat diandalkan. Protokol
WebSocket-nya diimplementasikan seperlunya: jabat tangan RFC 6455 + bingkai biner.
"""

from __future__ import annotations

import base64
import os
import socket
import ssl
import struct
import sys
import time
import threading
from urllib.parse import urlsplit

_CHUNK = 65536


def _fail(pesan: str) -> None:
    sys.stderr.write(f"[computehub] {pesan}\n")
    sys.exit(1)


class _Fatal(Exception):
    """Penolakan pasti (mis. 401/403) -> jangan diulang."""


class _Retry(Exception):
    """Gangguan sementara (TLS/handshake putus, 5xx) -> boleh diulang."""


def _handshake(sock: socket.socket, host: str, path: str) -> None:
    kunci = base64.b64encode(os.urandom(16)).decode()
    permintaan = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {kunci}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: ComputeHub-SSH-Proxy/1\r\n\r\n"
    )
    sock.sendall(permintaan.encode())
    header = b""
    while b"\r\n\r\n" not in header:
        bagian = sock.recv(1)
        if not bagian:
            # Jalur kampus kadang memutus jabat tangan TLS/WS (PMTU) -> layak diulang.
            raise _Retry("sambungan ditutup server saat jabat tangan.")
        header += bagian
        if len(header) > 16384:
            raise _Retry("jawaban server tidak wajar.")
    baris = header.split(b"\r\n", 1)[0].decode("latin-1")
    if "101" not in baris:
        if "401" in baris or "403" in baris:
            raise _Fatal("akses ditolak. Unduh ulang pemasang dari menu Devbox ComputeHub.")
        # 5xx (devbox belum siap / backend sesaat) -> ulang; devbox bisa selesai menyala.
        raise _Retry(f"server belum siap: {baris}")


def _kirim(sock: socket.socket, data: bytes, opcode: int = 0x2) -> None:
    """Satu bingkai bermask (klien WAJIB mask menurut RFC 6455)."""
    panjang = len(data)
    bingkai = bytearray([0x80 | opcode])
    if panjang < 126:
        bingkai.append(0x80 | panjang)
    elif panjang < (1 << 16):
        bingkai.append(0x80 | 126)
        bingkai += struct.pack("!H", panjang)
    else:
        bingkai.append(0x80 | 127)
        bingkai += struct.pack("!Q", panjang)
    mask = os.urandom(4)
    bingkai += mask
    bingkai += bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bingkai)


def _baca_pasti(sock: socket.socket, jumlah: int) -> bytes:
    data = b""
    while len(data) < jumlah:
        bagian = sock.recv(jumlah - len(data))
        if not bagian:
            return b""
        data += bagian
    return data


def _terima(sock: socket.socket) -> tuple[int, bytes] | None:
    kepala = _baca_pasti(sock, 2)
    if len(kepala) < 2:
        return None
    opcode = kepala[0] & 0x0F
    bermask = bool(kepala[1] & 0x80)
    panjang = kepala[1] & 0x7F
    if panjang == 126:
        panjang = struct.unpack("!H", _baca_pasti(sock, 2))[0]
    elif panjang == 127:
        panjang = struct.unpack("!Q", _baca_pasti(sock, 8))[0]
    mask = _baca_pasti(sock, 4) if bermask else b""
    isi = _baca_pasti(sock, panjang) if panjang else b""
    if bermask and isi:
        isi = bytes(b ^ mask[i % 4] for i, b in enumerate(isi))
    return opcode, isi


def main() -> None:
    if len(sys.argv) < 3:
        _fail("pemakaian: devbox_ssh_proxy.py <wss://host/path> <token>")
    url, token = sys.argv[1], sys.argv[2]
    bagian = urlsplit(url)
    aman = bagian.scheme in ("wss", "https")
    host = bagian.hostname or ""
    port = bagian.port or (443 if aman else 80)
    path = (bagian.path or "/") + f"?token={token}"

    # Coba ulang beberapa kali: dari jaringan luar, jabat tangan TLS/WS ke kampus
    # kadang putus (PMTU) sehingga VS Code -- yang membuka beberapa koneksi sekaligus --
    # gagal total hanya karena satu percobaan tersendat.
    sock = None
    galat = ""
    for percobaan in range(6):
        try:
            mentah = socket.create_connection((host, port), timeout=20)
            mentah.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if aman:
                konteks = ssl.create_default_context()
                sock = konteks.wrap_socket(mentah, server_hostname=host)
            else:
                sock = mentah
            _handshake(sock, bagian.netloc, path)
            break
        except _Fatal as exc:
            _fail(str(exc))
        except (_Retry, OSError, ssl.SSLError) as exc:
            galat = str(exc)
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                pass
            sock = None
            time.sleep(min(1.0 + percobaan, 4.0))
    if sock is None:
        _fail(f"tidak bisa menyambung ke ComputeHub setelah beberapa percobaan: {galat}")
    sock.settimeout(None)

    masuk = sys.stdin.buffer
    keluar = sys.stdout.buffer

    def dari_ssh() -> None:
        try:
            while True:
                data = masuk.read1(_CHUNK) if hasattr(masuk, "read1") else masuk.read(_CHUNK)
                if not data:
                    break
                _kirim(sock, data)
        except OSError:
            pass
        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    threading.Thread(target=dari_ssh, daemon=True).start()
    try:
        while True:
            bingkai = _terima(sock)
            if bingkai is None:
                break
            opcode, isi = bingkai
            if opcode in (0x1, 0x2, 0x0) and isi:
                keluar.write(isi)
                keluar.flush()
            elif opcode == 0x8:  # close
                break
            elif opcode == 0x9:
                # Payload ping WAJIB dipantulkan apa adanya: server menunggu pong yang
                # cocok, dan bila tidak cocok koneksi menganggur akan diputus.
                _kirim(sock, isi, opcode=0xA)
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
    # Keluar tanpa menutup runtime: thread pembaca stdin masih memegang kunci buffer,
    # dan penutupan normal bisa memunculkan galat fatal yang membingungkan pengguna.
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)
