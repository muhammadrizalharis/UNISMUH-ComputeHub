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

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Batas ukuran satu pesan input (paste besar dipecah klien; ini pagar terakhir).
MAX_INPUT_CHARS = 256 * 1024


class ContainerTerminal:
    """Satu shell interaktif (bash) di dalam container kernel, via PTY."""

    def __init__(
        self,
        container: str,
        cwd: str = "/work",
        username: str = "user",
        as_root: bool = False,
    ) -> None:
        self.container = container
        self.cwd = cwd
        # Nama untuk prompt (username ComputeHub user). HANYA huruf/angka/._- —
        # disanitasi pemanggil; pagar terakhir di sini.
        self.username = "".join(c for c in username if c.isalnum() or c in "._-") or "user"
        # Shell root (uid 0) HANYA untuk super admin — di kernel miliknya sendiri.
        self.as_root = as_root
        self.proc: asyncio.subprocess.Process | None = None
        self.master: int = -1

    async def start(self) -> None:
        """Spawn `docker exec -it <container> bash` dengan PTY sebagai TTY-nya."""
        master, slave = pty.openpty()
        # --noprofile --norc: lewati bashrc image (mengeluh UID non-root tak ada di
        # /etc/passwd -> "I have no name!" / "groups: cannot find ..."). PS1 dari env
        # dipakai bash saat tanpa rc -> prompt bersih: <username>:<cwd>$ (root: #).
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
        if self.as_root:
            argv += ["-u", "0:0"]
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
