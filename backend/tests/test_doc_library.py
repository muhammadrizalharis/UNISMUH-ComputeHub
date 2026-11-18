"""Uji helper Tanya Dokumen (tanpa Qdrant/DB)."""

import os
import time

from app.services import doc_library as dl


def test_safe_filename_strips_path_and_control_chars():
    assert dl.safe_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert dl.safe_filename("C:\\Users\\a\\Skripsi Bab 1.docx") == "Skripsi Bab 1.docx"
    assert "\x00" not in dl.safe_filename("a\x00b.txt")
    assert dl.safe_filename("...pdf") != ""
    assert dl.safe_filename("") == "dokumen"


def test_safe_filename_keeps_extension_when_truncated():
    out = dl.safe_filename("x" * 400 + ".pdf")
    assert out.endswith(".pdf") and len(out) <= 150


def test_unique_path_adds_suffix(tmp_path):
    assert dl.unique_path(tmp_path, "a.pdf") == tmp_path / "a.pdf"
    (tmp_path / "a.pdf").write_text("x")
    assert dl.unique_path(tmp_path, "a.pdf") == tmp_path / "a (2).pdf"
    (tmp_path / "a (2).pdf").write_text("x")
    assert dl.unique_path(tmp_path, "a.pdf") == tmp_path / "a (3).pdf"


def test_scan_skips_hidden_unsupported_symlink_and_cleans_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "folder", lambda uid: tmp_path)
    monkeypatch.setattr(dl, "folder_ok", lambda uid: True)
    (tmp_path / "ok.txt").write_text("halo")
    (tmp_path / "gambar.exe").write_text("x")
    (tmp_path / ".rahasia.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "link.txt").symlink_to(tmp_path / "ok.txt")
    fresh = tmp_path / ".aaaa.unggah"
    fresh.write_text("x")
    stale = tmp_path / ".bbbb.unggah"
    stale.write_text("x")
    old = time.time() - 2 * 24 * 3600
    os.utime(stale, (old, old))

    found = dl._scan(1)
    assert set(found) == {"ok.txt"}
    assert found["ok.txt"][0] == 4
    assert fresh.exists() and not stale.exists()


def test_scan_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "folder", lambda uid: tmp_path / "tidak-ada")
    assert dl._scan(1) == {}


def test_format_context_numbers_and_budget(monkeypatch):
    monkeypatch.setattr(dl.settings, "DOCS_LIBRARY_CONTEXT_CHARS", 1000)
    hits = [
        {"doc_id": 1, "name": "a.pdf", "section": "Bab 1", "text": "x" * 400},
        {"doc_id": 2, "name": "b.pdf", "section": "", "text": "y" * 400},
        {"doc_id": 3, "name": "c.pdf", "section": "", "text": "z" * 400},
    ]
    ctx, src = dl.format_context(hits)
    assert ctx.startswith("[D1] (a.pdf › Bab 1)\n")
    assert "[D2] (b.pdf)\n" in ctx and "[D3]" not in ctx
    assert [s["n"] for s in src] == [1, 2] and src[1]["doc_id"] == 2


def test_format_context_always_keeps_first_hit(monkeypatch):
    monkeypatch.setattr(dl.settings, "DOCS_LIBRARY_CONTEXT_CHARS", 1000)
    ctx, src = dl.format_context([{"doc_id": 9, "name": "n", "text": "q" * 5000}])
    assert len(src) == 1 and "[D1]" in ctx


def test_point_id_is_stable_and_distinct():
    assert dl._point_id(1, 0) == dl._point_id(1, 0)
    assert dl._point_id(1, 0) != dl._point_id(1, 1) != dl._point_id(2, 0)


def _fake_root(tmp_path, monkeypatch):
    root = tmp_path / "u1"
    root.mkdir()
    monkeypatch.setattr(dl.workspace_svc, "user_root", lambda uid: root)
    return root


def test_folder_ok_rejects_symlinked_folder(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch)
    other = tmp_path / "u2" / "Dokumen-AI"
    other.mkdir(parents=True)
    (root / "Dokumen-AI").symlink_to(other)
    assert dl.folder_ok(1) is False
    (other / "rahasia.txt").write_text("x")
    assert dl._scan(1) == {}
    assert dl.safe_file(1, "rahasia.txt") is None


def test_safe_file_rejects_symlink_and_traversal(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch)
    d = root / "Dokumen-AI"
    d.mkdir()
    (d / "ok.txt").write_text("x")
    secret = tmp_path / "rahasia.txt"
    secret.write_text("x")
    (d / "link.txt").symlink_to(secret)
    assert dl.folder_ok(1) is True
    assert dl.safe_file(1, "ok.txt") == d / "ok.txt"
    assert dl.safe_file(1, "link.txt") is None
    assert dl.safe_file(1, "../rahasia.txt") is None
    assert dl.safe_file(1, "..") is None


def test_library_chat_request_converts_to_assistant_request():
    from app.api.routers.assistant_library import to_chat_request
    from app.schemas.assistant import LibraryChatRequest

    req = to_chat_request(
        LibraryChatRequest(
            messages=[{"role": "user", "content": "halo"}, {"role": "assistant", "content": "hai"}],
            doc_ids=[1, 2],
        )
    )
    assert [(m.role, m.content) for m in req.messages] == [("user", "halo"), ("assistant", "hai")]
