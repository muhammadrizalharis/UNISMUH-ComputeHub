# Image compute ComputeHub MULTI-VERSI PYTHON (3.11/3.12/3.13) — varian dari
# ch-compute.Dockerfile (3.10, TIDAK diubah). Python dari deadsnakes PPA, stack
# library SAMA: torch 2.5.1+cu121 + requirements-compute.txt + requirements-compute-extra.txt.
#
# Build (salinan requirements-compute*.txt harus ada di backend/docker):
#   cp backend/requirements-compute.txt backend/requirements-compute-extra.txt backend/docker/
#   sudo -n docker build -t ch-compute:py311 --build-arg PYTHON_VERSION=3.11 \
#        -f backend/docker/ch-compute-py.Dockerfile backend/docker
#   (ulangi dengan 3.12 -> ch-compute:py312, 3.13 -> ch-compute:py313)
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

ARG PYTHON_VERSION=3.12

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_RETRIES=10 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONUNBUFFERED=1 \
    NLTK_DATA=/usr/local/share/nltk_data

# Python <versi> dari deadsnakes + toolchain + dependency sistem (opencv/librosa/ffmpeg).
# /usr/bin/python3 sistem (3.10) TIDAK disentuh (dipakai apt); python & python3 di
# /usr/local/bin (lebih dulu di PATH) menunjuk ke versi target.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common gnupg ca-certificates curl && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} python${PYTHON_VERSION}-dev python${PYTHON_VERSION}-venv \
        build-essential git ffmpeg libsndfile1 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python && \
    ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3

# Bootstrap pip: ensurepip (OFFLINE, wheel bawaan python3.x-venv) — get-pip.py via
# curl hanya fallback (--retry-all-errors: jaringan kampus sering reset koneksi).
# Wrapper pip/pip3 di /usr/local/bin -> selalu pip milik python target.
RUN (python -m ensurepip --upgrade || \
     (curl -fsSL --retry 15 --retry-all-errors --retry-delay 2 \
        https://bootstrap.pypa.io/get-pip.py | python)) && \
    python -m pip install --upgrade pip && \
    printf '#!/bin/sh\nexec python -m pip "$@"\n' > /usr/local/bin/pip && \
    chmod +x /usr/local/bin/pip && cp -f /usr/local/bin/pip /usr/local/bin/pip3

# Kunci stack GPU torch + numpy 2.x agar TAK ke-downgrade oleh library lain.
RUN printf 'numpy>=2.0,<3\ntorch==2.5.1+cu121\ntorchvision==0.20.1+cu121\ntorchaudio==2.5.1+cu121\n' \
        > /tmp/protect.txt

# 1) torch stack cu121 (GPU) — wheel tersedia utk cp310-cp313.
RUN python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121 && \
    { find /usr/local/lib /usr/lib -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; }

# 2) Core + seluruh requirements-compute.txt (pin sama dgn image 3.10).
COPY requirements-compute.txt /tmp/requirements-compute.txt
RUN python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        numpy pandas scipy scikit-learn matplotlib seaborn pillow networkx requests && \
    python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        -r /tmp/requirements-compute.txt && \
    { find /usr/local/lib /usr/lib -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; }

# 3) Data model NLP (nltk + spacy en_core_web_sm).
RUN python -m nltk.downloader -d "$NLTK_DATA" \
        punkt punkt_tab stopwords wordnet omw-1.4 \
        averaged_perceptron_tagger averaged_perceptron_tagger_eng vader_lexicon && \
    python -m spacy download en_core_web_sm

# 4) Library populer tambahan (sinkron dgn layer 5 image 3.10) + ipykernel utk
#    notebook interaktif. opencv headless dipaksa ulang (ultralytics menarik
#    varian non-headless).
COPY requirements-compute-extra.txt /tmp/requirements-compute-extra.txt
RUN python -m pip install -c /tmp/protect.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121 \
        -r /tmp/requirements-compute-extra.txt ipykernel jupyter_client && \
    python -m pip install --force-reinstall --no-deps opencv-python-headless==4.13.0.92 && \
    { find /usr/local/lib /usr/lib -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; } && \
    { rm -rf /root/.cache /tmp/* /usr/local/share/nltk_data/*.zip 2>/dev/null || true; }

WORKDIR /work
