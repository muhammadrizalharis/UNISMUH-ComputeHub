"""Terminal web di DALAM container kernel user (docker exec + PTY).

Keamanan = isolasi container yang SUDAH ada: shell berjalan di container kernel
milik user (ch-kernel-<sid>) yang hanya me-mount /work (workdir sesi), /persist
(miliknya sendiri), dan /opt/ch-shared + /opt/ch-models (read-only). Folder user
lain tidak pernah ada di namespace container -> tak mungkin diakses. Batas CPU/
RAM/pids container tetap berlaku. Ini BUKAN permukaan serangan baru: user memang
sudah bisa `!perintah` dari sel notebook; terminal hanya UX-nya.

Alur: WS terminal (router interactive) -> ContainerTerminal.spawn `docker exec
-it <container> bash` yang stdin/stdout-nya PTY -> relay dua arah ke WebSocket
(output = binary frame, input/resize = JSON text frame dari xterm.js).

Shell MILIK SESI KERNEL (PersistentTerminal), bukan milik koneksi WS: pindah menu /
window / tab hanya melepas WS; shell & proses di dalamnya tetap jalan, output
ditampung lalu diputar ulang saat WS tersambung lagi (pola sama dgn eksekusi sel).
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import pty
import signal
import struct
import termios
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Batas ukuran satu pesan input (paste besar dipecah klien; ini pagar terakhir).
MAX_INPUT_CHARS = 256 * 1024
# Riwayat output yang diputar ulang saat WS tersambung lagi (ekor terbaru saja).
REPLAY_MAX_BYTES = 256 * 1024

Sink = Callable[[bytes], Awaitable[None]]
Hook = Callable[[], Awaitable[None]]


class ContainerTerminal:
    """Satu shell interaktif (bash) di dalam container kernel, via PTY.

    Shell SELALU berjalan sebagai user container yang sama dengan kernel (non-root).
    CATATAN riwayat: exec `-u 0:0` untuk super admin pernah dicoba dan DIHAPUS —
    container memakai --cap-drop ALL sehingga root kehilangan CAP_DAC_OVERRIDE dan
    justru TIDAK bisa menulis /work & /persist milik user (git/mkdir Permission
    denied). Root cap-dropped lebih lemah dari user biasa di folder kerja.
    """

    def __init__(
        self,
        container: str,
        cwd: str = "/work",
        username: str = "user",
    ) -> None:
        self.container = container
        self.cwd = cwd
        # Nama untuk prompt (username ComputeHub user). HANYA huruf/angka/._- —
        # disanitasi pemanggil; pagar terakhir di sini.
        self.username = "".join(c for c in username if c.isalnum() or c in "._-") or "user"
        self.proc: asyncio.subprocess.Process | None = None
        self.master: int = -1

    async def start(self) -> None:
        """Spawn `docker exec -it <container> bash` dengan PTY sebagai TTY-nya."""
        master, slave = pty.openpty()
        # --noprofile --norc: lewati bashrc image (mengeluh UID non-root tak ada di
        # /etc/passwd -> "I have no name!" / "groups: cannot find ..."). PS1 dari env
        # dipakai bash saat tanpa rc -> prompt bersih: <username>:<cwd>$.
        prompt = (
            f"PS1=\\[\\e[1;36m\\]{self.username}\\[\\e[0m\\]:"
            r"\[\e[1;34m\]\w\[\e[0m\]\$ "
        )
        argv = [
            *settings.DOCKER_CMD.split(),
            "exec", "-it",
            "-w", self.cwd,
            "-e", "TERM=xterm-256color",
            "-e", prompt,
        ]
        argv += [self.container, "bash", "--noprofile", "--norc"]
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(slave)
        self.master = master
        os.set_blocking(master, False)

    def resize(self, cols: int, rows: int) -> None:
        """Sesuaikan ukuran PTY; docker CLI meneruskan (SIGWINCH) ke exec session."""
        if self.master < 0:
            return
        cols = max(2, min(500, int(cols)))
        rows = max(2, min(300, int(rows)))
        with contextlib.suppress(OSError):
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.send_signal(signal.SIGWINCH)

    async def write(self, data: bytes) -> None:
        """Tulis input keyboard ke PTY (non-blocking; tunggu sebentar bila buffer penuh)."""
        if self.master < 0:
            return
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.master, view)
                view = view[n:]
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except OSError:
                return

    def close(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Lepas reader, tutup PTY, matikan proses exec (kernel TIDAK tersentuh)."""
        if loop is not None and self.master >= 0:
            with contextlib.suppress(Exception):
                loop.remove_reader(self.master)
        if self.master >= 0:
            with contextlib.suppress(OSError):
                os.close(self.master)
            self.master = -1
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.kill()


