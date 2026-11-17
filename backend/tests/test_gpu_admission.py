"""Admission VRAM dipisah dari PLAFON (cap jalan-waktu).

Inti PR: job/sesi boleh MASUK selama VRAM bebas >= ambang-masuk kecil
(GPU_ADMIT_MIN_FREE_MB), BUKAN harus menunggu seluruh `required_mb` kosong.
Plafon ditegakkan saat jalan oleh vram_guard (uji di test_vram_guard.py).
"""

from unittest import TestCase, main
from unittest.mock import patch

from app.core.config import settings
from app.services import gpu as gpu_svc
from app.services import reservations
from app.services import vram_pocket


def _gpu(index: int, total: float, used: float) -> gpu_svc.GpuInfo:
    return gpu_svc.GpuInfo(
        index=index, name=f"GPU{index}", mem_total_mb=total, mem_used_mb=used
    )


def _isolate(test: TestCase, *, actual: bool, pocket: dict[int, float] | None = None) -> None:
    """Registry bersih, mode hitung terkunci, kantong VRAM palsu (tanpa file)."""
    reservations._claims.clear()
    test.addCleanup(reservations._claims.clear)
    for p in (
        patch.object(settings, "GPU_COUNT_ACTUAL_USAGE", actual),
        patch.object(vram_pocket, "held_mb", lambda i: (pocket or {}).get(i, 0.0)),
        patch.object(vram_pocket, "on_claims_changed", lambda: None),
    ):
        p.start()
        test.addCleanup(p.stop)


class PickGpuAdmissionTests(TestCase):
    """Mode anggaran (lama): slot & anggaran dihitung dari plafon yang dipesan."""

    def setUp(self) -> None:
        _isolate(self, actual=False)

    def test_masuk_walau_free_kecil_tanpa_tunggu_plafon_penuh(self) -> None:
        # GPU 46 GB, hanya ~500 MB bebas fisik. Job minta plafon 40 GB.
        # Perilaku LAMA menolak (butuh 40 GB+headroom bebas). Perilaku BARU: masuk,
        # karena 500 MB >= ambang masuk tak terpenuhi -> tolak; naikkan ke 1500 MB.
        gpus = [_gpu(0, 46000, 44500)]  # 1500 MB bebas
        with patch.object(gpu_svc, "list_gpus", return_value=gpus), \
                patch.object(settings, "GPU_ADMIT_MIN_FREE_MB", 1024.0), \
                patch.object(settings, "GPU_ALLOW_OVERCOMMIT", False):
            self.assertEqual(gpu_svc.pick_gpu_for(40000), 0)

    def test_tolak_bila_free_di_bawah_ambang_masuk(self) -> None:
        gpus = [_gpu(0, 46000, 45600)]  # 400 MB bebas < 1024 ambang
        with patch.object(gpu_svc, "list_gpus", return_value=gpus), \
                patch.object(settings, "GPU_ADMIT_MIN_FREE_MB", 1024.0), \
                patch.object(settings, "GPU_ALLOW_OVERCOMMIT", False):
            self.assertIsNone(gpu_svc.pick_gpu_for(8192))

    def test_anti_overcommit_default_batasi_jumlah_plafon(self) -> None:
        # Fisik lega (semua bebas) tapi reservasi sudah mendekati usable_total.
        gpus = [_gpu(0, 46000, 0)]
        reservations.reserve("job:a", 0, 44000, kind="job")  # planned ~44 GB
        with patch.object(gpu_svc, "list_gpus", return_value=gpus), \
                patch.object(settings, "GPU_SHARE_HEADROOM_MB", 2048.0), \
                patch.object(settings, "GPU_MAX_WORKLOADS_PER_GPU", 4), \
                patch.object(settings, "GPU_ADMIT_MIN_FREE_MB", 1024.0), \
                patch.object(settings, "GPU_ALLOW_OVERCOMMIT", False):
            # usable = 46000-2048 = 43952; planned 44000 => tak muat plafon baru.
            self.assertIsNone(gpu_svc.pick_gpu_for(8192))

    def test_overcommit_mengabaikan_anggaran_reservasi(self) -> None:
        gpus = [_gpu(0, 46000, 0)]
        reservations.reserve("job:a", 0, 44000, kind="job")
        with patch.object(gpu_svc, "list_gpus", return_value=gpus), \
                patch.object(settings, "GPU_SHARE_HEADROOM_MB", 2048.0), \
                patch.object(settings, "GPU_MAX_WORKLOADS_PER_GPU", 4), \
                patch.object(settings, "GPU_ADMIT_MIN_FREE_MB", 1024.0), \
                patch.object(settings, "GPU_ALLOW_OVERCOMMIT", True):
            # Overcommit: syarat anggaran dilewati; fisik bebas 46 GB >= ambang -> masuk.
            self.assertEqual(gpu_svc.pick_gpu_for(8192), 0)

    def test_batas_jumlah_beban_kerja_tetap_berlaku(self) -> None:
        gpus = [_gpu(0, 46000, 0)]
        for i in range(4):
            reservations.reserve(f"job:{i}", 0, 1000, kind="job")
        with patch.object(gpu_svc, "list_gpus", return_value=gpus), \
                patch.object(settings, "GPU_SHARE_ENABLED", True), \
                patch.object(settings, "GPU_MAX_WORKLOADS_PER_GPU", 4), \
                patch.object(settings, "GPU_ADMIT_MIN_FREE_MB", 1024.0), \
                patch.object(settings, "GPU_ALLOW_OVERCOMMIT", True):
            self.assertIsNone(gpu_svc.pick_gpu_for(1000))

    def test_pool_summary_konsisten_dengan_admission(self) -> None:
        gpus = [_gpu(0, 46000, 44500)]  # 1500 MB bebas
        with patch.object(gpu_svc, "list_gpus", return_value=gpus), \
                patch.object(settings, "GPU_ADMIT_MIN_FREE_MB", 1024.0), \
                patch.object(settings, "GPU_ALLOW_OVERCOMMIT", False), \
                patch.object(settings, "GPU_MAX_WORKLOADS_PER_GPU", 4):
            summary = gpu_svc.pool_summary(40000)
            self.assertTrue(summary["available"])
            self.assertEqual(summary["ready"], 1)


