"""Uji TensorBoard per pengguna (tanpa Docker): validasi path, pencarian log, argv, tiket."""

import asyncio
import time

import pytest

from app.api.routers import tensorboard_web as web
from app.services import tensorboard as tb


def _event(folder, name="events.out.tfevents.1.host"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"x")


def test_normalize_rel_accepts_persist_prefix_and_rejects_traversal():
    assert tb.normalize_rel("") == ""
    assert tb.normalize_rel("/persist/runs/exp1/") == "runs/exp1"
    assert tb.normalize_rel("/persist") == ""
    assert tb.normalize_rel("persisted/x") == "persisted/x"
    assert tb.normalize_rel("/persisted/x") == "persisted/x"
    assert tb.normalize_rel("./a//b") == "a/b"
    for bad in ("../x", "a/../../b", "a\x00b", "a\nb"):
        with pytest.raises(ValueError):
            tb.normalize_rel(bad)


def test_check_folder_rejects_symlink_and_missing(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "runs")
    assert tb.check_folder(tmp_path, "runs") == tmp_path / "runs"
    with pytest.raises(ValueError):
        tb.check_folder(tmp_path, "link")
    with pytest.raises(ValueError):
        tb.check_folder(tmp_path, "link/sub")
    with pytest.raises(ValueError):
        tb.check_folder(tmp_path, "tidak-ada")


def test_find_runs_skips_hidden_trash_and_symlinks(tmp_path):
    _event(tmp_path / "runs" / "exp1")
    _event(tmp_path / "lightning_logs" / "version_0")
    _event(tmp_path / ".trash" / "lama")
    _event(tmp_path / "node_modules" / "x")
    (tmp_path / "pintas").symlink_to(tmp_path / "runs")
    (tmp_path / "runs" / "exp2").mkdir()
    (tmp_path / "runs" / "exp2" / "catatan.txt").write_text("bukan log")
    hasil = tb.find_runs(tmp_path)
    paths = {r["path"] for r in hasil["runs"]}
    assert paths == {"runs/exp1", "lightning_logs/version_0"}
    assert hasil["truncated"] is False
    sub = tb.find_runs(tmp_path, "runs")
    assert [r["path"] for r in sub["runs"]] == ["runs/exp1"]


def test_find_runs_root_level_events(tmp_path):
    _event(tmp_path)
    assert tb.find_runs(tmp_path)["runs"][0]["path"] == ""


def test_run_argv_is_readonly_cpu_only_and_prefixed(tmp_path):
    argv = tb.TensorboardManager().run_argv(7, tmp_path, "job:3", "runs/a")
    s = " ".join(argv)
    assert f"{tmp_path}:/logs:ro" in s
    assert "--read-only" in argv
    assert "--gpus" not in argv and "--runtime" not in argv
    assert "--logdir /logs/runs/a" in s
    assert f"--path_prefix {tb.path_prefix()}/7" in s
    assert "--name ch-tb-7" in s
    assert "--memory" in argv and "--cpus" in argv and "--pids-limit" in argv


def test_ticket_single_use_and_owner_bound():
    t = web.make_ticket(5, "sid-a")
    assert web.consume_ticket(t, 6) is None
    assert web.consume_ticket(t, 5)["sid"] == "sid-a"
    assert web.consume_ticket(t, 5) is None


def test_session_cookie_bound_to_owner_and_type():
    c = web.make_session_cookie(5, "sid-a")
    assert web.verify_session_cookie(c, 5)["uid"] == 5
    assert web.verify_session_cookie(c, 6) is None
    # Tiket bukan cookie sesi (tipe berbeda).
    assert web.verify_session_cookie(web.make_ticket(5, "sid-a"), 5) is None
    assert web.cookie_path(5) == f"{tb.path_prefix()}/5"


def test_upstream_headers_drop_credentials():
    out = dict(web.upstream_headers([
        ("Cookie", "ch_tensorboard=abc; access=xyz"),
        ("Authorization", "Bearer x"),
        ("Accept", "application/json"),
        ("Connection", "keep-alive"),
    ]))
    assert out == {"Accept": "application/json"}


def test_reap_idle_stops_only_stale(monkeypatch):
    m = tb.TensorboardManager()
    now = time.time()
    m._inst[1] = tb.TbInstance(1, "persist", "", "10.0.0.1", now, now - 3600)
    m._inst[2] = tb.TbInstance(2, "persist", "", "10.0.0.2", now, now - 10)
    stopped: list[int] = []

    async def fake_shutdown(uid, locked=False):
        stopped.append(uid)
        m._inst.pop(uid, None)
        return True

    monkeypatch.setattr(m, "shutdown", fake_shutdown)
    assert asyncio.run(m.reap_idle(now)) == [1]
    assert stopped == [1]
    assert m.target(2) == ("10.0.0.2", tb.settings.TENSORBOARD_PORT)
    assert m.target(1) is None
    assert m.status(1)["running"] is False
