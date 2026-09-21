import asyncio
import os
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase, main, skipUnless
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services import devbox


def connection_event(connection_id: str, message: str) -> str:
    return f"2026-09-20 00:00:00.000 [info] [<unknown>][{connection_id}][ManagementConnection] {message}\n"


class ConnectedClientsTests(TestCase):
    def test_graceful_disconnect(self) -> None:
        lines = [connection_event("client-a", "New connection established.")]
        self.assertEqual(devbox._connected_clients(lines), 1)
        lines.append(connection_event(
            "client-a",
            "The client has disconnected gracefully, so the connection will be disposed.",
        ))
        self.assertEqual(devbox._connected_clients(lines), 0)

    def test_network_disconnect_and_reconnect(self) -> None:
        lines = [
            connection_event("client-a", "New connection established."),
            connection_event(
                "client-a",
                "The client has disconnected, will wait for reconnection 3h before disposing...",
            ),
        ]
        self.assertEqual(devbox._connected_clients(lines), 0)
        lines.append(connection_event("client-a", "The client has reconnected."))
        self.assertEqual(devbox._connected_clients(lines), 1)

    def test_other_window_remains_connected(self) -> None:
        lines = [
            connection_event("client-a", "New connection established."),
            connection_event("client-b", "New connection established."),
            connection_event(
                "client-a",
                "The client has disconnected gracefully, so the connection will be disposed.",
            ),
            connection_event(
                "client-a",
                "The reconnection short grace time of 5m has expired, so the connection will be disposed.",
            ),
        ]
        self.assertEqual(devbox._connected_clients(lines), 1)

    def test_missing_or_unknown_events_are_not_a_disconnect(self) -> None:
        self.assertIsNone(devbox._connected_clients([]))
        self.assertIsNone(devbox._connected_clients([
            "[ExtensionHostConnection] New connection established.",
            connection_event("client-a", "Unknown future event."),
        ]))


