from app.core.config import settings
from app.services import ollama_route
from app.services.gpu import GpuInfo


def _gpus(free0: float, free1: float):
    return lambda: [
        GpuInfo(index=0, name="L40S", mem_used_mb=46000 - free0, mem_total_mb=46000),
        GpuInfo(index=1, name="L40S", mem_used_mb=46000 - free1, mem_total_mb=46000),
    ]


def test_tanpa_setelan_pakai_default(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_GPU_BACKENDS", "")
    assert ollama_route.pick_base("http://localhost:11434/") == "http://localhost:11434"


def test_pilih_gpu_paling_lega(monkeypatch):
    monkeypatch.setattr(
        settings, "OLLAMA_GPU_BACKENDS", "0=http://127.0.0.1:11435, 1=http://127.0.0.1:11436/"
    )
    monkeypatch.setattr(ollama_route.gpu_svc, "list_all_gpus", _gpus(1200, 28000))
    assert ollama_route.pick_base("http://localhost:11434") == "http://127.0.0.1:11436"
    monkeypatch.setattr(ollama_route.gpu_svc, "list_all_gpus", _gpus(30000, 500))
    assert ollama_route.pick_base("http://localhost:11434") == "http://127.0.0.1:11435"


def test_gagal_baca_gpu_pakai_default(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_GPU_BACKENDS", "0=http://127.0.0.1:11435")

    def _rusak():
        raise RuntimeError("nvml")

    monkeypatch.setattr(ollama_route.gpu_svc, "list_all_gpus", _rusak)
    assert ollama_route.pick_base("http://localhost:11434") == "http://localhost:11434"


def test_setelan_rusak_diabaikan(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_GPU_BACKENDS", "x=http://a, 1, 2=")
    assert ollama_route.backends() == {}
