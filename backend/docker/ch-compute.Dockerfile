# Image compute per-user ComputeHub (1 user 1 docker).
# Basis CUDA runtime + Python 3.10 + torch (cu121) + library sains inti.
# Tujuan: container per-user (ch-user-<id>) bisa MENJALANKAN job GPU. User dapat
# menambah library lain via pip ke volume /work miliknya sendiri.
#
# Build (memakai sudo passwordless yang SUDAH ada — TIDAK mengubah setelan docker):
#   sudo -n docker build -t ch-compute:latest -f backend/docker/ch-compute.Dockerfile backend/docker
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Python + toolchain minimal (git utk job berbasis repo).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3 /usr/local/bin/python

# torch cu121 (cocok dgn host) + library sains inti. Library lain bisa ditambah
# user via `pip install --target /work/...` ke volume mereka sendiri.
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install --index-url https://download.pytorch.org/whl/cu121 torch && \
    python3 -m pip install numpy pandas scipy scikit-learn matplotlib

WORKDIR /work
