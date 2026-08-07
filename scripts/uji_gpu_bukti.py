"""Uji bukti pemakaian GPU di UNISMUH ComputeHub.

Cara pakai (pilih salah satu):
  1. Web  : menu "Tempel Kode" -> salin seluruh isi berkas ini -> pilih device GPU -> Jalankan.
  2. Notebook: salin ke satu sel lalu jalankan.
  3. Server: python uji_gpu_bukti.py

Skrip ini sengaja berjalan ~60 detik dengan beban GPU yang KONSTAN. Alasannya:
pemantau mencuplik tiap 5 detik, jadi beban yang terlalu singkat tidak akan
terekam sebagai VRAM/utilisasi pada Laporan. Sesudah selesai, buka
Laporan -> Riwayat Pemakaian Harian -> tab ComputeHub untuk membandingkan angka.
"""

import platform
import time

import torch

DETIK_BEBAN = 60  # durasi beban berkelanjutan
UKURAN_MATRIKS = 4096  # ukuran matriks untuk pembanding CPU vs GPU
TARGET_VRAM_GB = 3.0  # GPU dipakai bersama -> jangan rakus


def judul(teks: str) -> None:
    print(f"\n{'=' * 64}\n{teks}\n{'=' * 64}", flush=True)


judul("1. LINGKUNGAN")
print(f"Python        : {platform.python_version()}", flush=True)
print(f"PyTorch       : {torch.__version__}", flush=True)
print(f"CUDA tersedia : {torch.cuda.is_available()}", flush=True)

if not torch.cuda.is_available():
    print(
        "\nGPU TIDAK terlihat dari proses ini.\n"
        "Pastikan job dikirim dengan device = GPU (bukan CPU).",
        flush=True,
    )
    raise SystemExit(1)

dev = torch.device("cuda")
props = torch.cuda.get_device_properties(0)
vram_total_gb = props.total_memory / 1024**3
print(f"CUDA (torch)  : {torch.version.cuda}", flush=True)
print(f"GPU           : {props.name}", flush=True)
print(f"VRAM total    : {vram_total_gb:.1f} GB", flush=True)
print(f"Jumlah SM     : {props.multi_processor_count}", flush=True)


judul("2. PEMBANDING CPU vs GPU (perkalian matriks)")
n = UKURAN_MATRIKS
print(f"Matriks {n}x{n} float32, 3 kali ulangan.\n", flush=True)

a_cpu = torch.randn(n, n)
b_cpu = torch.randn(n, n)

t0 = time.perf_counter()
for _ in range(3):
    hasil_cpu = a_cpu @ b_cpu
detik_cpu = (time.perf_counter() - t0) / 3

a_gpu = a_cpu.to(dev)
b_gpu = b_cpu.to(dev)
for _ in range(3):  # pemanasan: kompilasi kernel & alokasi awal tidak ikut diukur
    _ = a_gpu @ b_gpu
torch.cuda.synchronize()

t0 = time.perf_counter()
for _ in range(3):
    hasil_gpu = a_gpu @ b_gpu
torch.cuda.synchronize()
detik_gpu = (time.perf_counter() - t0) / 3

# GFLOPS: satu perkalian matriks n x n butuh 2*n^3 operasi.
flop = 2 * n**3
selisih = (hasil_cpu - hasil_gpu.cpu()).abs().max().item()

print(f"CPU  : {detik_cpu * 1000:8.1f} ms/ulangan  ({flop / detik_cpu / 1e9:7.1f} GFLOPS)", flush=True)
print(f"GPU  : {detik_gpu * 1000:8.1f} ms/ulangan  ({flop / detik_gpu / 1e9:7.1f} GFLOPS)", flush=True)
print(f"GPU {detik_cpu / detik_gpu:.1f}x lebih cepat daripada CPU.", flush=True)
print(f"Selisih hasil maks {selisih:.2e} (wajar untuk float32 -> hasil setara).", flush=True)

del a_cpu, b_cpu, hasil_cpu, hasil_gpu
torch.cuda.empty_cache()


judul(f"3. BEBAN BERKELANJUTAN {DETIK_BEBAN} DETIK (agar terekam pemantau)")
# Isi VRAM sampai sekitar target, lalu putar perkalian matriks tanpa henti.
elemen = int(TARGET_VRAM_GB * 1024**3 / 4)  # float32 = 4 byte
sisi = int(elemen**0.5 / 2)
bantalan = torch.randn(sisi, sisi, device=dev)
kerja_a = torch.randn(2048, 2048, device=dev)
kerja_b = torch.randn(2048, 2048, device=dev)

print(f"VRAM dialokasikan : {torch.cuda.memory_allocated() / 1024**3:.2f} GB", flush=True)
print(f"VRAM dicadangkan  : {torch.cuda.memory_reserved() / 1024**3:.2f} GB", flush=True)
print("Menjalankan beban… (laporan progres tiap 10 detik)\n", flush=True)

mulai = time.perf_counter()
putaran = 0
lapor_berikut = 10.0
while True:
    berlalu = time.perf_counter() - mulai
    if berlalu >= DETIK_BEBAN:
        break
    kerja_a = (kerja_a @ kerja_b).clamp_(-3, 3)  # clamp: cegah nilai meledak jadi inf
    bantalan.mul_(1.0001)
    putaran += 1
    if berlalu >= lapor_berikut:
        torch.cuda.synchronize()
        print(
            f"  {berlalu:5.1f} dtk | {putaran:6d} putaran | "
            f"VRAM {torch.cuda.memory_allocated() / 1024**3:.2f} GB",
            flush=True,
        )
        lapor_berikut += 10.0

torch.cuda.synchronize()
total = time.perf_counter() - mulai
puncak_gb = torch.cuda.max_memory_allocated() / 1024**3


judul("4. RINGKASAN — bandingkan dengan Laporan ComputeHub")
print(f"Durasi beban        : {total:.1f} detik", flush=True)
print(f"Putaran matmul      : {putaran:,}", flush=True)
print(f"VRAM puncak (torch) : {puncak_gb:.2f} GB  (~{puncak_gb * 1024:.0f} MB)", flush=True)
print(f"GPU dipakai         : {props.name}", flush=True)
print(
    "\nAngka 'VRAM puncak' pada Laporan biasanya SEDIKIT LEBIH BESAR dari angka di\n"
    "atas, karena Laporan mengukur seluruh pemakaian proses di GPU (termasuk konteks\n"
    "CUDA ~300-500 MB), sedangkan angka di atas hanya tensor milik program ini.",
    flush=True,
)
print("\nSELESAI — pemakaian GPU terbukti dan sudah terekam.", flush=True)
