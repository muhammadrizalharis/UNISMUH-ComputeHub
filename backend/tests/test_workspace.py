import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import workspace


class WorkspaceDirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ch-workspace-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        roots = patch.object(workspace, "user_root", side_effect=lambda user_id: self.base / str(user_id))
        roots.start()
        self.addCleanup(roots.stop)
        self.root = workspace.ensure_root(42)

    def test_large_folder_does_not_hide_sibling_project(self):
        dataset = self.root / "final_goal"
        dataset.mkdir()
        for number in range(4005):
            (dataset / f"sample-{number:05d}.txt").touch()
        project = self.root / "phd_project" / "code"
        project.mkdir(parents=True)
        (project / "analysis.py").write_text("print('ok')", encoding="utf-8")

        result = workspace.tree(42)
        self.assertEqual([child["name"] for child in result["children"]], ["final_goal", "phd_project"])
        self.assertTrue(all(child["children"] == [] for child in result["children"]))
        self.assertIsNone(result["next_offset"])

        names = []
        offset = 0
        while offset is not None:
            page = workspace.list_directory(42, "final_goal", offset=offset)
            self.assertLessEqual(len(page["children"]), 200)
            names.extend(child["name"] for child in page["children"])
            offset = page["next_offset"]
        self.assertEqual(names, [f"sample-{number:05d}.txt" for number in range(4005)])

        nested = workspace.list_directory(42, "phd_project/code")
        self.assertEqual(nested["children"][0]["path"], "phd_project/code/analysis.py")

    def test_root_directory_can_be_paged_without_losing_case_variants(self):
        for name in ("z.txt", "A.txt", "a.txt"):
            (self.root / name).touch()
        (self.root / "project").mkdir()
        names = []
        for offset in range(4):
            page = workspace.list_directory(42, offset=offset, limit=1)
            names.append(page["children"][0]["name"])
            self.assertEqual(page["next_offset"], offset + 1 if offset < 3 else None)
        self.assertEqual(names, ["project", "A.txt", "a.txt", "z.txt"])
        self.assertEqual(workspace.list_directory(42, offset=4)["children"], [])

    def test_hidden_directories_and_symlinks_remain_excluded(self):
        (self.root / ".cache").mkdir()
        (self.root / "visible").mkdir()
        (self.root / "outside").symlink_to(self.base, target_is_directory=True)
        (self.root / "broken").symlink_to(self.base / "missing")
        result = workspace.list_directory(42)
        self.assertEqual([child["name"] for child in result["children"]], ["visible"])

    def test_other_users_and_traversal_are_rejected(self):
        workspace.ensure_root(43)
        (self.root / "escape").symlink_to(self.base / "43", target_is_directory=True)
        for path in ("../43", "../../", str(self.base), "escape"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                workspace.list_directory(42, path)

    def test_missing_folder_and_invalid_pages_are_explicit_errors(self):
        with self.assertRaises(FileNotFoundError):
            workspace.list_directory(42, "missing")
        for arguments in ({"offset": -1}, {"limit": 0}, {"limit": 1001}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                workspace.list_directory(42, **arguments)

    def test_directory_endpoint_pages_and_rejects_invalid_paths(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.deps import get_current_active_user
        from app.api.routers.interactive import router

        application = FastAPI()
        application.include_router(router, prefix="/interactive")
        application.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=42)
        for name in ("one.txt", "two.txt"):
            (self.root / name).touch()
        with TestClient(application) as client:
            first = client.get("/interactive/workspace/directory", params={"limit": 1})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["children"][0]["name"], "one.txt")
            self.assertEqual(first.json()["next_offset"], 1)
            second = client.get("/interactive/workspace/directory", params={"offset": 1, "limit": 1})
            self.assertEqual(second.json()["children"][0]["name"], "two.txt")
            self.assertIsNone(second.json()["next_offset"])
            for parameters, expected in (
                ({"path": "../43"}, 400),
                ({"path": "missing"}, 404),
                ({"offset": -1}, 422),
                ({"limit": 1001}, 422),
            ):
                with self.subTest(parameters=parameters):
                    response = client.get("/interactive/workspace/directory", params=parameters)
                    self.assertEqual(response.status_code, expected)


if __name__ == "__main__":
    unittest.main()