class ConnectionLogTests(TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = patch.object(settings, "DEVBOX_HOME_ROOT", str(self.root))
        override.start()
        self.addCleanup(override.stop)
        self.logs = self.root / "24" / "server" / "data" / "logs"

    def write_log(self, folder: str, text: str, name: str = "remoteagent.log") -> Path:
        target = self.logs / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def test_old_container_log_is_ignored(self) -> None:
        target = self.write_log("20260919T100000", connection_event(
            "client-a", "The client has disconnected gracefully, so the connection will be disposed.",
        ))
        os.utime(target, (10, 10))
        self.assertIsNone(devbox._read_client_connection(24, 20))

    def test_latest_server_log_and_rotations(self) -> None:
        self.write_log("20260919T100000", connection_event("old-client", "New connection established."))
        self.write_log("20260920T100000", connection_event("client-a", "New connection established."), "remoteagent.1.log")
        self.write_log("20260920T100000", connection_event("client-b", "New connection established.") + connection_event(
            "client-b", "The client has disconnected gracefully, so the connection will be disposed.",
        ))
        self.assertTrue(devbox._read_client_connection(24, 0))
        self.write_log("20260920T100000", connection_event(
            "client-a", "The client has disconnected gracefully, so the connection will be disposed.",
        ))
        self.assertFalse(devbox._read_client_connection(24, 0))

    def test_missing_or_unreadable_log_is_unknown(self) -> None:
        self.assertIsNone(devbox._read_client_connection(24, 0))
        self.write_log("20260920T100000", connection_event("client-a", "New connection established."))
        with patch.object(Path, "open", side_effect=PermissionError("unreadable")):
            self.assertIsNone(devbox._read_client_connection(24, 0))

    def test_web_server_log_counts_too(self) -> None:
        """Jalur browser (server-web) & tunnel (server) dijumlahkan: satu masih
        tersambung di mana pun = devbox tidak dianggap terputus."""
        web = self.root / "24" / "server-web" / "data" / "logs" / "20260921T100000" / "remoteagent.log"
        web.parent.mkdir(parents=True)
        web.write_text(connection_event("browser", "New connection established."), encoding="utf-8")
        self.assertTrue(devbox._read_client_connection(24, 0))
        self.write_log("20260921T090000", connection_event("desktop", "New connection established.")
                       + connection_event("desktop", "The client has disconnected, will wait for reconnection 3h before disposing..."))
        self.assertTrue(devbox._read_client_connection(24, 0))
        web.write_text(
            connection_event("browser", "New connection established.")
            + connection_event("browser", "The client has disconnected gracefully, so the connection will be disposed."),
            encoding="utf-8",
        )
        self.assertFalse(devbox._read_client_connection(24, 0))


class WebAccessTests(TestCase):
    """Tiket sekali-pakai -> cookie sesi IDE; hanya pemilik; header proxy bersih."""

    def setUp(self) -> None:
        from app.api.routers import devbox_web

        self.web = devbox_web
        devbox_web._used_tickets.clear()

    def test_ticket_is_single_use_and_owner_bound(self) -> None:
        ticket = self.web.make_ticket(24, "sid-24")
        self.assertIsNone(self.web.consume_ticket(ticket, 25), "tiket user lain harus ditolak")
        claims = self.web.consume_ticket(ticket, 24)
        self.assertEqual((claims["uid"], claims["sid"]), (24, "sid-24"))
        self.assertIsNone(self.web.consume_ticket(ticket, 24), "tiket tidak boleh dipakai dua kali")

    def test_session_cookie_is_not_a_ticket_and_vice_versa(self) -> None:
        cookie = self.web.make_session_cookie(24, "sid-24")
        self.assertEqual(self.web.verify_session_cookie(cookie, 24)["uid"], 24)
        self.assertIsNone(self.web.verify_session_cookie(cookie, 25))
        self.assertIsNone(self.web.consume_ticket(cookie, 24), "cookie sesi bukan tiket")
        self.assertIsNone(self.web.verify_session_cookie(self.web.make_ticket(24, "s"), 24))
        self.assertIsNone(self.web.verify_session_cookie("bukan.jwt.sah", 24))
        with patch.object(settings, "SECRET_KEY", "kunci-lain"):
            self.assertIsNone(self.web.verify_session_cookie(cookie, 24), "tanda tangan salah")

    def test_upstream_headers_strip_hop_by_hop_and_swap_cookies(self) -> None:
        out = dict(self.web.build_upstream_headers(
            [("Host", "computehub.lab"), ("Connection", "keep-alive"), ("Upgrade", "websocket"),
             ("Cookie", "ch_devbox_web=rahasia; vscode-tkn=basi; lain=1"), ("Accept", "*/*")],
            token="TOKEN", host="computehub.lab", scheme="https", client_ip="10.0.0.1",
        ))
        self.assertNotIn("Host", out)
        self.assertNotIn("Connection", out)
        self.assertNotIn("Upgrade", out)
        self.assertEqual(out["cookie"], "lain=1; vscode-tkn=TOKEN")
        self.assertEqual(out["x-forwarded-proto"], "https")
        self.assertEqual(out["Accept"], "*/*")

    def test_response_headers_drop_upstream_token_cookie(self) -> None:
        import httpx

        headers = httpx.Headers([
            ("set-cookie", "vscode-tkn=TOKEN; Max-Age=604800; SameSite=Lax"),
            ("set-cookie", "vscode-cli-secret-half=abc; HttpOnly; Path=/"),
            ("transfer-encoding", "chunked"), ("content-type", "text/html"),
        ])
        out = self.web.filter_response_headers(headers)
        self.assertEqual([v for k, v in out if k == "set-cookie"], ["vscode-cli-secret-half=abc; HttpOnly; Path=/"])
        self.assertNotIn("transfer-encoding", [k for k, _ in out])
        self.assertIn(("content-type", "text/html"), out)

    def test_web_base_path_and_cookie_path(self) -> None:
        self.assertEqual(devbox.web_base_path(19), "/devbox-ide/19/")
        self.assertEqual(self.web.cookie_path(19), "/devbox-ide/19")
        with patch.object(settings, "DEVBOX_WEB_PATH", "ide/"):
            self.assertEqual(devbox.web_base_path(7), "/ide/7/")


class WebTokenTests(TestCase):
    def test_token_file_is_reused_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first = devbox._ensure_web_token(home)
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(oct((home / "web.token").stat().st_mode & 0o777), "0o600")
            self.assertEqual(devbox._ensure_web_token(home), first, "token tetap setelah backend restart")
            (home / "web.token").write_text("pendek", encoding="utf-8")
            self.assertNotEqual(devbox._ensure_web_token(home), "pendek", "token tak sah diganti")


class DesktopSetupTests(TestCase):
    """Kunci SSH + pemasang sekali-klik (user tidak menyentuh konfigurasi apa pun)."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        override = patch.object(settings, "DEVBOX_HOME_ROOT", temporary.name)
        override.start()
        self.addCleanup(override.stop)
        self.uid = 4242

    def test_key_is_private_and_rotation_revokes_old(self) -> None:
        from app.services import devbox_keys

        priv1, pub1 = devbox_keys.generate(self.uid)
        self.assertTrue(priv1.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"))
        self.assertTrue(pub1.startswith("ssh-ed25519 "))
        self.assertEqual(
            oct(devbox_keys.private_path(self.uid).stat().st_mode & 0o777), "0o600"
        )
        self.assertEqual(devbox_keys.ensure(self.uid), pub1, "kunci yang ada dipakai ulang")
        priv2, pub2 = devbox_keys.generate(self.uid)
        self.assertNotEqual(priv1, priv2)
        self.assertNotEqual(pub1, pub2)
        self.assertEqual(
            devbox_keys.public_path(self.uid).read_text().strip(), pub2,
            "hanya kunci terbaru yang tersimpan -> laptop lama kehilangan akses",
        )

    def test_sshd_config_menolak_password_dan_root(self) -> None:
        home = devbox.home_dir(self.uid)
        home.mkdir(parents=True, exist_ok=True)
        devbox._prepare_ssh(self.uid, home, 1015, 1015, "CH-uji")
        conf = (home / "ssh" / "sshd_config").read_text()
        for wajib in (
            "PasswordAuthentication no",
            "PermitRootLogin no",
            "UsePAM no",
            "AuthorizedKeysFile /home/dev/ssh/authorized_keys",
            "SetEnv HOME=/CH-uji",
        ):
            self.assertIn(wajib, conf)
        auth = home / "ssh" / "authorized_keys"
        self.assertEqual(oct(auth.stat().st_mode & 0o777), "0o600")
        self.assertTrue(auth.read_text().startswith("ssh-ed25519 "))
        self.assertTrue((home / "ssh" / "ssh_host_ed25519_key").is_file())
        # Dipanggil ulang (rotasi kunci): host key TIDAK berubah supaya klien tidak
        # menuduh server berganti identitas.
        sidik = (home / "ssh" / "ssh_host_ed25519_key").read_bytes()
        devbox._prepare_ssh(self.uid, home, 1015, 1015, "CH-uji")
        self.assertEqual((home / "ssh" / "ssh_host_ed25519_key").read_bytes(), sidik)

    def test_pemasang_memuat_kunci_config_dan_proxy(self) -> None:
        from app.services import devbox_keys, devbox_setup

        priv, _ = devbox_keys.generate(self.uid)
        alias = devbox.ssh_host_alias(self.uid)
        for teks, penanda in (
            (devbox_setup.build_windows(self.uid, alias, priv, "TOK", "CH-uji"), "powershell"),
            (devbox_setup.build_unix(self.uid, alias, priv, "TOK", "CH-uji"), "python3"),
        ):
            self.assertIn(priv.strip().splitlines()[1], teks, "kunci privat ikut dalam pemasang")
            self.assertIn(f"Host {alias}", teks)
            self.assertIn("IdentitiesOnly yes", teks)
            self.assertIn("ProxyCommand", teks)
            self.assertIn("TOK", teks)
            self.assertIn(penanda, teks.lower())
            self.assertIn("ComputeHub devbox", teks, "blok config ditandai -> aman ditulis ulang")
            self.assertNotIn("devbox-ide", teks, "pemasang hanya untuk jalur SSH")
        # Pemasang Windows harus siap dobel-klik: dibungkus batch & ASCII murni.
        win = devbox_setup.build_windows(self.uid, alias, priv, "TOK", "CH-uji")
        self.assertTrue(win.startswith("@echo off"))
        self.assertIn("#PSSTART", win)
        self.assertTrue(win.isascii(), "cmd.exe tidak bisa diandalkan membaca non-ASCII")
        # Platform host diset -> VS Code tidak menanyakan Linux/Windows saat connect.
        self.assertIn("remote.SSH.remotePlatform", win)
        unix = devbox_setup.build_unix(self.uid, alias, priv, "TOK", "CH-uji")
        self.assertIn("devbox_vscode_platform.py", unix)

    def test_token_ssh_terikat_pemilik_dan_kunci(self) -> None:
        from app.api.routers import devbox_ssh
        from app.services import devbox_keys

        devbox_keys.generate(self.uid)
        token = devbox_ssh.make_token(self.uid, devbox_keys.fingerprint(self.uid))
        self.assertIsNotNone(devbox_ssh.verify_token(token, self.uid))
        self.assertIsNone(devbox_ssh.verify_token(token, self.uid + 1), "milik user lain")
        self.assertIsNone(devbox_ssh.verify_token("bukan.jwt", self.uid))
        with patch.object(settings, "SECRET_KEY", "kunci-lain"):
            self.assertIsNone(devbox_ssh.verify_token(token, self.uid), "tanda tangan salah")
        devbox_keys.generate(self.uid)  # "laptop hilang" -> kunci & token lama dicabut
        self.assertIsNone(devbox_ssh.verify_token(token, self.uid), "token lama harus mati")


class DisconnectReaperTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = devbox.DevboxManager()
        self.box = devbox.Devbox(user_id=24, gpu_index=0, state=devbox.STATE_RUNNING)
        self.manager._boxes[24] = self.box
        self.manager._stop_and_notify = AsyncMock()
        override = patch.object(settings, "DEVBOX_DISCONNECT_TIMEOUT_SECONDS", 120)
        override.start()
        self.addCleanup(override.stop)
        audit = patch.object(devbox, "_audit")
        audit.start()
        self.addCleanup(audit.stop)

    async def test_docker_nanosecond_timestamp_is_supported(self) -> None:
        stamp = "2026-09-19T09:13:39.762603759Z\n"
        with (
            patch.object(devbox, "_run", AsyncMock(return_value=(0, stamp))),
            patch.object(devbox, "_read_client_connection", return_value=True) as read_connection,
        ):
            self.assertTrue(await self.manager._client_connected(self.box))
            read_connection.assert_called_once()

    async def test_sesi_ssh_aktif_menahan_penghentian(self) -> None:
        """Remote-SSH tidak menulis remoteagent.log yang dibaca reaper; tanpa hitungan
        sesi proxy, devbox milik pemakai VS Code Desktop akan dimatikan saat bekerja."""
        devbox.ssh_session_open(self.box.user_id)
        self.addCleanup(devbox.ssh_session_close, self.box.user_id)
        with (
            patch.object(devbox, "_run", AsyncMock(return_value=(0, "x"))) as run,
            patch.object(devbox, "_read_client_connection", return_value=False) as read_connection,
        ):
            self.assertTrue(await self.manager._client_connected(self.box))
            read_connection.assert_not_called()
            run.assert_not_called()

        devbox.ssh_session_close(self.box.user_id)
        self.assertEqual(devbox.ssh_sessions(self.box.user_id), 0)
        stamp = "2026-09-19T09:13:39.762603759Z\n"
        with (
            patch.object(devbox, "_run", AsyncMock(return_value=(0, stamp))),
            patch.object(devbox, "_read_client_connection", return_value=False),
        ):
            self.assertFalse(await self.manager._client_connected(self.box))

    async def test_stop_only_after_grace(self) -> None:
        self.assertFalse(await self.manager._reap_disconnected(self.box, False, 100))
        self.assertFalse(await self.manager._reap_disconnected(self.box, False, 219))
        self.assertTrue(await self.manager._reap_disconnected(self.box, False, 220))
        self.manager._stop_and_notify.assert_awaited_once()
        self.assertIn("koneksi VS Code terputus", self.manager._stop_and_notify.call_args.args[1])

    async def test_reconnect_cancels_countdown(self) -> None:
        await self.manager._reap_disconnected(self.box, False, 100)
        self.assertFalse(await self.manager._reap_disconnected(self.box, True, 219))
        self.assertIsNone(self.box._disconnected_at)
        self.assertFalse(await self.manager._reap_disconnected(self.box, False, 220))
        self.manager._stop_and_notify.assert_not_awaited()

    async def test_unknown_state_never_causes_shutdown(self) -> None:
        await self.manager._reap_disconnected(self.box, False, 100)
        self.assertFalse(await self.manager._reap_disconnected(self.box, None, 300))
        self.assertFalse(await self.manager._reap_disconnected(self.box, False, 301))
        self.manager._stop_and_notify.assert_not_awaited()

    async def test_disabled_setting(self) -> None:
        with patch.object(settings, "DEVBOX_DISCONNECT_TIMEOUT_SECONDS", 0):
            await self.manager._reap_disconnected(self.box, False, 100)
            self.assertFalse(await self.manager._reap_disconnected(self.box, False, 1000))
        self.manager._stop_and_notify.assert_not_awaited()

    async def test_reaper_stops_despite_busy_cpu_and_gpu(self) -> None:
        self.box.client_connected = False
        self.box._disconnected_at = 100
        with (
            patch.object(devbox.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])),
            patch.object(devbox.time, "time", return_value=220),
            patch.object(self.manager, "_cpu_percent", AsyncMock(return_value={self.box.container: 99})),
            patch.object(self.manager, "_gpu_busy", AsyncMock(return_value=True)),
            patch.object(self.manager, "_quota_habis", AsyncMock(return_value=False)),
            patch.object(self.manager, "_is_container_running", AsyncMock(return_value=True)),
            patch.object(self.manager, "_client_connected", AsyncMock(return_value=False)),
            patch.object(devbox, "_adopt_jobs", AsyncMock()),
            patch.object(self.manager, "_sweep_stale", AsyncMock()),
        ):
            await self.manager._reap_loop()
        self.manager._stop_and_notify.assert_awaited_once()

    async def test_failed_docker_stop_keeps_reservation_and_session(self) -> None:
        with (
            patch.object(devbox, "_run", AsyncMock(return_value=(1, "Docker unavailable"))),
            patch.object(self.manager, "_forget", AsyncMock()) as forget,
        ):
            with self.assertRaises(devbox.DevboxError):
                await self.manager.shutdown_user(24)
            forget.assert_not_awaited()
        self.assertIs(self.manager._boxes[24], self.box)

    async def test_stop_happens_before_release_without_delete(self) -> None:
        calls: list[str] = []

        async def stop_container(argv: list[str], **kwargs) -> tuple[int, str]:
            self.assertIn("stop", argv)
            self.assertNotIn("rm", argv)
            calls.append("stop")
            return 0, self.box.container

        async def forget_box(*args) -> None:
            calls.append("release")

        with (
            patch.object(devbox, "_run", side_effect=stop_container),
            patch.object(self.manager, "_forget", side_effect=forget_box),
        ):
            self.assertTrue(await self.manager.shutdown_user(24))
        self.assertEqual(calls, ["stop", "release"])


@skipUnless(os.environ.get("CH_DEVBOX_DOCKER_SMOKE") == "1", "Docker smoke test is opt-in")
class DockerDisconnectSmokeTests(IsolatedAsyncioTestCase):
    async def test_container_stops_without_losing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            persist = root / "persist"
            persist.mkdir()
            sentinel = persist / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            with (
                patch.object(settings, "DEVBOX_HOME_ROOT", str(root / "homes")),
                patch.object(settings, "DEVBOX_DISCONNECT_TIMEOUT_SECONDS", 120),
                patch.object(devbox, "CONTAINER_PREFIX", "ch-qa-disconnect-"),
                patch.object(devbox, "_audit"),
                patch.object(devbox, "_kirim_notifikasi", AsyncMock()) as notify,
            ):
                box = devbox.Devbox(user_id=os.getpid(), state=devbox.STATE_RUNNING)
                manager = devbox.DevboxManager()
                claim = f"devbox:{box.user_id}"
                rc, container_id = await devbox._run(devbox._docker_argv(
                    "create", "--pull=never", "--name", box.container,
                    "--label", "computehub.test=devbox-auto-stop",
                    "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--memory", "128m", "--cpus", "0.25",
                    "-v", f"{persist}:/persist:ro", "busybox",
                    "httpd", "-f", "-p", "8080", "-h", "/persist",
                ))
                self.assertEqual(rc, 0, container_id)
                container_id = container_id.strip()
                try:
                    rc, output = await devbox._run(devbox._docker_argv("start", container_id))
                    self.assertEqual(rc, 0, output)
                    manager._boxes[box.user_id] = box
                    devbox.reservations.reserve(claim, 0, 512, kind="interactive")
                    log = devbox.home_dir(box.user_id) / "server/data/logs/20260920T000000/remoteagent.log"
                    log.parent.mkdir(parents=True)
                    log.write_text(connection_event("client-a", "New connection established."), encoding="utf-8")
                    self.assertTrue(await manager._client_connected(box))
                    with log.open("a", encoding="utf-8") as stream:
                        stream.write(connection_event(
                            "client-a",
                            "The client has disconnected gracefully, so the connection will be disposed.",
                        ))
                    connected = await manager._client_connected(box)
                    self.assertFalse(connected)
                    self.assertFalse(await manager._reap_disconnected(box, connected, 100))
                    self.assertTrue(await manager._is_container_running(box.container))
                    self.assertTrue(await manager._reap_disconnected(box, connected, 220))
                    rc, state = await devbox._run(devbox._docker_argv(
                        "inspect", "-f", "{{.Id}} {{.State.Status}}", box.container,
                    ))
                    self.assertEqual(rc, 0, state)
                    self.assertEqual(state.strip(), f"{container_id} exited")
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
                    self.assertNotIn(box.user_id, manager._boxes)
                    self.assertEqual(devbox.reservations.count(0), 0)
                    notify.assert_awaited_once()
                finally:
                    devbox.reservations.release(claim)
                    await devbox._run(devbox._docker_argv("rm", "-f", container_id))


if __name__ == "__main__":
    main()