class ActualUsageAdmissionTests(TestCase):
    """Mode pemakaian nyata + kantong VRAM."""

    def setUp(self) -> None:
        self.pocket: dict[int, float] = {}
        _isolate(self, actual=True, pocket=self.pocket)

    def _patches(self, gpus):
        return (
            patch.object(gpu_svc, "list_gpus", return_value=gpus),
            patch.object(settings, "GPU_ADMIT_MIN_FREE_MB", 1024.0),
            patch.object(settings, "GPU_MAX_WORKLOADS_PER_GPU", 2),
            patch.object(settings, "GPU_CLAIM_GRACE_SECONDS", 120.0),
            patch.object(settings, "GPU_ALLOW_OVERCOMMIT", False),
        )

    def _age(self, claim_id: str, seconds: float) -> None:
        reservations._claims[claim_id].created -= seconds

    def test_klaim_diam_tak_menghabiskan_slot(self) -> None:
        gpus = [_gpu(0, 46000, 1000)]
        for i in range(3):
            reservations.reserve(f"devbox:{i}", 0, 18000)
            self._age(f"devbox:{i}", 600)  # lewat masa tenggang, VRAM nyata 0
        p = self._patches(gpus)
        with p[0], p[1], p[2], p[3], p[4]:
            self.assertEqual(reservations.count(0), 0)
            self.assertEqual(reservations.planned_mb(0), 0.0)
            self.assertEqual(reservations.holders(0), 3)
            self.assertEqual(gpu_svc.pick_gpu_for(18000), 0)

    def test_klaim_baru_dan_yang_memakai_vram_menempati_slot(self) -> None:
        gpus = [_gpu(0, 46000, 1000)]
        reservations.reserve("a", 0, 8000)  # masih masa tenggang
        reservations.reserve("b", 0, 8000)
        self._age("b", 600)
        reservations.update_usage("b", 3000)
        p = self._patches(gpus)
        with p[0], p[1], p[2], p[3], p[4]:
            self.assertEqual(reservations.count(0), 2)
            self.assertEqual(reservations.planned_mb(0), 3000.0)
            self.assertIsNone(gpu_svc.pick_gpu_for(8000))  # batas 2 beban kerja aktif

    def test_job_eksklusif_menutup_gpu(self) -> None:
        gpus = [_gpu(0, 46000, 1000), _gpu(1, 46000, 1000)]
        reservations.reserve("job:9#g0", 0, 46000, kind="job", exclusive=True)
        self._age("job:9#g0", 600)
        p = self._patches(gpus)
        with p[0], p[1], p[2], p[3], p[4]:
            self.assertEqual(reservations.planned_mb(0), 46000.0)
            self.assertEqual(gpu_svc.pick_gpu_for(1000), 1)
            summary = gpu_svc.pool_summary(1000)
            self.assertFalse(summary["gpus"][0]["fits"])
            self.assertTrue(summary["gpus"][1]["fits"])

    def test_vram_kantong_dihitung_bebas_dan_diutamakan(self) -> None:
        # GPU0 tampak penuh (500 MB bebas) tetapi 8 GB dipegang kantong -> boleh masuk.
        gpus = [_gpu(0, 46000, 45500), _gpu(1, 46000, 20000)]
        self.pocket.update({0: 8192.0})
        p = self._patches(gpus)
        with p[0], p[1], p[2], p[3], p[4]:
            self.assertEqual(gpu_svc.pick_gpu_for(8000), 0)
            self.pocket.clear()
            self.assertEqual(gpu_svc.pick_gpu_for(8000), 1)


if __name__ == "__main__":
    main()
