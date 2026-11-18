"""Simulasi perkiraan waktu mulai antrian (services/queue.simulate)."""

import math
import unittest

from app.services.queue import QueuedItem, RunningItem, simulate


class SimulateTest(unittest.TestCase):
    def test_slot_kosong_langsung_mulai(self):
        out = simulate(2, [], [QueuedItem(1, 10, 300), QueuedItem(2, 11, 300)])
        self.assertEqual([s.start_in for s in out], [0.0, 0.0])

    def test_menunggu_slot_tercepat(self):
        running = [RunningItem(1, 100), RunningItem(2, 400)]
        out = simulate(2, running, [QueuedItem(1, 10, 300), QueuedItem(2, 11, 50)])
        self.assertEqual([s.start_in for s in out], [100.0, 400.0])
        self.assertEqual([s.position for s in out], [1, 2])

    def test_sesi_interaktif_tidak_memakai_slot(self):
        running = [RunningItem(5, math.inf, batch=False)]
        out = simulate(1, running, [QueuedItem(1, 10, 300)])
        self.assertEqual(out[0].start_in, 0.0)

    def test_batas_job_bersamaan_pemilik(self):
        # User 10 maks 1 job: job keduanya menunggu job pertamanya selesai,
        # sementara job user lain boleh menyalip memakai slot bebas.
        q = [QueuedItem(1, 10, 300, user_limit=1), QueuedItem(2, 10, 300, user_limit=1),
             QueuedItem(3, 11, 300, user_limit=1)]
        out = simulate(3, [], q)
        self.assertEqual([s.start_in for s in out], [0.0, 300.0, 0.0])
        self.assertEqual([s.own_limit for s in out], [False, True, False])

    def test_pemilik_sedang_pakai_devbox_eta_tak_diketahui(self):
        running = [RunningItem(10, math.inf, batch=False)]
        out = simulate(2, running, [QueuedItem(1, 10, 300, user_limit=1)])
        self.assertTrue(math.isinf(out[0].start_in))
        self.assertTrue(out[0].own_limit)

    def test_jadwal_dan_kuota_menunda(self):
        out = simulate(2, [], [QueuedItem(1, 10, 300, not_before=1200)])
        self.assertEqual(out[0].start_in, 1200.0)

    def test_job_terjadwal_tidak_menahan_job_lain(self):
        q = [QueuedItem(1, 10, 300, not_before=7200), QueuedItem(2, 11, 300),
             QueuedItem(3, 12, 300)]
        out = simulate(1, [], q)
        self.assertEqual([s.start_in for s in out], [7200.0, 0.0, 300.0])

    def test_job_pemilik_disalip_job_lain(self):
        # 1 slot; user 10 sedang pakai Devbox (batas 1) -> job user 11 jalan duluan.
        running = [RunningItem(10, math.inf, batch=False)]
        q = [QueuedItem(1, 10, 300, user_limit=1), QueuedItem(2, 11, 300, user_limit=1)]
        out = simulate(1, running, q)
        self.assertTrue(math.isinf(out[0].start_in))
        self.assertEqual(out[1].start_in, 0.0)

    def test_slot_minimal_satu(self):
        out = simulate(0, [], [QueuedItem(1, 10, 60), QueuedItem(2, 11, 60)])
        self.assertEqual([s.start_in for s in out], [0.0, 60.0])


if __name__ == "__main__":
    unittest.main()
