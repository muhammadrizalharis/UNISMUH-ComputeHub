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


GIB = 1024 ** 3
RUN = "/run/systemd/system.control/"
ETC = "/etc/systemd/system.control/"
LIB = "/usr/lib/systemd/system/user-.slice.d/10-defaults.conf"


def show(unit: str, description: str, *dropins: str) -> str:
    return f"Id={unit}\nDescription={description}\nDropInPaths={' '.join((LIB, *dropins))}\n"


class LinuxWriteTests(IsolatedAsyncioTestCase):
    """Semua interaksi systemd dipalsukan: uji ini TIDAK menyentuh host."""

    def setUp(self) -> None:
        self.calls: list[list[str]] = []
        self.show_output = show("user-1016.slice", "User Slice of UID 1016")

        async def fake_run_host(cmd: list[str]) -> str:
            self.calls.append(cmd)
            return self.show_output if cmd[:3] == ["systemctl", "--no-pager", "show"] else ""

        override = patch.object(linux_limits, "_run_host", fake_run_host)
        override.start()
        self.addCleanup(override.stop)

    def writes(self) -> list[list[str]]:
        return [c for c in self.calls if c[:3] != ["systemctl", "--no-pager", "show"]]

    def test_validate_bounds_and_units(self) -> None:
        props = linux_limits.validate_request(
            {"cpu_cores": 2.5, "memory_max_bytes": 8 * GIB, "memory_high_bytes": None},
            total_memory_bytes=256 * GIB, cpu_count=64,
        )
        self.assertEqual(props, {"CPUQuota": "250%", "MemoryMax": str(8 * GIB), "MemoryHigh": ""})
        for bad in (
            {"cpu_cores": 0},
            {"cpu_cores": 65},
            {"cpu_cores": True},
            {"cpu_cores": float("nan")},
            {"memory_max_bytes": 1024},
            {"memory_max_bytes": 257 * GIB},
            {"memory_high_bytes": 8 * GIB, "memory_max_bytes": 4 * GIB},
            {"tasks": 10},
            {"vram_mb": 1024},
            {},
        ):
            with self.subTest(bad=bad), self.assertRaises(linux_limits.LinuxLimitError):
                linux_limits.validate_request(bad, total_memory_bytes=256 * GIB, cpu_count=64)

    def test_classify_from_systemctl_output(self) -> None:
        # Kasus nyata akbar404: drop-in permanen IT + bawaan distro.
        info = linux_limits.classify_dropins(show("user-1013.slice", "User Slice of UID 1013", ETC + "user-1013.slice.d/50-MemoryMax.conf"))
        self.assertEqual(info, {"managed": [], "runtime_other": [], "permanent": [ETC + "user-1013.slice.d/50-MemoryMax.conf"]})
        # Runtime tanpa penanda = dipasang orang lain.
        info = linux_limits.classify_dropins(show("user-1016.slice", "User Slice of UID 1016", RUN + "user-1016.slice.d/50-CPUQuota.conf"))
        self.assertEqual(info["runtime_other"], [RUN + "user-1016.slice.d/50-CPUQuota.conf"])
        # Runtime + Description berpenanda = milik ComputeHub; permanen tetap terpisah.
        info = linux_limits.classify_dropins(show(
            "user-1016.slice", "User Slice of UID 1016 [computehub-managed]",
            RUN + "user-1016.slice.d/50-Description.conf", RUN + "user-1016.slice.d/50-CPUQuota.conf", ETC + "user-1016.slice.d/50-MemoryMax.conf",
        ))
        self.assertEqual(len(info["managed"]), 2)
        self.assertEqual(info["permanent"], [ETC + "user-1016.slice.d/50-MemoryMax.conf"])

    async def test_apply_refuses_to_override_it_rules(self) -> None:
        self.show_output = show("user-1013.slice", "User Slice of UID 1013", ETC + "user-1013.slice.d/50-MemoryMax.conf")
        with self.assertRaises(linux_limits.LinuxLimitError) as ctx:
            await linux_limits.apply_runtime_limits(1013, "akbar404", {"cpu_cores": 2})
        self.assertIn("50-MemoryMax.conf", str(ctx.exception))
        self.assertEqual(self.writes(), [])

    async def test_apply_refuses_foreign_runtime_dropin(self) -> None:
        self.show_output = show("user-1016.slice", "User Slice of UID 1016", RUN + "user-1016.slice.d/50-CPUQuota.conf")
        with self.assertRaises(linux_limits.LinuxLimitError):
            await linux_limits.apply_runtime_limits(1016, "qa", {"cpu_cores": 2})
        self.assertEqual(self.writes(), [])

    async def test_apply_marks_then_sets_runtime_only(self) -> None:
        with patch.object(linux_limits.os, "cpu_count", return_value=64):
            result = await linux_limits.apply_runtime_limits(1016, "qa", {"cpu_cores": 2, "memory_max_bytes": 8 * GIB})
        writes = self.writes()
        self.assertEqual(len(writes), 2)
        for call in writes:
            self.assertEqual(call[:5], ["systemctl", "--no-pager", "--runtime", "set-property", "user-1016.slice"])
        self.assertIn("computehub-managed", writes[0][5])
        self.assertEqual(set(writes[1][5:]), {"CPUQuota=200%", f"MemoryMax={8 * GIB}"})
        self.assertEqual(result["properties"], {"CPUQuota": "200%", "MemoryMax": str(8 * GIB)})

    async def test_apply_rejects_invalid_uid(self) -> None:
        for uid in (0, 999, True, "1016"):
            with self.subTest(uid=uid), self.assertRaises(linux_limits.LinuxLimitError):
                await linux_limits.apply_runtime_limits(uid, "x", {"cpu_cores": 1})  # type: ignore[arg-type]

    async def test_revert_only_touches_computehub_dropins_and_never_uses_systemctl_revert(self) -> None:
        self.show_output = show(
            "user-1016.slice", "User Slice of UID 1016 [computehub-managed]",
            RUN + "user-1016.slice.d/50-Description.conf", RUN + "user-1016.slice.d/50-CPUQuota.conf",
            ETC + "user-1016.slice.d/50-MemoryMax.conf",  # milik IT
        )
        result = await linux_limits.revert_runtime_limits(1016)
        writes = self.writes()
        self.assertEqual(writes[0][:5], ["systemctl", "--no-pager", "--runtime", "set-property", "user-1016.slice"])
        self.assertEqual(set(writes[0][5:]), {"CPUQuota=", "Description="})  # MemoryMax milik IT TIDAK disentuh
        self.assertEqual(writes[1], ["rm", "-rf", RUN + "user-1016.slice.d"])
        self.assertEqual(writes[2], ["systemctl", "--no-pager", "daemon-reload"])
        self.assertFalse(any("revert" in c for c in self.calls))
        self.assertEqual(sorted(result["removed"]), ["50-CPUQuota.conf", "50-Description.conf"])

    async def test_revert_without_our_dropins_is_noop(self) -> None:
        result = await linux_limits.revert_runtime_limits(1016)
        self.assertEqual(result["removed"], [])
        self.assertEqual(self.writes(), [])

    async def test_host_exec_only_allows_runtime_unit_dir_removal(self) -> None:
        for bad in (["rm", "-rf", "/etc/systemd/system.control/user-1013.slice.d"], ["rm", "-rf", "/run/systemd/system.control"],
                    ["rm", "-rf", "/run/systemd/system.control/user-1016.slice.d/.."], ["cat", "/etc/shadow"], ["rm", "-rf", "/"]):
            with self.subTest(bad=bad), self.assertRaises(linux_limits.LinuxLimitError):
                await linux_limits._host_exec(bad)
        self.assertEqual(self.calls, [])
        await linux_limits._host_exec(["rm", "-rf", RUN + "user-1016.slice.d"])
        self.assertEqual(len(self.calls), 1)

    async def test_ownership_map_batches_and_tolerates_failure(self) -> None:
        self.show_output = (
            show("user-1013.slice", "User Slice of UID 1013", ETC + "user-1013.slice.d/50-MemoryMax.conf")
            + "\n" + show("user-1016.slice", "x [computehub-managed]", RUN + "user-1016.slice.d/50-CPUQuota.conf")
        )
        own = await linux_limits._ownership_map([1013, 1016])
        self.assertEqual(own[1013], {"by_computehub": False, "external": ["50-MemoryMax.conf"]})
        self.assertEqual(own[1016], {"by_computehub": True, "external": []})
        self.assertEqual(len(self.calls), 1)
        with patch.object(linux_limits, "_systemctl", AsyncMock(side_effect=linux_limits.LinuxLimitError("x"))):
            self.assertEqual(await linux_limits._ownership_map([1013]), {})

    def test_write_helper_has_minimal_rights(self) -> None:
        with patch.object(settings, "DOCKER_CMD", "/usr/bin/docker"):
            argv = linux_limits._helper_argv("ch-x", ["systemctl", "--no-pager", "daemon-reload"])
        self.assertNotIn("--privileged", argv)
        self.assertNotIn("--mount", argv)
        self.assertNotIn("-v", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertIn("--read-only", argv)
        self.assertIn("--pull=never", argv)
        caps = [argv[i + 1] for i, v in enumerate(argv) if v == "--cap-add"]
        self.assertEqual(sorted(caps), ["SYS_ADMIN", "SYS_CHROOT", "SYS_PTRACE"])
        self.assertEqual(argv[-3:], ["systemctl", "--no-pager", "daemon-reload"])


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