"""Uji integrasi layanan local-ai untuk Asisten AI: lampiran dokumen (Tika/Docling),
pencarian web (SearXNG/Crawl4AI), dan RAG bot Panduan (bge-m3 + Qdrant).

Semua panggilan jaringan dipalsukan (tanpa layanan nyata). Jalankan DALAM container app:
  docker exec -w <repo>/backend ComputeHub-app python -m pytest tests/test_assistant_localai.py -q
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

import httpx

from app.core.config import settings
from app.schemas.assistant import AssistantChatRequest
from app.services import assistant, doc_extract, help_rag, helpbot, web_search


def _run(coro):
    return asyncio.run(coro)


def _patch(**kw):
    return mock.patch.multiple(settings, **kw)


class DocExtractTests(unittest.TestCase):
    def test_clean_text_buang_escape_dan_entitas(self) -> None:
        raw = "\\> init compute\\_core \\[ OK \\]\r\n&#32; Gejala\n\n\n\nSolusi  "
        self.assertEqual(doc_extract.clean_text(raw), "> init compute_core [ OK ]\n  Gejala\n\nSolusi")

    def test_jenis_tidak_didukung(self) -> None:
        with self.assertRaises(doc_extract.ExtractError):
            _run(doc_extract.extract("virus.exe", b"MZ"))
        self.assertFalse(doc_extract.is_allowed("foto.png"))
        self.assertTrue(doc_extract.is_allowed("Laporan.PDF"))

    def test_batas_ukuran(self) -> None:
        with _patch(ASSISTANT_DOC_MAX_BYTES=10):
            with self.assertRaises(doc_extract.ExtractError):
                _run(doc_extract.extract("a.txt", b"x" * 11))

    def test_teks_biasa_tanpa_layanan(self) -> None:
        with _patch(ASSISTANT_TIKA_URL="", ASSISTANT_DOCLING_URL=""):
            r = _run(doc_extract.extract("data.csv", "a,b\n1,2\n".encode()))
        self.assertEqual((r.engine, r.text, r.truncated), ("teks", "a,b\n1,2", False))

    def test_pdf_pindaian_jatuh_ke_docling(self) -> None:
        async def tika(data, mime, **_):
            return "  \n"

        async def docling(data, name, **_):
            return "# Judul\n\nIsi hasil OCR " * 20

        with _patch(ASSISTANT_TIKA_URL="http://t", ASSISTANT_DOCLING_URL="http://d"), \
                mock.patch.object(doc_extract, "_tika", tika), \
                mock.patch.object(doc_extract, "_docling", docling):
            r = _run(doc_extract.extract("scan.pdf", b"%PDF"))
        self.assertEqual(r.engine, "docling")
        self.assertIn("Isi hasil OCR", r.text)

    def test_tika_cukup_docling_tidak_dipanggil(self) -> None:
        dipanggil = []

        async def tika(data, mime, **_):
            return "Isi dokumen yang panjang. " * 20

        async def docling(data, name, **_):
            dipanggil.append(name)
            return ""

        with _patch(ASSISTANT_TIKA_URL="http://t", ASSISTANT_DOCLING_URL="http://d"), \
                mock.patch.object(doc_extract, "_tika", tika), \
                mock.patch.object(doc_extract, "_docling", docling):
            r = _run(doc_extract.extract("a.docx", b"PK"))
        self.assertEqual((r.engine, dipanggil), ("tika", []))

    def test_tika_mati_tanpa_docling_pesan_ramah(self) -> None:
        async def tika(data, mime, **_):
            raise httpx.ConnectError("mati")

        with _patch(ASSISTANT_TIKA_URL="http://t", ASSISTANT_DOCLING_URL=""), \
                mock.patch.object(doc_extract, "_tika", tika):
            with self.assertRaises(doc_extract.ExtractError):
                _run(doc_extract.extract("a.pdf", b"%PDF"))


class WebSearchTests(unittest.TestCase):
    def test_build_query_buang_kode_dan_kata_tanya(self) -> None:
        q = web_search.build_query(
            "Kenapa muncul error `CUDA out of memory` di YOLO?\n```python\nrahasia = 1\n```"
        )
        self.assertNotIn("rahasia", q)
        self.assertNotIn("Kenapa", q)
        self.assertIn("CUDA out of memory", q)
        self.assertLessEqual(len(web_search.build_query("kata " * 200)), 200)

    def _fake_client(self, payload: dict):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        real = httpx.AsyncClient

        def factory(*a, **kw):
            kw.pop("timeout", None)
            return real(transport=httpx.MockTransport(handler))

        return mock.patch.object(web_search.httpx, "AsyncClient", factory)

    def test_search_saring_hasil_tak_relevan_dan_url_aneh(self) -> None:
        payload = {"results": [
            {"title": "All About Google", "url": "https://x.example/g", "content": "mesin cari"},
            {"title": "CUDA out of memory YOLO fix", "url": "https://a.example/1", "content": "batch"},
            {"title": "CUDA memory error", "url": "javascript:alert(1)", "content": "yolo"},
            {"title": "Tips YOLO memory", "url": "https://b.example/2", "content": "CUDA"},
            {"title": "CUDA out of memory YOLO fix", "url": "https://a.example/1", "content": ""},
        ]}
        with _patch(ASSISTANT_SEARXNG_URL="http://s"), self._fake_client(payload):
            src = _run(web_search.search("CUDA out of memory YOLO", 5))
        self.assertEqual([s.url for s in src], ["https://a.example/1", "https://b.example/2"])
        self.assertEqual([s.n for s in src], [1, 2])

    def test_format_context_patuh_anggaran(self) -> None:
        src = [web_search.Source(i, f"Judul {i}", f"https://e/{i}", content="x" * 5000) for i in (1, 2)]
        out = web_search.format_context(src, 3000)
        self.assertLessEqual(len(out), 3000)
        self.assertIn("[1] Judul 1", out)

    def test_compact_buang_navigasi_simpan_kode(self) -> None:
        md = "[Home](/) | [Docs](/d)\n![logo](x.png)\npip install torch\nIsi jawaban penting."
        self.assertEqual(web_search._compact(md, 1000), "pip install torch\nIsi jawaban penting.")

    def test_gather_gagal_tetap_aman(self) -> None:
        async def boom(q, n):
            raise httpx.ConnectError("mati")

        with _patch(ASSISTANT_SEARXNG_URL="http://s"), mock.patch.object(web_search, "search", boom):
            ctx = _run(web_search.gather("error torch"))
        self.assertEqual((ctx.sources, ctx.text), ([], ""))


class BuildMessagesTests(unittest.TestCase):
    def _req(self, **kw) -> AssistantChatRequest:
        return AssistantChatRequest(**kw)

    def test_dokumen_disisipkan_dan_anggaran_utamakan_terbaru(self) -> None:
        req = self._req(messages=[
            {"role": "user", "content": "baca ini", "documents": [{"name": "lama.pdf", "text": "L" * 80}]},
            {"role": "assistant", "content": "oke"},
            {"role": "user", "content": "dan ini", "documents": [{"name": "baru.docx", "text": "B" * 80}]},
        ])
        with _patch(ASSISTANT_DOC_MAX_CHARS=100):
            msgs = assistant._build_messages(req, system_override="SYS")
        users = [m["content"] for m in msgs if m["role"] == "user"]
        self.assertIn("«baru.docx»", users[1])
        self.assertIn("B" * 80, users[1])
        self.assertTrue(users[1].endswith("dan ini"))
        self.assertIn("DIPOTONG", users[0])
        self.assertIn("L" * 20, users[0])
        self.assertNotIn("L" * 21, users[0])

    def test_lampiran_lama_tanpa_sisa_anggaran(self) -> None:
        req = self._req(messages=[
            {"role": "user", "content": "", "documents": [{"name": "a.pdf", "text": "A" * 50}]},
            {"role": "user", "content": "q", "documents": [{"name": "b.pdf", "text": "B" * 50}]},
        ])
        with _patch(ASSISTANT_DOC_MAX_CHARS=50):
            msgs = assistant._build_messages(req, system_override="SYS")
        self.assertIn("tidak disertakan lagi", msgs[1]["content"])

    def test_web_context_masuk_pesan_terakhir(self) -> None:
        req = self._req(messages=[{"role": "user", "content": "apa itu YOLO"}])
        msgs = assistant._build_messages(req, system_override="SYS", web_context="[1] YOLO\nURL: https://e")
        self.assertIn("HASIL PENCARIAN WEB", msgs[-1]["content"])
        self.assertTrue(msgs[-1]["content"].endswith("apa itu YOLO"))

    def test_status_memuat_flag_fitur(self) -> None:
        with _patch(ASSISTANT_TIKA_URL="http://t", ASSISTANT_DOCLING_URL="", ASSISTANT_SEARXNG_URL=""):
            st = assistant.status("m")
        self.assertTrue(st["documents"])
        self.assertFalse(st["web_search"])


class HelpRagTests(unittest.TestCase):
    TEKS = (
        "U N I S M U H\n\nPengantar singkat panduan ini untuk mahasiswa baru.\n"
        "1 Masuk ke ComputeHub\nLogin memakai SSO kampus atau username CH dari admin lab.\n\n"
        "2 Dashboard & kuota GPU harian\nKuota GPU harian 6 jam dihitung ulang tiap tengah malam."
        + " Kalimat tambahan." * 80
    )

    def test_chunk_mengikuti_judul_bagian(self) -> None:
        chunks = help_rag.chunk_text("panduan.pdf", self.TEKS, size=300)
        sections = [c.section for c in chunks]
        self.assertIn("1 Masuk ke ComputeHub", sections)
        self.assertIn("2 Dashboard & kuota GPU harian", sections)
        self.assertTrue(all(len(c.text) <= 300 for c in chunks))
        login = next(c for c in chunks if c.section == "1 Masuk ke ComputeHub")
        self.assertIn("SSO", login.text)
        self.assertNotIn("Kuota", login.text)

    def test_id_titik_stabil_berbasis_isi(self) -> None:
        a = help_rag.Chunk("x", "s", "isi")
        self.assertEqual(a.point_id, help_rag.Chunk("x", "s2", "isi").point_id)
        self.assertNotEqual(a.point_id, help_rag.Chunk("x", "s", "isi lain").point_id)

    def test_retrieve_nonaktif_kosong(self) -> None:
        with _patch(HELP_RAG_QDRANT_URL="", HELP_RAG_EMBED_URL=""):
            self.assertEqual(_run(help_rag.retrieve("kuota")), [])

    def test_retrieve_gagal_jaringan_kosong(self) -> None:
        async def boom(client, texts):
            raise httpx.ConnectError("mati")

        with _patch(HELP_RAG_QDRANT_URL="http://q", HELP_RAG_EMBED_URL="http://e"), \
                mock.patch.object(help_rag, "embed", boom):
            self.assertEqual(_run(help_rag.retrieve("kuota")), [])

    def test_prompt_panduan_dengan_kutipan(self) -> None:
        self.assertEqual(helpbot.system_prompt(""), helpbot.SYSTEM_PROMPT)
        ex = help_rag.format_excerpts([{"source": "p.pdf", "section": "2 Kuota", "text": "6 jam"}])
        p = helpbot.system_prompt(ex)
        self.assertIn("KUTIPAN DOKUMEN PANDUAN", p)
        self.assertIn("[1] (p.pdf › 2 Kuota)\n6 jam", p)


if __name__ == "__main__":
    unittest.main()
