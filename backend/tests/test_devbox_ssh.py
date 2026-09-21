"""Uji ProxyCommand WebSocket (scripts/devbox_ssh_proxy.py) end-to-end lokal.

Dijalankan tanpa devbox: server WebSocket tiruan berperan sebagai backend, lalu skrip
proxy dijalankan sebagai proses nyata dengan stdin/stdout pipa — persis seperti dipakai
ssh. Yang dikunci: jabat tangan RFC 6455, bingkai bermask dari klien, data dua arah
(termasuk potongan besar), dan penutupan bersih.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, main

import websockets

PROXY = Path(__file__).resolve().parents[2] / "scripts" / "devbox_ssh_proxy.py"


class ProxyCommandTests(IsolatedAsyncioTestCase):
    async def test_dua_arah_dan_potongan_besar(self) -> None:
        diterima: list[bytes] = []
        siap = asyncio.Event()

        async def handler(ws) -> None:  # noqa: ANN001
            siap.set()
            async for pesan in ws:
                diterima.append(pesan if isinstance(pesan, bytes) else pesan.encode())
                if diterima[-1] == b"PING\n":
                    await ws.send(b"PONG\n")
                elif diterima[-1].startswith(b"BESAR"):
                    await ws.send(b"X" * 200_000)

        server = await websockets.serve(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(PROXY), f"ws://127.0.0.1:{port}/devbox-ssh/1", "token-uji",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(b"PING\n")
            await proc.stdin.drain()
            await asyncio.wait_for(siap.wait(), timeout=10)
            balasan = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
            self.assertEqual(balasan, b"PONG\n", "data server -> ssh harus utuh")
            self.assertEqual(diterima[0], b"PING\n", "data ssh -> server harus utuh (bermask)")

            proc.stdin.write(b"BESAR\n")
            await proc.stdin.drain()
            besar = await asyncio.wait_for(proc.stdout.readexactly(200_000), timeout=20)
            self.assertEqual(len(besar), 200_000, "bingkai besar (>64 KB) harus tersalin penuh")
            self.assertEqual(set(besar), {ord("X")})
        finally:
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()
            server.close()
            await server.wait_closed()

    async def test_server_menolak_ditandai_jelas(self) -> None:
        """401 dari backend harus jadi pesan yang bisa dimengerti, bukan diam lalu hang."""

        async def proses(reader, writer) -> None:  # noqa: ANN001
            await reader.read(1024)
            writer.write(b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(proses, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(PROXY), f"ws://127.0.0.1:{port}/devbox-ssh/1", "token-basi",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=15)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("computehub", err.decode().lower())
            self.assertIn("unduh ulang pemasang", err.decode().lower())
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    main()