class PersistentTerminal:
    """Shell yang bertahan lintas koneksi WS; satu WS terpasang pada satu waktu.

    - attach(): pasang WS sebagai tujuan output + kembalikan riwayat untuk replay.
    - detach(): WS putus (pindah menu/window) -> shell TETAP jalan, output ditampung.
    - close(): shell dihentikan (user menekan Hentikan / kernel dimatikan).
    Shell selesai sendiri (`exit`) -> WS terpasang ditutup rapi (1000).
    """

    def __init__(
        self,
        term: ContainerTerminal,
        on_activity: Callable[[], None] | None = None,
    ) -> None:
        self.term = term
        self.on_activity = on_activity
        self.alive = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._history = bytearray()
        self._sink: Sink | None = None
        self._on_exit: Hook | None = None
        self._kick: Hook | None = None
        self._pump: asyncio.Task | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self.term.start()
        self.alive = True
        self._loop.add_reader(self.term.master, self._readable)
        self._pump = asyncio.create_task(self._pump_output())

    def _readable(self) -> None:
        try:
            data = os.read(self.term.master, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if data:
            self._queue.put_nowait(data)
        else:  # EOF: shell exit / PTY tutup
            if self._loop is not None:
                with contextlib.suppress(Exception):
                    self._loop.remove_reader(self.term.master)
            self._queue.put_nowait(b"")

    async def _pump_output(self) -> None:
        while True:
            data = await self._queue.get()
            if not data:
                break
            self._history += data
            if len(self._history) > REPLAY_MAX_BYTES:
                del self._history[: len(self._history) - REPLAY_MAX_BYTES]
            if self.on_activity is not None:
                self.on_activity()
            sink = self._sink
            if sink is None:
                continue
            try:
                await sink(data)
            except Exception:  # noqa: BLE001 - WS putus di tengah kirim
                self.detach(sink)
        self.alive = False
        self.term.close(self._loop)
        on_exit = self._on_exit
        self._sink = self._on_exit = self._kick = None
        if on_exit is not None:
            with contextlib.suppress(Exception):
                await on_exit()

    def attach(self, sink: Sink, on_exit: Hook, kick: Hook) -> tuple[bytes, Hook | None]:
        """Pasang WS baru. Kembalikan (riwayat utk replay, kick WS lama bila ada)."""
        previous = self._kick if self._sink is not None and self._sink != sink else None
        self._sink, self._on_exit, self._kick = sink, on_exit, kick
        return bytes(self._history), previous

    def detach(self, sink: Sink) -> None:
        if self._sink is not None and self._sink == sink:
            self._sink = self._on_exit = self._kick = None

    async def write(self, data: bytes) -> None:
        if self.alive:
            await self.term.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self.alive:
            self.term.resize(cols, rows)

    def close(self) -> None:
        if self._pump is None or self._pump.done():
            return
        self.alive = False
        self.term.close(self._loop)
        # Reader sudah dilepas -> EOF tak akan datang; akhiri pump secara eksplisit.
        self._queue.put_nowait(b"")
