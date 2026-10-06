"""Plafon VRAM ditegakkan DI DALAM container ComputeHub (job, kernel, Devbox)."""

import os
import runpy
import sys
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from app.core.config import settings
from app.models.job import JobDevice
from app.services import interactive, jobruntime, provision


GUARD = settings.vram_guard_path / "sitecustomize.py"


class VramGuardArgvTests(TestCase):
    def test_mati_default(self) -> None:
        with patch.object(settings, "VRAM_HARD_LIMIT", False):
            self.assertEqual(provision.vram_guard_argv(8192), [])

    def test_tanpa_batas_tidak_dipasang(self) -> None:
        with patch.object(settings, "VRAM_HARD_LIMIT", True):
            self.assertEqual(provision.vram_guard_argv(0), [])
            self.assertEqual(provision.vram_guard_argv(-5), [])

    def test_mount_read_only_dan_env(self) -> None:
        with patch.object(settings, "VRAM_HARD_LIMIT", True):
            argv = provision.vram_guard_argv(8192.4)
        self.assertEqual(
            argv,
            [
                "-v", f"{settings.vram_guard_path}:/opt/ch-vram:ro",
                "-e", "PYTHONPATH=/opt/ch-vram",
                "-e", "CH_MAX_VRAM_MB=8192",
            ],
        )

    def test_job_docker_argv_hanya_saat_gpu(self) -> None:
        with patch.object(settings, "VRAM_HARD_LIMIT", True):
            gpu = jobruntime.docker_run_argv(
                job_id=1, working_dir="/tmp", run_cwd="/tmp", command="python x.py",
                gpu_index=0, gpu_indices=[0], device=JobDevice.gpu, vram_mb=4096,
            )
            cpu = jobruntime.docker_run_argv(
                job_id=2, working_dir="/tmp", run_cwd="/tmp", command="python x.py",
                gpu_index=-1, gpu_indices=[], device=JobDevice.cpu, vram_mb=4096,
            )
        self.assertIn("CH_MAX_VRAM_MB=4096", gpu)
        self.assertNotIn("CH_MAX_VRAM_MB=4096", cpu)

    def test_env_kernel(self) -> None:
        with patch.object(settings, "VRAM_HARD_LIMIT", True):
            env = interactive._kernel_env(0, cap_vram_mb=2048)
            lepas = interactive._kernel_env(0, cap_vram_mb=0)
        self.assertEqual(env["CH_K_VRAM_MB"], "2048")
        self.assertEqual(env["CH_K_VRAM_DIR"], str(settings.vram_guard_path))
        self.assertNotIn("CH_K_VRAM_MB", lepas)


class SitecustomizeTests(TestCase):
    """Hook dijalankan apa adanya dengan modul torch/tensorflow palsu."""

    def setUp(self) -> None:
        self.impor_asli = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
        self.addCleanup(self._pulihkan)

    def _pulihkan(self) -> None:
        import builtins

        builtins.__import__ = self.impor_asli
        sys.modules.pop("torch", None)
        sys.modules.pop("tensorflow", None)

    def jalankan(self, cap: str | None) -> None:
        env = {k: v for k, v in os.environ.items() if k != "CH_MAX_VRAM_MB"}
        if cap is not None:
            env["CH_MAX_VRAM_MB"] = cap
        env["CH_VRAM_QUIET"] = "1"
        with patch.dict(os.environ, env, clear=True):
            runpy.run_path(str(GUARD), run_name="sitecustomize")

    def torch_palsu(self, total_mb: float, tersedia: bool = True):
        dipanggil: list[tuple[float, int]] = []
        cuda = SimpleNamespace(
            is_available=lambda: tersedia,
            device_count=lambda: 1,
            get_device_properties=lambda idx: SimpleNamespace(total_memory=int(total_mb * 1024 * 1024)),
            set_per_process_memory_fraction=lambda frac, idx=0: dipanggil.append((frac, idx)),
        )
        return SimpleNamespace(cuda=cuda), dipanggil

    def test_tanpa_env_tidak_mengubah_import(self) -> None:
        import builtins

        sebelum = builtins.__import__
        self.jalankan(None)
        self.assertIs(builtins.__import__, sebelum)

    def test_fraksi_sesuai_plafon(self) -> None:
        torch, dipanggil = self.torch_palsu(46068)
        self.jalankan("8192")
        sys.modules["torch"] = torch
        __import__("torch")
        self.assertEqual(len(dipanggil), 1)
        self.assertAlmostEqual(dipanggil[0][0], 8192 / 46068, places=6)

    def test_plafon_lebih_besar_dari_kartu_dilewati(self) -> None:
        torch, dipanggil = self.torch_palsu(8192)
        self.jalankan("16384")
        sys.modules["torch"] = torch
        __import__("torch")
        self.assertEqual(dipanggil, [])

    def test_container_cpu_aman(self) -> None:
        torch, dipanggil = self.torch_palsu(8192, tersedia=False)
        self.jalankan("8192")
        sys.modules["torch"] = torch
        __import__("torch")
        self.assertEqual(dipanggil, [])

    def test_torch_rusak_tidak_menggagalkan_import(self) -> None:
        rusak = SimpleNamespace(cuda=SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_properties=lambda idx: (_ for _ in ()).throw(RuntimeError("driver")),
            set_per_process_memory_fraction=lambda *a, **k: None,
        ))
        self.jalankan("8192")
        sys.modules["torch"] = rusak
        self.assertIs(__import__("torch"), rusak)

    def test_cuda_yang_mengimpor_lagi_tidak_rekursi(self) -> None:
        """Insiden 6 Okt: init CUDA mengimpor modul lain -> hook memanggil dirinya -> hang."""
        torch, dipanggil = self.torch_palsu(46068)
        torch.cuda.is_available = lambda: bool(__import__("torch")) or True
        self.jalankan("8192")
        sys.modules["torch"] = torch
        __import__("torch")
        self.assertEqual(len(dipanggil), 1)

    def test_paket_setengah_terimpor_dilewati(self) -> None:
        torch, dipanggil = self.torch_palsu(46068)
        torch.__spec__ = SimpleNamespace(_initializing=True)
        self.jalankan("8192")
        sys.modules["torch"] = torch
        __import__("torch")
        self.assertEqual(dipanggil, [])
        torch.__spec__ = SimpleNamespace(_initializing=False)
        __import__("torch")
        self.assertEqual(len(dipanggil), 1)

    def test_tensorflow(self) -> None:
        dipakai: list[int] = []
        config = SimpleNamespace(
            list_physical_devices=lambda jenis: ["GPU:0"],
            LogicalDeviceConfiguration=lambda memory_limit: memory_limit,
            set_logical_device_configuration=lambda gpu, konf: dipakai.extend(konf),
        )
        tf = SimpleNamespace(config=config)
        self.jalankan("4096")
        sys.modules["tensorflow"] = tf
        __import__("tensorflow")
        self.assertEqual(dipakai, [4096])


if __name__ == "__main__":
    main(verbosity=2)
