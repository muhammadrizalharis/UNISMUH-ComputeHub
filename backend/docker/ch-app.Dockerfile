# Image APLIKASI ComputeHub (backend FastAPI) — perintah Kaprodi 2026-08-03:
# "app kasi masuk di docker".
#
# Desain:
#   - Image = DEPENDENSI saja; kode backend + frontend dist di-BIND-MOUNT dari
#     host pada path yang IDENTIK -> update kode cukup restart (tanpa rebuild),
#     dan path -v yang dikirim app ke daemon (utk container job/kernel) tetap
#     sah karena daemon menafsirkan path di HOST.
#   - Klien docker TIDAK diinstal di sini: /usr/bin/docker host di-mount :ro
#     (selalu sinkron dgn versi daemon host). Akses via /var/run/docker.sock +
#     --group-add <gid docker host>.
#   - Jalan sebagai UID host (1015) -> file _jobs/log yang dibuat app tetap
#     milik user host; container kernel/job (juga uid 1015) bisa menulisnya.
#
# Build (context = backend/):
#   sudo -n docker build -t ch-app:latest -f docker/ch-app.Dockerfile .
FROM python:3.10-slim

# git: clone repo utk job source=git (dilakukan APP sebelum container job jalan)
# curl: health check / diagnosa; tzdata: laporan berzona WITA (TZ=Asia/Makassar)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
# cryptography: verifikasi JWKS SSO (RS256); fpdf2: PDF laporan/peringatan.
RUN pip install --no-cache-dir -r /tmp/requirements.txt cryptography fpdf2 \
    && rm -f /tmp/requirements.txt

# Kode di-mount ke path ini saat run (identik dgn host).
WORKDIR /home/muhammadrizalharis/DATA_ICAL/SERVER-KAMPUS/backend

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
