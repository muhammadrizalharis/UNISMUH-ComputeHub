# Image compute ComputeHub KHUSUS PYTHON 3.13 — varian dari ch-compute-py.Dockerfile.
# KENAPA TERPISAH: stack torch cu121 (2.5.1) TIDAK punya wheel torchvision utk cp313
# -> 3.13 memakai torch 2.6.0+cu124 / torchvision 0.21.0+cu124 / torchaudio 2.6.0+cu124
# (driver host 595.x, CUDA 13.2 -> cu124 didukung). Beberapa pin lama di
# requirements-compute*.txt juga belum punya wheel cp313 -> pin DILONGGARKAN (== dihapus)
# KHUSUS image ini: pip memilih versi terbaru yang kompatibel; numpy 2.x + stack torch
# tetap dikunci via constraints.
#
# Build (salinan requirements-compute*.txt harus ada di backend/docker):
#   cp backend/requirements-compute.txt backend/requirements-compute-extra.txt backend/docker/
#   sudo -n docker build -t ch-compute:py313 -f backend/docker/ch-compute-py313.Dockerfile backend/docker
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

ARG PYTHON_VERSION=3.13

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_RETRIES=10 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONUNBUFFERED=1 \
    NLTK_DATA=/usr/local/share/nltk_data

# Python 3.13 dari deadsnakes + toolchain + dependency sistem.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common gnupg ca-certificates curl && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} python${PYTHON_VERSION}-dev python${PYTHON_VERSION}-venv \
        build-essential git ffmpeg libsndfile1 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python && \
    ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3

# Bootstrap pip offline (ensurepip); get-pip.py hanya fallback (jaringan kampus reset-an).
RUN (python -m ensurepip --upgrade || \
     (curl -fsSL --retry 15 --retry-all-errors --retry-delay 2 \
        https://bootstrap.pypa.io/get-pip.py | python)) && \
    python -m pip install --upgrade pip && \
    printf '#!/bin/sh\nexec python -m pip "$@"\n' > /usr/local/bin/pip && \
    chmod +x /usr/local/bin/pip && cp -f /usr/local/bin/pip /usr/local/bin/pip3

# Kunci numpy 2.x + stack torch cu124 (satu-satunya stack lengkap utk cp313).
RUN printf 'numpy>=2.0,<3\ntorch==2.6.0+cu124\ntorchvision==0.21.0+cu124\ntorchaudio==2.6.0+cu124\n' \
        > /tmp/protect.txt

# 1) torch stack cu124 (GPU).
RUN python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu124 \
        torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0+cu124 && \
    { find /usr/local/lib /usr/lib -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; }

# 2) Core + requirements-compute.txt DENGAN PIN DILONGGARKAN (wheel cp313).
COPY requirements-compute.txt /tmp/requirements-compute.txt
RUN sed -i 's/==.*$//' /tmp/requirements-compute.txt && \
    python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu124 \
        numpy pandas scipy scikit-learn matplotlib seaborn pillow networkx requests && \
    python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu124 \
        -r /tmp/requirements-compute.txt && \
    { find /usr/local/lib /usr/lib -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; }

# 3) Data model NLP (nltk + spacy en_core_web_sm).
RUN python -m nltk.downloader -d "$NLTK_DATA" \
        punkt punkt_tab stopwords wordnet omw-1.4 \
        averaged_perceptron_tagger averaged_perceptron_tagger_eng vader_lexicon && \
    python -m spacy download en_core_web_sm

# 4) Library tambahan (pin dilonggarkan) + ipykernel; opencv headless dipaksa ulang.
COPY requirements-compute-extra.txt /tmp/requirements-compute-extra.txt
RUN sed -i 's/==.*$//' /tmp/requirements-compute-extra.txt && \
    python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu124 \
        -r /tmp/requirements-compute-extra.txt ipykernel jupyter_client && \
    python -m pip install --force-reinstall --no-deps opencv-python-headless && \
    { find /usr/local/lib /usr/lib -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; } && \
    { rm -rf /root/.cache /tmp/* /usr/local/share/nltk_data/*.zip 2>/dev/null || true; }

WORKDIR /work
