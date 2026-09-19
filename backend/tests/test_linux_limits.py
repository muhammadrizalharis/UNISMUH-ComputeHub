import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase, main
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.schemas.admin import LinuxLimitsOut
from app.services import linux_limits


class LinuxLimitsTests(TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "cgroup.controllers").write_text("cpu memory pids cpuset")
        self.parent = self.root / "user.slice"
        self.group = self.parent / "user-1015.slice"
        self.group.mkdir(parents=True)
        for group in (self.parent, self.group):
            for resource in ("cpu.max", "memory.high", "memory.max", "pids.max"):
                (group / resource).write_text("max 100000" if resource == "cpu.max" else "max")

    def limits(self) -> dict:
        return linux_limits.collect_limits(self.root, [1015])["users"][0]

    def test_unlimited_is_distinct_from_missing(self) -> None:
        self.assertEqual(self.limits()["limits"]["cpu_cores"]["state"], "unlimited")
        (self.group / "cpu.max").unlink()
        self.assertEqual(self.limits()["limits"]["cpu_cores"]["state"], "unavailable")

    def test_disabled_child_controller_still_uses_parent_limit(self) -> None:
        (self.group / "cpu.max").unlink()
        (self.group / "cgroup.controllers").write_text("memory pids")
        (self.parent / "cpu.max").write_text("250000 100000")
        (self.parent / "cpuset.cpus.effective").write_text("0-7")
        account = self.limits()
        self.assertEqual(account["limits"]["cpu_cores"]["value"], 2.5)
        self.assertTrue(account["limits"]["cpu_cores"]["inherited"])
        self.assertEqual(account["allowed_cpus"], "0-7")
        (self.parent / "cpu.max").write_text("max 100000")
        self.assertEqual(self.limits()["limits"]["cpu_cores"]["state"], "unlimited")

    def test_enabled_controller_with_missing_file_is_unknown(self) -> None:
        (self.group / "cpu.max").unlink()
        (self.group / "cgroup.controllers").write_text("cpu memory pids")
        self.assertEqual(self.limits()["limits"]["cpu_cores"]["state"], "unavailable")

    def test_inherited_limit_is_effective_not_local(self) -> None:
        (self.parent / "cpu.max").write_text("150000 100000")
        (self.group / "cpu.max").write_text("400000 100000")
        limit = self.limits()["limits"]["cpu_cores"]
        self.assertEqual(limit["value"], 1.5)
        self.assertEqual(limit["local_value"], 4)
        self.assertEqual(limit["source"], "/user.slice")
        self.assertTrue(limit["inherited"])

    def test_system_changes_are_read_on_next_snapshot(self) -> None:
        (self.group / "memory.max").write_text("8589934592")
        self.assertEqual(self.limits()["limits"]["memory_max_bytes"]["value"], 8589934592)
        (self.group / "memory.max").write_text("17179869184")
        self.assertEqual(self.limits()["limits"]["memory_max_bytes"]["value"], 17179869184)

    def test_inactive_account_has_no_invented_defaults(self) -> None:
        account = linux_limits.collect_limits(self.root, [1016])["users"][0]
        self.assertFalse(account["active"])
        self.assertIsNone(account["limits"])

    def test_invalid_or_unreadable_parent_does_not_mean_unlimited(self) -> None:
        for text in ("invalid", "0 0", "-1000 100000"):
            with self.subTest(text=text):
                (self.parent / "cpu.max").write_text(text)
                self.assertEqual(self.limits()["limits"]["cpu_cores"]["state"], "unavailable")

    def test_memory_high_tasks_and_cpuset(self) -> None:
        (self.group / "memory.high").write_text("4294967296")
        (self.group / "pids.max").write_text("512")
        (self.group / "cpuset.cpus.effective").write_text("0-3,6")
        account = self.limits()
        self.assertEqual(account["limits"]["memory_high_bytes"]["value"], 4294967296)
        self.assertEqual(account["limits"]["tasks"]["value"], 512)
        self.assertEqual(account["allowed_cpus"], "0-3,6")

    def test_unsupported_system_and_invalid_uid(self) -> None:
        with self.assertRaises(ValueError):
            linux_limits.collect_limits(self.root, ["../system.slice"])
        (self.root / "cgroup.controllers").unlink()
        self.assertFalse(linux_limits.collect_limits(self.root, [1015])["available"])


