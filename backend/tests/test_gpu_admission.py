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


def _gpu(index: int, total: float, used: float) -> gpu_svc.GpuInfo:
    return gpu_svc.GpuInfo(
        index=index, name=f"GPU{index}", mem_total_mb=total, mem_used_mb=used
    )


class PickGpuAdmissionTests(TestCase):
    def setUp(self) -> None:
        reservations._claims.clear()
        self.addCleanup(reservations._claims.clear)

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


if __name__ == "__main__":
    main()
