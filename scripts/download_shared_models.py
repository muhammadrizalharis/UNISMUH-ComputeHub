"""Unduh model pre-trained BERSAMA ke ~/.computehub/shared_models (sekali oleh admin).

Folder ini di-mount READ-ONLY ke SEMUA container kernel & job sebagai /opt/ch-models,
sehingga user memakai model populer TANPA download ulang (hemat bandwidth kampus yang
sering putus + hemat kuota disk /persist per-user).

CARA PAKAI (di host, jalan di DALAM image compute agar dependensi lengkap):

    mkdir -p ~/.computehub/shared_models
    sudo docker run --rm \
      -v ~/.computehub/shared_models:/out \
      -v ~/DATA_ICAL/SERVER-KAMPUS/scripts/download_shared_models.py:/dl.py:ro \
      ch-compute:latest python /dl.py

Idempotent: model yang sudah lengkap dilewati. Aman diulang bila jaringan putus.
Di akhir menulis /out/_MANIFEST.json — dibaca services/syscontext.py agar asisten AI
tahu model apa saja yang tersedia + contoh pemakaiannya.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path("/out")

# ---------------------------------------------------------------- katalog model
# path: subfolder di /opt/ch-models ; contoh: 1 baris kode pemakaian (utk manifest).
HF_MODELS = [
    {
        "repo": "Systran/faster-whisper-small",
        "path": "faster-whisper-small",
        "desc": "Whisper small (CTranslate2) — transkripsi audio cepat, multibahasa (termasuk Indonesia)",
        "contoh": 'from faster_whisper import WhisperModel; m = WhisperModel("/opt/ch-models/faster-whisper-small", device="cuda")',
    },
    {
        "repo": "Systran/faster-whisper-large-v3",
        "path": "faster-whisper-large-v3",
        "desc": "Whisper large-v3 (CTranslate2) — transkripsi paling akurat, cocok di L40S",
        "contoh": 'from faster_whisper import WhisperModel; m = WhisperModel("/opt/ch-models/faster-whisper-large-v3", device="cuda")',
    },
    {
        "repo": "indobenchmark/indobert-base-p1",
        "path": "indobert-base-p1",
        "desc": "IndoBERT base — NLP bahasa Indonesia (klasifikasi/sentimen/NER, fine-tuning)",
        "contoh": 'from transformers import AutoTokenizer, AutoModel; tok = AutoTokenizer.from_pretrained("/opt/ch-models/indobert-base-p1")',
    },
    {
        "repo": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "path": "paraphrase-multilingual-MiniLM-L12-v2",
        "desc": "Sentence embedding multibahasa — kemiripan teks/semantic search (dukung Indonesia)",
        "contoh": 'from sentence_transformers import SentenceTransformer; m = SentenceTransformer("/opt/ch-models/paraphrase-multilingual-MiniLM-L12-v2")',
    },
]

YOLO_FILES = [
    # (nama file, deskripsi) — diunduh via ultralytics (URL resmi rilis GitHub).
    ("yolov8n.pt", "YOLOv8 nano — deteksi objek realtime (paling ringan)"),
    ("yolov8s.pt", "YOLOv8 small — deteksi objek, akurasi lebih baik"),
    ("yolov8n-seg.pt", "YOLOv8 nano segmentasi instance"),
]


def hf_download() -> list[dict]:
    from huggingface_hub import snapshot_download

    entries = []
    for m in HF_MODELS:
        dst = OUT / m["path"]
        marker = dst / ".complete"
        if marker.exists():
            print(f"[skip] {m['path']} sudah lengkap")
        else:
            print(f"[unduh] {m['repo']} -> {dst} ...")
            snapshot_download(m["repo"], local_dir=str(dst))
            marker.touch()
            print(f"[ok] {m['path']}")
        entries.append({"path": f"/opt/ch-models/{m['path']}", "desc": m["desc"], "contoh": m["contoh"]})
    return entries


def yolo_download() -> list[dict]:
    import shutil

    from ultralytics.utils.downloads import attempt_download_asset

    ydir = OUT / "yolo"
    ydir.mkdir(parents=True, exist_ok=True)
    entries = []
    for fname, desc in YOLO_FILES:
        dst = ydir / fname
        if dst.exists() and dst.stat().st_size > 1_000_000:
            print(f"[skip] yolo/{fname} sudah ada")
        else:
            print(f"[unduh] {fname} ...")
            got = Path(attempt_download_asset(fname))  # unduh ke CWD
            # shutil.move (bukan Path.replace): CWD di overlay fs container,
            # /out volume terpisah -> rename lintas-device gagal (Errno 18).
            shutil.move(str(got), str(dst))
            print(f"[ok] yolo/{fname}")
        entries.append({
            "path": f"/opt/ch-models/yolo/{fname}",
            "desc": desc,
            "contoh": f'from ultralytics import YOLO; model = YOLO("/opt/ch-models/yolo/{fname}")',
        })
    return entries


def easyocr_download() -> list[dict]:
    import easyocr

    edir = OUT / "easyocr"
    edir.mkdir(parents=True, exist_ok=True)
    if any(edir.glob("*.pth")):
        print("[skip] easyocr model sudah ada")
    else:
        print("[unduh] easyocr (id+en) ...")
        easyocr.Reader(["id", "en"], gpu=False, model_storage_directory=str(edir),
                       user_network_directory=str(edir), download_enabled=True)
        print("[ok] easyocr")
    return [{
        "path": "/opt/ch-models/easyocr",
        "desc": "Model EasyOCR (deteksi + recognisi latin, bahasa Indonesia & Inggris)",
        "contoh": 'import easyocr; r = easyocr.Reader(["id","en"], model_storage_directory="/opt/ch-models/easyocr", download_enabled=False)',
    }]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    gagal: list[str] = []
    for fn in (hf_download, yolo_download, easyocr_download):
        try:
            entries.extend(fn())
        except Exception as exc:  # noqa: BLE001 — lanjut model lain bila 1 sumber gagal
            print(f"[GAGAL] {fn.__name__}: {exc}", file=sys.stderr)
            gagal.append(fn.__name__)
    manifest = OUT / "_MANIFEST.json"
    manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nManifest: {manifest} ({len(entries)} entri)")
    if gagal:
        print(f"SEBAGIAN GAGAL: {', '.join(gagal)} — jalankan ulang skrip ini.", file=sys.stderr)
        return 1
    print("SEMUA MODEL SIAP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
