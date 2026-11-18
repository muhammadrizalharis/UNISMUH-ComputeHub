import unittest
from unittest import mock

from app.services import container_identity as ci

CID = "f6168f4439b330b7364c6f3608e5d4b8df21c588adc9ba2c26386db6e078d83b"


class ContainerIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        ci._cache = {}
        ci._loaded_at = -1e9

    def _cgroup(self, text):
        return mock.patch("builtins.open", mock.mock_open(read_data=text))

    def test_cgroup_pola(self) -> None:
        for text in (
            f"0::/../docker-{CID}.scope\n",
            f"0::/system.slice/docker-{CID}.scope\n",
            f"12:memory:/docker/{CID}\n",
        ):
            with self.subTest(text=text), self._cgroup(text):
                self.assertEqual(ci.container_id_for_pid(123), CID)
        with self._cgroup("0::/user.slice/user-1015.slice/session-3.scope\n"):
            self.assertIsNone(ci.container_id_for_pid(123))

    def test_label_compose_dan_cache(self) -> None:
        items = [{"Id": CID, "Names": ["/local-ai-docling"],
                  "Labels": {"com.docker.compose.project": "local-ai",
                             "com.docker.compose.service": "docling"}}]
        with self._cgroup(f"0::/../docker-{CID}.scope\n"), \
             mock.patch.object(ci, "_fetch_containers", return_value=items) as f:
            info = ci.for_pid(1)
            ci.for_pid(1)
        self.assertEqual(info["label"], "Docker / local-ai / docling")
        self.assertEqual(info["name"], "local-ai-docling")
        self.assertEqual(f.call_count, 1)

    def test_tanpa_compose_dan_docker_mati(self) -> None:
        self.assertEqual(ci.workload_label({"name": "web", "project": "", "service": ""}), "Docker / web")
        with self._cgroup(f"0::/../docker-{CID}.scope\n"), \
             mock.patch.object(ci, "_fetch_containers", side_effect=OSError("down")):
            self.assertEqual(ci.for_pid(1)["label"], ci.UNAVAILABLE_LABEL)


class SystemdUnitDanLabelTests(unittest.TestCase):
    def test_unit_dari_cgroup(self) -> None:
        f = ci._unit_from_cgroup
        self.assertEqual(f("0::/system.slice/system-comfyui.slice/comfyui@0.service\n"),
                         {"name": "comfyui@0", "user": False})
        self.assertEqual(
            f("0::/user.slice/user-1003.slice/user@1003.service/app.slice/revisi-backend.service\n"),
            {"name": "revisi-backend", "user": True},
        )
        self.assertEqual(f("0::/system.slice/system-postfix.slice/postfix@-.service\n")["name"], "postfix")
        for text in ("0::/system.slice/cron.service\n", "0::/user.slice/user-1002.slice/session-29.scope\n",
                     "0::/user.slice/user-1003.slice/user@1003.service/init.scope\n", "0::/init.scope\n"):
            with self.subTest(text=text):
                self.assertIsNone(f(text))

    def test_label_workload_semua_user(self) -> None:
        from app.services import report

        def run(cmd, cgroup, name="python3"):
            with mock.patch.object(ci, "_read_cgroup", return_value=cgroup):
                return report._workload_for(1, cmd, name)[0]["label"]

        self.assertEqual(
            run("/venv/bin/python /venv/bin/uvicorn server:app --port 8772", "0::/system.slice/ai-f5tts.service\n"),
            "API / Web server (server:app) · service ai-f5tts",
        )
        self.assertEqual(
            run("next-server (v16.4.1)", "0::/user.slice/user-1015.slice/user@1015.service/app.slice/web.service\n", "node"),
            "Node / Frontend (Next.js v16.4.1) · service user web",
        )
        self.assertEqual(run("/usr/sbin/nginx -g daemon", "0::/system.slice/nginx.service\n", "nginx"),
                         "Service sistem (nginx)")
        self.assertEqual(run("python3 x.py", "0::/user.slice/user-1.slice/session-2.scope\n"), "Skrip Python (x.py)")


if __name__ == "__main__":
    unittest.main()
