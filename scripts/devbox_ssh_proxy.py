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
import threading
from urllib.parse import urlsplit

_CHUNK = 65536


def _fail(pesan: str) -> None:
    sys.stderr.write(f"[computehub] {pesan}\n")
    sys.exit(1)


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
            _fail("sambungan ditutup server saat jabat tangan.")
        header += bagian
        if len(header) > 16384:
            _fail("jawaban server tidak wajar.")
    baris = header.split(b"\r\n", 1)[0].decode("latin-1")
    if "101" not in baris:
        if "401" in baris or "403" in baris:
            _fail("akses ditolak. Unduh ulang pemasang dari menu Devbox ComputeHub.")
        if "503" in baris:
            _fail("devbox belum siap. Nyalakan dari ComputeHub lalu coba lagi.")
        _fail(f"server menolak: {baris}")


def _kirim(sock: socket.socket, data: bytes) -> None:
    """Satu bingkai biner bermask (klien WAJIB mask menurut RFC 6455)."""
    panjang = len(data)
    bingkai = bytearray([0x82])
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

    mentah = socket.create_connection((host, port), timeout=30)
    mentah.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    if aman:
        konteks = ssl.create_default_context()
        sock: socket.socket = konteks.wrap_socket(mentah, server_hostname=host)
    else:
        sock = mentah
    _handshake(sock, bagian.netloc, path)
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
            elif opcode == 0x9:  # ping -> pong
                sock.sendall(b"\x8a\x80" + os.urandom(4))
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
