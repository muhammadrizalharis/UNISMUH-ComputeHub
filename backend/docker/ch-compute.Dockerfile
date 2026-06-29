# Image compute per-user ComputeHub — SETARA backend/.venv host ("ala Colab").
# CUDA runtime + Python 3.10 + torch cu121 (GPU) + tensorflow-cpu + SELURUH library
# requirements-compute.txt, supaya job di container TIDAK kehilangan library.
#
# Build (sudo passwordless yang SUDAH ada; TIDAK mengubah setelan docker). Perlu
# salinan requirements-compute.txt di folder context (backend/docker):
#   cp backend/requirements-compute.txt backend/docker/
#   sudo -n docker build -t ch-compute:latest -f backend/docker/ch-compute.Dockerfile backend/docker
#
# CATATAN: tensorflow-cpu (BUKAN tensorflow penuh) agar TAK bentrok CUDA dgn torch GPU.
# numpy dikunci >=2,<3 + torch/vision/audio cu121 (sama spt host) via constraints.
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
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
        torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121

# 2) Core (di host ada di base) + seluruh requirements-compute.txt (versi dipin).
COPY requirements-compute.txt /tmp/requirements-compute.txt
RUN python3 -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        numpy pandas scipy scikit-learn matplotlib seaborn pillow networkx requests && \
    python3 -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        -r /tmp/requirements-compute.txt

# 3) Data model NLP (nltk + spacy en_core_web_sm) — tersedia utk semua job.
RUN python3 -m nltk.downloader -d "$NLTK_DATA" \
        punkt punkt_tab stopwords wordnet omw-1.4 \
        averaged_perceptron_tagger averaged_perceptron_tagger_eng vader_lexicon && \
    python3 -m spacy download en_core_web_sm

# 4) ipykernel + jupyter_client untuk SESI NOTEBOOK INTERAKTIF (kernel jalan di container).
RUN python3 -m pip install -c /tmp/protect.txt ipykernel jupyter_client

WORKDIR /work
