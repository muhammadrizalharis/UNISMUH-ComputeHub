# Image compute per-user ComputeHub — SETARA backend/.venv host ("ala Colab").
# CUDA runtime + Python 3.10 + torch cu121 (GPU) + tensorflow-cpu + SELURUH library
# requirements-compute.txt, supaya job di container TIDAK kehilangan library.
#
# Build (sudo passwordless yang SUDAH ada; TIDAK mengubah setelan docker). Perlu
# salinan requirements-compute.txt + requirements-compute-extra.txt di folder
# context (backend/docker):
#   cp backend/requirements-compute.txt backend/requirements-compute-extra.txt backend/docker/
#   sudo -n docker build -t ch-compute:latest -f backend/docker/ch-compute.Dockerfile backend/docker
#
# CATATAN: tensorflow-cpu (BUKAN tensorflow penuh) agar TAK bentrok CUDA dgn torch GPU.
# numpy dikunci >=2,<3 + torch/vision/audio cu121 (sama spt host) via constraints.
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_RETRIES=10 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONUNBUFFERED=1 \
    NLTK_DATA=/usr/local/share/nltk_data

# Python 3.10 + toolchain + dependency sistem (opencv/librosa/soundfile/ffmpeg).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev python3-venv build-essential git ca-certificates \
        ffmpeg libsndfile1 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3 /usr/local/bin/python

# Kunci stack GPU torch + numpy 2.x agar TAK ke-downgrade oleh library lain.
RUN printf 'numpy>=2.0,<3\ntorch==2.5.1+cu121\ntorchvision==0.20.1+cu121\ntorchaudio==2.5.1+cu121\n' \
        > /tmp/protect.txt

# 1) torch stack cu121 (GPU).
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121 && \
    { find /usr/local/lib/python3.10 -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; }

# 2) Core (di host ada di base) + seluruh requirements-compute.txt (versi dipin).
COPY requirements-compute.txt /tmp/requirements-compute.txt
RUN python3 -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        numpy pandas scipy scikit-learn matplotlib seaborn pillow networkx requests && \
    python3 -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        -r /tmp/requirements-compute.txt && \
    { find /usr/local/lib/python3.10 -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; }

# 3) Data model NLP (nltk + spacy en_core_web_sm) — tersedia utk semua job.
RUN python3 -m nltk.downloader -d "$NLTK_DATA" \
        punkt punkt_tab stopwords wordnet omw-1.4 \
        averaged_perceptron_tagger averaged_perceptron_tagger_eng vader_lexicon && \
    python3 -m spacy download en_core_web_sm

# 4) ipykernel + jupyter_client untuk SESI NOTEBOOK INTERAKTIF (kernel jalan di container).
RUN python3 -m pip install -c /tmp/protect.txt ipykernel jupyter_client && \
    { find /usr/local/lib/python3.10 -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; } && \
    { rm -rf /root/.cache /tmp/* /usr/local/share/nltk_data/*.zip 2>/dev/null || true; }

# 5) Library populer tambahan (requirements-compute-extra.txt) — layer terpisah
#    agar cache layer 1-4 tetap utuh. /tmp/protect.txt sudah dihapus di layer 4,
#    jadi ditulis ulang di sini. ultralytics menarik opencv-python non-headless;
#    ditimpa ulang dengan headless (--no-deps) supaya image tetap headless.
COPY requirements-compute-extra.txt /tmp/requirements-compute-extra.txt
RUN printf 'numpy>=2.0,<3\ntorch==2.5.1+cu121\ntorchvision==0.20.1+cu121\ntorchaudio==2.5.1+cu121\n' \
        > /tmp/protect.txt && \
    python3 -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        -r /tmp/requirements-compute-extra.txt && \
    python3 -m pip install --force-reinstall --no-deps opencv-python-headless==4.13.0.92 && \
    { find /usr/local/lib/python3.10 -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; } && \
    { rm -rf /root/.cache /tmp/* 2>/dev/null || true; }

# 6) GELOMBANG 2: speech (faster-whisper) + metrik NLP + OCR + time series + statistik,
#    plus binary sistem: tesseract (eng+ind), poppler (pdf2image), graphviz (render pohon).
#    Layer terpisah agar cache layer 1-5 utuh; protect.txt ditulis ulang (dihapus layer 5).
COPY requirements-compute-extra2.txt /tmp/requirements-compute-extra2.txt
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-ind poppler-utils graphviz && \
    rm -rf /var/lib/apt/lists/* && \
    printf 'numpy>=2.0,<3\ntorch==2.5.1+cu121\ntorchvision==0.20.1+cu121\ntorchaudio==2.5.1+cu121\n' \
        > /tmp/protect.txt && \
    python3 -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        -r /tmp/requirements-compute-extra2.txt && \
    { find /usr/local/lib/python3.10 -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; } && \
    { rm -rf /root/.cache /tmp/* 2>/dev/null || true; }

# Alat CLI ringan untuk terminal web (edit/lihat file dari shell). Layer kecil terpisah.
RUN apt-get update && apt-get install -y --no-install-recommends nano less tree && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /work
