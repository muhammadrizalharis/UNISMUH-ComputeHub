import os
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from app.core.config import settings
from app.services import devbox


class SeedCopilotSkillsTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src = root / "skills-src"
        self.persist = root / "persist"
        self.persist.mkdir()
        skill = self.src / "sitasi-mendeley"
        (skill / "scripts").mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: sitasi-mendeley\n---\nisi\n")
        (skill / "scripts" / "mendeleyfy.py").write_text("print('hai')\n")
        os.chmod(skill / "scripts" / "mendeleyfy.py", 0o755)
        (skill / "__pycache__").mkdir()
        (skill / "__pycache__" / "x.pyc").write_bytes(b"x")
        (skill / ".rahasia").write_text("x")
        (self.src / "bukan-skill").mkdir()
        (self.src / "bukan-skill" / "README.md").write_text("x")
        self.dst = self.persist / ".copilot" / "skills" / "sitasi-mendeley"
        self._p = patch.object(settings, "DEVBOX_COPILOT_SKILLS_DIR", str(self.src))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def seed(self):
        return devbox._seed_copilot_skills(7, self.persist)

    def test_copies_skill_and_skips_cache_hidden_and_non_skill(self):
        self.assertEqual(self.seed(), ["sitasi-mendeley"])
        self.assertTrue((self.dst / "SKILL.md").is_file())
        script = self.dst / "scripts" / "mendeleyfy.py"
        self.assertEqual(script.read_text(), "print('hai')\n")
        self.assertTrue(os.access(script, os.X_OK))
        self.assertFalse((self.dst / "__pycache__").exists())
        self.assertFalse((self.dst / ".rahasia").exists())
        self.assertFalse((self.persist / ".copilot" / "skills" / "bukan-skill").exists())
        self.assertEqual([p.name for p in self.dst.iterdir() if p.name.endswith(".tmp")], [])

    def test_idempotent_and_overwrites_only_changed(self):
        self.seed()
        (self.dst / "catatan-user.md").write_text("milik user")
        self.assertEqual(self.seed(), [])
        (self.dst / "SKILL.md").write_text("diubah user")
        self.assertEqual(self.seed(), ["sitasi-mendeley"])
        self.assertIn("name: sitasi-mendeley", (self.dst / "SKILL.md").read_text())
        self.assertEqual((self.dst / "catatan-user.md").read_text(), "milik user")

    def test_refuses_symlinked_copilot_dir(self):
        luar = Path(self._tmp.name) / "milik-orang-lain"
        luar.mkdir()
        (self.persist / ".copilot").symlink_to(luar)
        self.assertEqual(self.seed(), [])
        self.assertEqual(list(luar.iterdir()), [])

    def test_refuses_symlinked_skills_dir_and_target_file(self):
        luar = Path(self._tmp.name) / "luar"
        luar.mkdir()
        (self.persist / ".copilot").mkdir()
        (self.persist / ".copilot" / "skills").symlink_to(luar)
        self.assertEqual(self.seed(), [])
        self.assertEqual(list(luar.iterdir()), [])
        (self.persist / ".copilot" / "skills").unlink()
        self.dst.mkdir(parents=True)
        korban = luar / "korban.txt"
        korban.write_text("asli")
        (self.dst / "SKILL.md").symlink_to(korban)
        self.seed()
        self.assertEqual(korban.read_text(), "asli")

    def test_skips_oversize_file(self):
        with patch.object(devbox, "_SKILL_MAX_BYTES", 10):
            self.seed()
        self.assertFalse((self.dst / "SKILL.md").exists())

    def test_disabled_or_missing_source_is_noop(self):
        with patch.object(settings, "DEVBOX_COPILOT_SKILLS_DIR", ""):
            self.assertEqual(self.seed(), [])
        with patch.object(settings, "DEVBOX_COPILOT_SKILLS_DIR", str(self.src / "tidak-ada")):
            self.assertEqual(self.seed(), [])
        self.assertFalse((self.persist / ".copilot").exists())

    def test_prepare_dirs_never_fails_when_seeding_raises(self):
        mgr = devbox.DevboxManager.__new__(devbox.DevboxManager)
        with (
            patch.object(devbox, "home_dir", return_value=Path(self._tmp.name) / "home"),
            patch.object(devbox, "web_enabled", return_value=False),
            patch.object(devbox, "ssh_enabled", return_value=False),
            patch.object(settings, "DEVBOX_SEED_SERVER", False),
            patch.object(devbox.workspace_svc, "ensure_root", return_value=self.persist),
            patch.object(devbox, "_seed_copilot_skills", side_effect=RuntimeError("boom")),
        ):
            _home, persist = mgr._prepare_dirs(7)
        self.assertEqual(persist, self.persist)


if __name__ == "__main__":
    main()
