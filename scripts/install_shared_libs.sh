#!/usr/bin/env bash
# Pasang library PUBLIK/BERSAMA (read-only overlay) untuk SEMUA user & job.
#
# Konsep: library ini dipasang SEKALI ke folder bersama ($SHARED_DIR), lalu di-mount
# read-only ke setiap container job & kernel (path /opt/ch-shared) + masuk PYTHONPATH.
# Hemat disk (tak terduplikasi per user) & tak perlu rebuild image. Library milik USER
# (requirements.txt / pip --user) TETAP masuk ruang user sendiri dan DIPRIORITASKAN.
#
# Cara pakai:
#   bash scripts/install_shared_libs.sh              # pasang/segarkan set default
#   EXTRA="line_profiler seaborn" bash scripts/install_shared_libs.sh   # tambah paket
#
# CATATAN: paket yang OVERLAP dengan image dasar DIPIN ke versi image (constraints) supaya
# tidak menimpa/merusak torch dkk. Instalasi memakai pip DI DALAM image (versi cocok).
set -euo pipefail

IMAGE="${IMAGE:-ch-compute:latest}"
DOCKER="${DOCKER:-sudo -n /usr/bin/docker}"
SHARED_DIR="${SHARED_DIR:-$HOME/.computehub/shared_pydeps}"

# Daftar library umum yang SERING & KADANG dipakai (di luar yang sudah ada di image dasar:
# numpy, pandas, scipy, scikit-learn, matplotlib, seaborn, plotly, torch, torchvision,
# transformers, nltk, xgboost, lightgbm, statsmodels, pillow, requests, tqdm, tensorflow-cpu).
LIBS=(
  opencv-python-headless   # computer vision (cv2)
  cupy-cuda12x             # array GPU ala numpy
  polars pyarrow           # dataframe cepat + arrow
  openpyxl xlsxwriter xlrd tabulate  # Excel/tabel
  networkx                 # graph
  numba                    # JIT
  h5py                     # HDF5
  scikit-image imageio     # image processing
  beautifulsoup4 lxml      # scraping/parsing
  gdown                    # unduh Google Drive publik
  gensim wordcloud         # NLP/topik + word cloud
  pymupdf pypdf python-docx  # baca PDF/DOCX
  sqlalchemy               # ORM/DB
)
# Paket tambahan opsional via env EXTRA (dipisah spasi).
read -r -a EXTRA_ARR <<<"${EXTRA:-}"

mkdir -p "$SHARED_DIR"
echo "==> Overlay bersama : $SHARED_DIR"
echo "==> Image           : $IMAGE"

# 1) Ambil versi paket image dasar sebagai CONSTRAINTS (agar overlap dipin ke versi image).
CONSTRAINTS="$(mktemp)"
trap 'rm -f "$CONSTRAINTS"' EXIT
$DOCKER run --rm "$IMAGE" python -m pip freeze 2>/dev/null | grep -vE ' @ |^-e ' >"$CONSTRAINTS"
echo "==> Constraints base: $(wc -l <"$CONSTRAINTS") paket"

# 2) Pasang ke overlay memakai pip DI DALAM image (versi/ABI cocok), dengan constraints.
$DOCKER run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$SHARED_DIR:/shared" -v "$CONSTRAINTS:/c.txt:ro" "$IMAGE" \
  python -m pip install --no-cache-dir --disable-pip-version-check \
  --target /shared -c /c.txt "${LIBS[@]}" "${EXTRA_ARR[@]}"

echo "==> Ukuran overlay  : $(du -sh "$SHARED_DIR" | cut -f1)"

# 3) Uji cepat: torch tetap jalan + beberapa library baru bisa di-import.
echo "==> Uji kompatibilitas (torch + library baru):"
$DOCKER run --rm --runtime nvidia -e NVIDIA_VISIBLE_DEVICES=0 \
  -e PYTHONPATH=/opt/ch-shared -v "$SHARED_DIR:/opt/ch-shared:ro" "$IMAGE" \
  python -c "import torch,numpy,cv2,polars,cupy; print('OK torch',torch.__version__,'cuda',torch.cuda.is_available(),'| cv2',cv2.__version__)" \
  2>&1 | grep -vE 'WARNING|encryption|eavesdrop|CurveZMQ|TCP' | tail -2

echo "Selesai. Semua job & kernel BARU otomatis mendapat library ini."
