"""Pinjam kantong VRAM oleh project Docker Compose (otomatis + pinjam di muka)."""

import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from app.services import vram_borrow, vram_pocket

CID_DOC = "a" * 64
CID_OTHER = "b" * 64
META = {
    CID_DOC: {"name": "local-ai-docling", "project": "local-ai", "service": "docling",
              "working_dir": "/home/ical/local-ai"},
    CID_OTHER: {"name": "orang-lain", "project": "lain", "service": "x", "working_dir": ""},
}
PID_CID = {101: CID_DOC, 102: CID_OTHER, 103: None}


class _Base(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.p_dir = patch.object(vram_pocket, "base_dir", return_value=Path(self.tmp.name))
        self.p_dir.start()
        self.p_cid = patch(
            "app.services.container_identity.container_id_for_pid", side_effect=PID_CID.get
        )
        self.p_cid.start()
        self.p_meta = patch("app.services.container_identity.lookup", side_effect=META.get)
        self.p_meta.start()
        self.p_notify = patch.object(vram_borrow, "_notify")
        self.p_notify.start()
        vram_borrow._reset_for_tests()

    def tearDown(self) -> None:
        for p in (self.p_dir, self.p_cid, self.p_meta, self.p_notify):
            p.stop()
        vram_borrow._reset_for_tests()
        self.tmp.cleanup()


class AutoBorrowTests(_Base):
    PROCS = [(1, 101, 1400.0), (1, 102, 5000.0), (0, 103, 900.0)]

    def test_tanpa_peminjam_tak_ada_yang_dihitung(self) -> None:
        vram_borrow.scan(self.PROCS, now=0)
        self.assertEqual(vram_borrow.used_mb(1), 0.0)
        self.assertEqual(vram_borrow.holders(1), 0)

    def test_hanya_container_project_terdaftar(self) -> None:
        vram_borrow.set_projects(["local-ai"], "admin")
        vram_borrow.scan(self.PROCS, now=0)
        self.assertEqual(vram_borrow.used_mb(1), 1400.0)
        self.assertEqual(vram_borrow.holders(1), 1)
        self.assertEqual(vram_borrow.used_mb(0), 0.0)
        st = vram_borrow.status()["projects"][0]
        self.assertEqual(st["owner"], "ical")
        self.assertEqual(st["containers"], ["local-ai-docling"])

    def test_vram_nol_kembali_ke_kantong(self) -> None:
        vram_borrow.set_projects(["local-ai"], "admin")
        vram_borrow.scan(self.PROCS, now=0)
        vram_borrow.scan([], now=2)
        self.assertEqual(vram_borrow.used_mb(1), 0.0)
        self.assertEqual(vram_borrow.holders(1), 0)

    def test_nama_project_tidak_valid_dibuang(self) -> None:
        got = vram_borrow.set_projects(["Local-AI", "../x", "", "ok_1"], "admin")
        self.assertEqual(got, ["local-ai", "ok_1"])

    def test_pocket_view_menambah_peminjam(self) -> None:
        vram_borrow.set_projects(["local-ai"], "admin")
        vram_borrow.scan(self.PROCS, now=0)

        class G:
            def __init__(self, i):
                self.index, self.mem_total_mb, self.mem_used_mb = i, 46000.0, 8000.0

        with patch("app.services.gpu.list_gpus", return_value=[G(0), G(1)]), \
                patch.object(vram_pocket, "held_map", return_value={}):
            views = {v.index: v for v in vram_pocket._views()}
        self.assertEqual(views[1].ch_used_mb, 1400.0)
        self.assertEqual(views[1].ch_holders, 1)
        self.assertEqual(views[0].ch_used_mb, 0.0)


class LeaseTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        vram_borrow.set_projects(["local-ai"], "admin")

    def test_pinjam_di_muka_dihitung_terbesar(self) -> None:
        vram_borrow.borrow("local-ai", 8000, 1, "local-ai-docling")
        self.assertEqual(vram_borrow.used_mb(1), 8000.0)
        vram_borrow.scan([(1, 101, 9000.0)], now=1e9)
        self.assertEqual(vram_borrow.used_mb(1), 9000.0)

    def test_project_bukan_peminjam_ditolak(self) -> None:
        with self.assertRaises(PermissionError):
            vram_borrow.borrow("lain", 1000, 0, "x")

    def test_kembali_otomatis_setelah_diam(self) -> None:
        lease = vram_borrow.borrow("local-ai", 4000, 1, "x")
        t0 = lease.created
        vram_borrow.scan([(1, 101, 3000.0)], now=t0 + 5)
        vram_borrow.scan([], now=t0 + 10)
        self.assertEqual(vram_borrow.used_mb(1), 4000.0)  # masih dalam masa diam
        vram_borrow.scan([], now=t0 + 10 + vram_borrow.IDLE_RETURN_SECONDS + 1)
        self.assertEqual(vram_borrow.used_mb(1), 0.0)

    def test_tanpa_batas_waktu_selama_dipakai(self) -> None:
        lease = vram_borrow.borrow("local-ai", 4000, 1, "x")
        for h in range(1, 48):
            vram_borrow.scan([(1, 101, 3000.0)], now=lease.created + h * 3600)
        self.assertEqual(vram_borrow.used_mb(1), 4000.0)

    def test_tak_pernah_dipakai_kembali_setelah_tenggang(self) -> None:
        lease = vram_borrow.borrow("local-ai", 4000, 1, "x")
        vram_borrow.scan([], now=lease.created + vram_borrow.START_GRACE_SECONDS - 1)
        self.assertEqual(vram_borrow.used_mb(1), 4000.0)
        vram_borrow.scan([], now=lease.created + vram_borrow.START_GRACE_SECONDS + 1)
        self.assertEqual(vram_borrow.used_mb(1), 0.0)

    def test_dikembalikan_manual(self) -> None:
        vram_borrow.borrow("local-ai", 4000, 1, "x")
        self.assertEqual(vram_borrow.give_back("local-ai"), 1)
        self.assertEqual(vram_borrow.used_mb(1), 0.0)

    def test_hapus_peminjam_membatalkan_pinjaman(self) -> None:
        vram_borrow.borrow("local-ai", 4000, 1, "x")
        vram_borrow.set_projects([], "admin")
        self.assertEqual(vram_borrow.used_mb(1), 0.0)


if __name__ == "__main__":
    main()
