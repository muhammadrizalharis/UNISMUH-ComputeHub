import asyncio
import os
import pty
from unittest import IsolatedAsyncioTestCase, main

from app.services.terminal import ContainerTerminal, PersistentTerminal


class LocalShell(ContainerTerminal):
    """ContainerTerminal yang menjalankan bash lokal (tanpa docker) untuk uji."""

    async def start(self) -> None:
        master, slave = pty.openpty()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                "bash", "--noprofile", "--norc",
                stdin=slave, stdout=slave, stderr=slave,
                start_new_session=True, close_fds=True,
                env={"PS1": "$ ", "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )
        finally:
            os.close(slave)
        self.master = master
        os.set_blocking(master, False)


class Collector:
    def __init__(self) -> None:
        self.data = bytearray()
        self.exited = asyncio.Event()
        self.kicked = asyncio.Event()

    async def sink(self, data: bytes) -> None:
        self.data += data

    async def on_exit(self) -> None:
        self.exited.set()

    async def kick(self) -> None:
        self.kicked.set()


async def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timeout menunggu kondisi")
        await asyncio.sleep(0.02)


class PersistentTerminalTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.activity = 0

        def touch() -> None:
            self.activity += 1

        self.pt = PersistentTerminal(LocalShell("tidak-dipakai"), on_activity=touch)
        await self.pt.start()

    async def asyncTearDown(self) -> None:
        self.pt.close()
        await asyncio.sleep(0.05)

    async def test_shell_tetap_jalan_saat_ws_lepas_dan_replay_saat_kembali(self) -> None:
        first = Collector()
        self.pt.attach(first.sink, first.on_exit, first.kick)
        await self.pt.write(b"echo satu-$((1+1))\n")
        await wait_for(lambda: b"satu-2" in first.data)

        # WS putus (pindah menu/window): shell tetap jalan & output ditampung.
        self.pt.detach(first.sink)
        await self.pt.write(b"sleep 0.2; echo selagi-pergi-$((2+3))\n")
        await asyncio.sleep(0.6)
        self.assertTrue(self.pt.alive)
        self.assertNotIn(b"selagi-pergi-5", first.data)

        second = Collector()
        replay, previous = self.pt.attach(second.sink, second.on_exit, second.kick)
        self.assertIsNone(previous)
        self.assertIn(b"satu-2", replay)
        self.assertIn(b"selagi-pergi-5", replay)
        self.assertGreater(self.activity, 0)

    async def test_ws_baru_menggeser_ws_lama(self) -> None:
        old, new = Collector(), Collector()
        self.pt.attach(old.sink, old.on_exit, old.kick)
        _, previous = self.pt.attach(new.sink, new.on_exit, new.kick)
        self.assertIsNotNone(previous)
        await previous()
        self.assertTrue(old.kicked.is_set())

        await self.pt.write(b"echo hanya-baru-$((3+4))\n")
        await wait_for(lambda: b"hanya-baru-7" in new.data)
        self.assertNotIn(b"hanya-baru-7", old.data)
        # Detach WS lama tidak boleh melepas WS baru.
        self.pt.detach(old.sink)
        await self.pt.write(b"echo masih-$((4+4))\n")
        await wait_for(lambda: b"masih-8" in new.data)

    async def test_exit_menutup_ws_dan_menandai_mati(self) -> None:
        c = Collector()
        self.pt.attach(c.sink, c.on_exit, c.kick)
        await self.pt.write(b"exit\n")
        await asyncio.wait_for(c.exited.wait(), 5)
        self.assertFalse(self.pt.alive)

    async def test_close_menghentikan_shell(self) -> None:
        c = Collector()
        self.pt.attach(c.sink, c.on_exit, c.kick)
        proc = self.pt.term.proc
        self.pt.close()
        await asyncio.wait_for(c.exited.wait(), 5)
        await asyncio.wait_for(proc.wait(), 5)
        self.assertFalse(self.pt.alive)
        # close berulang aman.
        self.pt.close()


if __name__ == "__main__":
    main()
