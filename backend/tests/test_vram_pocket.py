"""Kantong VRAM: pembagian target per GPU, lepas-duluan, dan konfigurasi admin."""

import json
import tempfile
import time
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from app.services import vram_pocket
from app.services.vram_pocket import GpuView, compute_targets

KW = {"buffer_mb": 3072.0, "keep_free_mb": 2048.0, "chunk_mb": 512.0}


def _v(i, used, held=0.0, ch=0.0, holders=0, total=46000.0):
    return GpuView(index=i, total_mb=total, used_mb=used, held_mb=held,
                   ch_used_mb=ch, ch_holders=holders)


class ComputeTargetsTests(TestCase):
    def test_mati_semua_nol(self) -> None:
        out = compute_targets([_v(0, 1000), _v(1, 1000)], 16384, False, **KW)
        self.assertEqual({i: t["target_mb"] for i, t in out.items()}, {0: 0.0, 1: 0.0})

    def test_dibagi_rata_bila_kedua_gpu_lega(self) -> None:
        out = compute_targets([_v(0, 1000), _v(1, 1000)], 16384, True, **KW)
        self.assertEqual(out[0]["target_mb"], 8192.0)
        self.assertEqual(out[1]["target_mb"], 8192.0)
        self.assertEqual(out[0]["min_free_mb"], 2048.0)

    def test_gpu_sesak_dialihkan_ke_gpu_lain(self) -> None:
        # GPU0: 41 GB dipakai pengguna lain -> kapasitas 46000-41000-2048 = 2952 MB.
        out = compute_targets([_v(0, 41000), _v(1, 1000)], 16384, True, **KW)
        self.assertAlmostEqual(out[0]["share_mb"], 2952.0, places=0)
        self.assertAlmostEqual(out[0]["share_mb"] + out[1]["share_mb"], 16384.0, places=0)
        self.assertEqual(out[0]["target_mb"], 2560.0)  # dibulatkan ke potongan 512 MB

    def test_pegangan_sendiri_tak_dianggap_milik_orang_lain(self) -> None:
        # GPU0 tampak 41 GB terpakai, tetapi 8 GB di antaranya pegangan kantong sendiri.
        out = compute_targets([_v(0, 41000, held=8192), _v(1, 1000)], 16384, True, **KW)
        self.assertEqual(out[0]["target_mb"], 8192.0)

    def test_pemakaian_user_computehub_mengurangi_pegangan_dan_jaga_buffer(self) -> None:
        out = compute_targets(
            [_v(0, 10000, held=3000, ch=5000, holders=1), _v(1, 1000)], 16384, True, **KW
        )
        self.assertEqual(out[0]["target_mb"], 3072.0)  # 8192 - 5000 -> potongan 512
        self.assertEqual(out[0]["min_free_mb"], 3072.0)  # GPU ditempati -> buffer
        self.assertEqual(out[1]["min_free_mb"], 2048.0)

    def test_kantong_terpakai_habis_target_nol(self) -> None:
        out = compute_targets([_v(0, 15000, ch=12000, holders=1)], 8192, True, **KW)
        self.assertEqual(out[0]["target_mb"], 0.0)

    def test_tidak_ada_kapasitas_sama_sekali(self) -> None:
        out = compute_targets([_v(0, 45000), _v(1, 45000)], 16384, True, **KW)
        self.assertEqual(out[0]["target_mb"], 0.0)
        self.assertEqual(out[1]["target_mb"], 0.0)


class ConfigFileTests(TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        p = patch.object(vram_pocket, "base_dir", lambda: self.tmp)
        p.start()
        self.addCleanup(p.stop)
        r = patch.object(vram_pocket, "_views", lambda: [_v(0, 1000), _v(1, 1000)])
        r.start()
        self.addCleanup(r.stop)

    def test_toggle_dan_ukuran_tertulis_ke_target(self) -> None:
        cfg = vram_pocket.get_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.size_mb, 16384.0)
        vram_pocket.set_config(False, None, "admin@x")
        target = json.loads((self.tmp / "target.json").read_text())
        self.assertFalse(target["enabled"])
        self.assertEqual(target["targets_mb"], {"0": 0.0, "1": 0.0})
        vram_pocket.set_config(True, 4096.0, "admin@x")
        target = json.loads((self.tmp / "target.json").read_text())
        self.assertTrue(target["enabled"])
        self.assertEqual(target["targets_mb"], {"0": 2048.0, "1": 2048.0})
        self.assertEqual(vram_pocket.get_config().updated_by, "admin@x")

    def test_status_daemon_basi_dianggap_mati(self) -> None:
        (self.tmp / "status.json").write_text(
            json.dumps({"ts": time.time() - 999, "held_mb": {"0": 4096}})
        )
        self.assertIsNone(vram_pocket.daemon_status())
        self.assertEqual(vram_pocket.held_map(), {})
        (self.tmp / "status.json").write_text(
            json.dumps({"ts": time.time(), "held_mb": {"0": 4096}})
        )
        self.assertEqual(vram_pocket.held_map(), {0: 4096.0})
        st = vram_pocket.status()
        self.assertTrue(st["daemon_alive"])
        self.assertEqual(len(st["gpus"]), 2)


class SchedulerWaitTests(TestCase):
    def test_lama_menunggu(self) -> None:
        import datetime as dt

        from app.services import scheduler

        self.assertEqual(scheduler._waited(None), 0.0)
        naive = dt.datetime.utcnow() - dt.timedelta(seconds=700)
        self.assertGreaterEqual(scheduler._waited(naive), 699)
        aware = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=30)
        self.assertLess(scheduler._waited(aware), 60)


if __name__ == "__main__":
    main()
