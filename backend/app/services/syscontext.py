"""Pengetahuan SISTEM untuk Asisten AI: library terpasang, GPU, aturan platform.

Asisten "membaca sistem" secara NYATA: daftar paket diambil dari image compute
(`pip list` di container efemeral) lalu di-cache per versi Python. Hanya paket
kurasi (yang relevan untuk rekomendasi) yang dikirim ke model agar konteks tetap
ringkas — model kecil punya jendela konteks terbatas.
"""

from __future__ import annotations

import asyncio
import json
import time

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Paket yang ditampilkan ke model (superset; yang tak terpasang otomatis tersaring).
_CURATED = {
    "torch", "torchvision", "torchaudio", "tensorflow-cpu", "tensorflow", "keras",
    "transformers", "datasets", "tokenizers", "sentencepiece", "accelerate",
    "numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "seaborn", "plotly",
    "opencv-python-headless", "pillow", "scikit-image", "imageio",
    "xgboost", "lightgbm", "catboost", "statsmodels", "numba", "sympy", "networkx",
    "spacy", "nltk", "gensim", "sastrawi", "wordcloud", "emoji", "deep-translator",
    "thefuzz", "beautifulsoup4", "requests", "tqdm", "joblib",
    "ultralytics", "timm", "pytorch-lightning", "torchmetrics", "torchinfo",
    "einops", "tensorboard", "mlxtend", "optuna", "shap", "lime",
    "category-encoders", "missingno", "prophet", "yfinance", "folium", "geopandas",
    "librosa", "soundfile", "pypdf", "python-docx", "openpyxl", "xlsxwriter",
    "tabulate", "kaggle", "sqlalchemy", "duckdb", "pyarrow",
    # gelombang 2 (2026-07-23): speech, OCR, time series, statistik
    "faster-whisper", "evaluate", "rouge-score", "sacrebleu", "jiwer",
    "easyocr", "pytesseract", "pdf2image", "pmdarima", "sktime", "pingouin",
}

# Fallback bila `pip list` via docker gagal (mis. runtime bukan docker / image absen).
_FALLBACK_LIBS = (
    "torch (CUDA), torchvision, torchaudio, tensorflow (CPU), transformers, numpy, "
    "pandas, scipy, scikit-learn, matplotlib, seaborn, opencv (headless), xgboost, "
    "lightgbm, statsmodels, spacy, nltk, gensim, Sastrawi, wordcloud, ultralytics, "
    "timm, pytorch-lightning, torchmetrics, optuna, shap, lime, prophet, geopandas, "
    "folium, yfinance, pypdf, python-docx, xlsxwriter, kaggle"
)

_CACHE_TTL_SECONDS = 6 * 3600  # image jarang berubah; refresh tiap 6 jam
_cache: dict[str, tuple[float, str]] = {}
_lock = asyncio.Lock()


async def _pip_list_from_image(image: str) -> dict[str, str]:
    """Jalankan `pip list --format=freeze` di container efemeral; {} bila gagal."""
    argv = [
        *settings.DOCKER_CMD.split(),
        "run", "--rm", "--network", "none", image,
        "python", "-m", "pip", "list", "--format=freeze",
    ]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        return {}
    if proc.returncode != 0:
        return {}
    pkgs: dict[str, str] = {}
    for line in out.decode("utf-8", "replace").splitlines():
        name, sep, ver = line.strip().partition("==")
        if sep:
            pkgs[name.lower().replace("_", "-")] = ver
    return pkgs


def _libs_line(pkgs: dict[str, str]) -> str:
    """Baris ringkas 'nama versi' hanya untuk paket kurasi yang benar-benar ada."""
    picked = [f"{k} {v}" for k, v in sorted(pkgs.items()) if k in _CURATED]
    return ", ".join(picked)


def _gpu_line() -> str:
    """Deskripsi GPU nyata (best-effort)."""
    try:
        from app.services import gpu as gpu_svc  # lazy: hindari import melingkar

        gpus = gpu_svc.list_gpus()
        if gpus:
            g = gpus[0]
            total_gb = round(getattr(g, "mem_total_mb", 0) / 1024)
            return f"{getattr(g, 'name', 'GPU')} ({total_gb} GB VRAM) x{len(gpus)}"
    except Exception:  # noqa: BLE001
        pass
    return "GPU NVIDIA (CUDA tersedia)"