class LinuxReaderTests(IsolatedAsyncioTestCase):
    def test_reader_has_only_readonly_host_mounts(self) -> None:
        with patch.object(settings, "DOCKER_CMD", "/usr/bin/docker"):
            argv = linux_limits._reader_argv([1015], "ch-linux-limits-test")
        self.assertIn("--read-only", argv)
        self.assertIn("--pull=never", argv)
        self.assertIn("no-new-privileges", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertEqual(argv[argv.index("--cap-drop") + 1], "ALL")
        mounts = [argv[index + 1] for index, value in enumerate(argv) if value == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all(mount.endswith(",readonly") for mount in mounts))
        self.assertNotIn("--privileged", argv)
        self.assertNotIn("--pid=host", argv)

    async def test_reader_result_and_process_error(self) -> None:
        proc = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(
            json.dumps({"available": True, "reason": None, "users": []}).encode(), b"",
        )))
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)) as run,
        ):
            self.assertTrue((await linux_limits._collect_host([1015]))["available"])
            self.assertNotIn("shell", run.call_args.kwargs)
            proc.returncode = 1
            with self.assertRaises(RuntimeError):
                await linux_limits._collect_host([1015])

    async def test_snapshot_cache_expires_and_never_persists_policy(self) -> None:
        account = SimpleNamespace(pw_uid=1015, pw_name="test-user")
        row = {"uid": 1015, "active": False, "cgroup": "/user.slice/user-1015.slice", "allowed_cpus": None, "limits": None}
        with (
            patch.object(linux_limits, "_cache", None),
            patch.object(linux_limits, "_cache_until", 0),
            patch.object(linux_limits, "_lock", asyncio.Lock()),
            patch.object(linux_limits.pwd, "getpwall", return_value=[account]),
            patch("app.services.report.is_human_user", return_value=True),
            patch.object(linux_limits, "_collect_host", AsyncMock(return_value={
                "available": True, "reason": None, "users": [row],
            })) as collect,
        ):
            first = LinuxLimitsOut.model_validate(await linux_limits.snapshot())
            self.assertTrue(first.read_only)
            self.assertEqual(first.users[0].username, "test-user")
            await linux_limits.snapshot()
            self.assertEqual(collect.await_count, 1)
            linux_limits._cache_until = 0
            await linux_limits.snapshot()
            self.assertEqual(collect.await_count, 2)

    async def test_reader_failure_is_not_unlimited(self) -> None:
        with (
            patch.object(linux_limits, "_cache", None),
            patch.object(linux_limits, "_cache_until", 0),
            patch.object(linux_limits, "_lock", asyncio.Lock()),
            patch.object(linux_limits.pwd, "getpwall", return_value=[]),
            patch.object(linux_limits, "_collect_host", AsyncMock(side_effect=RuntimeError("unavailable"))),
        ):
            result = LinuxLimitsOut.model_validate(await linux_limits.snapshot())
        self.assertFalse(result.available)
        self.assertEqual(result.reason, "reader_unavailable")
        self.assertEqual(result.users, [])

    def test_route_is_readonly_and_requires_admin(self) -> None:
        from app.api.deps import require_admin
        from app.api.routers.admin import router

        routes = [route for route in router.routes if route.path == "/linux-accounts/limits"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].methods, {"GET"})
        self.assertIn(require_admin, [dependency.call for dependency in routes[0].dependant.dependencies])


if __name__ == "__main__":
    main()