def _shared_models_block() -> str:
    """Blok MODEL PRE-TRAINED BERSAMA dari _MANIFEST.json (kosong bila belum ada).

    Manifest ditulis scripts/download_shared_models.py; folder di-mount read-only
    ke /opt/ch-models di semua kernel & job.
    """
    try:
        manifest = settings.shared_models_path / "_MANIFEST.json"
        if not manifest.exists():
            return ""
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        if not entries:
            return ""
        lines = [
            f"  * {e['path']} \u2014 {e['desc']}. Contoh: `{e['contoh']}`"
            for e in entries
            if e.get("path") and e.get("desc")
        ]
        if not lines:
            return ""
        return (
            "\n- MODEL PRE-TRAINED BERSAMA sudah tersedia lokal di /opt/ch-models "
            "(read-only, TANPA download \u2014 SELALU pakai path ini alih-alih menyuruh "
            "user download dari internet):\n" + "\n".join(lines)
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("syscontext manifest model gagal: %s", exc)
        return ""


async def system_context(python_version: str | None) -> str:
    """Blok INFO SISTEM untuk system prompt asisten (di-cache per versi Python).

    python_version divalidasi lewat peta versi->image internal (nilai tak dikenal
    jatuh ke image default) — TIDAK pernah disisipkan ke perintah docker.
    """
    ver = (python_version or "").strip()
    if ver not in settings.python_image_map:
        ver = (settings.DOCKER_PYTHON_DEFAULT or "3.10").strip()
    now = time.monotonic()
    cached = _cache.get(ver)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    async with _lock:
        cached = _cache.get(ver)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        libs = ""
        try:
            pkgs = await _pip_list_from_image(settings.image_for_python(ver))
            libs = _libs_line(pkgs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("syscontext pip list gagal: %s", exc)
        if not libs:
            libs = _FALLBACK_LIBS + " (daftar perkiraan)"
        text = (
            "INFO SISTEM NYATA (sumber kebenaran — jangan mengarang di luar ini):\n"
            f"- Lingkungan: Python {ver} dalam container di server GPU kampus; "
            f"perangkat: {_gpu_line()}.\n"
            f"- Library SUDAH TERPASANG (nama versi): {libs}.\n"
            "- Paket di luar daftar itu kemungkinan BELUM terpasang. Cara pasang: "
            "sel `!pip install NAMA` — otomatis masuk penyimpanan pribadi user "
            "(/persist, permanen antar-sesi, tidak mengganggu pengguna lain).\n"
            "- UTAMAKAN merekomendasikan library yang sudah terpasang di atas; "
            "JANGAN menyuruh install paket yang sudah ada di daftar.\n"
            "- File kerja sesi: /work (sementara); simpan hasil penting ke /persist "
            "(muncul di menu Penyimpanan).\n"
            "- TERMINAL tersedia: tombol Terminal atau Ctrl+` di notebook — bash + git "
            "di dalam container sesi (folder sama: /work & /persist). Perintah yang "
            "MENANYAKAN input (mis. git push minta username/token) HARUS dijalankan di "
            "terminal, BUKAN lewat sel `!...` — sel notebook tidak bisa menjawab prompt "
            "interaktif.\n"
            "- GIT PUSH ke GitHub (HTTPS) WAJIB Personal Access Token — GitHub MENOLAK "
            "password akun sejak 2021; ini aturan GitHub, bukan pembatasan platform. "
            "CARA BUAT TOKEN (jelaskan langkah ini bila user belum punya): buka "
            "github.com > klik foto profil > Settings > Developer settings (paling "
            "bawah) > Personal access tokens > Fine-grained tokens > Generate new "
            "token; isi nama & masa berlaku; Repository access = Only select "
            "repositories (pilih repo tujuan); Permissions > Repository permissions > "
            "Contents = Read and write; klik Generate lalu SALIN token (hanya tampil "
            "sekali). Setup sekali di terminal: `git config --global "
            "credential.helper store`, lalu push pertama isi username GitHub + TEMPEL "
            "token di prompt Password (layar tak menampilkan apa pun saat menempel — "
            "itu normal) — token tersimpan permanen & privat di /persist user, push "
            "berikutnya tidak ditanya lagi. Error 'Authentication failed' = memakai "
            "password akun / token salah izin; error 'could not read Username / "
            "terminal prompts disabled' = perintah dijalankan dari sel, pindah ke "
            "terminal. Clone/pull repo PUBLIK tidak butuh token. Ingatkan: JANGAN "
            "menaruh token di dalam kode/notebook."
            + _shared_models_block()
        )
        _cache[ver] = (time.monotonic(), text)
        return text
