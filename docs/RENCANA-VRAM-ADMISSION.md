# Rencana — Pisahkan Admission VRAM dari Plafon (cap jalan-waktu, bukan syarat masuk)

> Status: **USULAN / BELUM DIKERJAKAN**. Dokumen rencana; tidak ada perubahan kode/perilaku
> yang sudah diterapkan. Dibuat: 2026-11-08.

## Masalah yang dilaporkan

Saat pengguna menyetel **batas maks VRAM** sebuah job/sesi (mis. **40 GB**) — atau mencentang
**izinkan job 2 GPU** — sistem sekarang **menunggu sampai VRAM bebas sebesar batas itu** baru job
boleh memakai GPU. Akibatnya job tertahan di antrian walau GPU sebenarnya masih bisa dimulai.

**Perilaku yang diinginkan:**
1. **Admission longgar** — job boleh **masuk** selama ada VRAM bebas minimal (mis. cukup untuk
   mulai; walau sisa hanya ratusan MB), **bukan** harus menunggu 40 GB kosong lebih dulu.
2. **Plafon ditegakkan saat proses berjalan** — batas 40 GB berlaku sebagai **cap jalan-waktu**.
   Jika kode user mencoba memakai 60 GB, **prosesnya yang gagal/OOM ("ambar")**, **bukan** ditolak
   saat masuk, dan **bukan** dialihkan ke CPU.

## Temuan kode (terverifikasi)

### Penegakan plafon saat jalan — SUDAH ADA ✅
- `backend/runtime/vram_guard/sitecustomize.py` di-mount read-only ke `/opt/ch-vram` + masuk
  `PYTHONPATH`, lalu menegakkan plafon di lapisan framework:
  - PyTorch: `torch.cuda.set_per_process_memory_fraction(cap/total, idx)`
  - TensorFlow: `LogicalDeviceConfiguration(memory_limit=cap)`
- Melebihi plafon → **OutOfMemoryError pada proses user itu**, tidak mengorbankan proses lain.
  **Ini persis perilaku "ambar" yang diinginkan.**
- Diaktifkan lewat env `CH_MAX_VRAM_MB` (job) / `CH_K_VRAM_MB` (kernel), yang hanya dipasang bila
  `settings.VRAM_HARD_LIMIT = True`. **Default saat ini `False`** (lihat `backend/app/core/config.py:330`).

### Admission terlalu ketat — SUMBER MASALAH ❌
`backend/app/services/gpu.py` → `pick_gpu_for(required_mb)` menolak GPU bila salah satu gagal:
1. jumlah beban kerja di GPU ≥ `GPU_MAX_WORKLOADS_PER_GPU` (default 4), **atau**
2. `planned_mb + required_mb > usable_total` (reservasi anti-overcommit antar beban kerja kita), **atau**
3. **`gpu.mem_free_mb < required_mb + headroom`** ← inilah yang memaksa "tunggu 40 GB kosong dulu"
   (`GPU_SHARE_HEADROOM_MB` default 2048).

Untuk **job 2 GPU** (`scheduler.py`, cabang `multi_gpu`): butuh **kedua GPU benar-benar kosong**
dari semua reservasi (`reservations.count/planned == 0`) → eksklusif, menunggu sampai bersih total.

## Usulan perubahan

Pisahkan **"anggaran reservasi / syarat masuk"** dari **"plafon jalan-waktu"**:

- **Admission** cukup mensyaratkan VRAM bebas ≥ **ambang-mulai kecil** (mis. `GPU_MIN_FREE_MEMORY_MB`,
  default 1024 MB), **bukan** `required_mb` penuh. Tambahkan setelan terpisah, mis.
  `GPU_ADMIT_MIN_FREE_MB`, agar "ambang masuk" ≠ "plafon pakai".
- **Plafon** (`required_mb`/max VRAM) **hanya** dipakai oleh `vram_guard` sebagai cap jalan-waktu.
- **Wajib mengaktifkan `VRAM_HARD_LIMIT = True`** — kalau admission dilonggarkan tanpa penegakan
  jalan-waktu, job bisa saling tabrak VRAM tanpa batas. Penegakan adalah syarat keamanan fitur ini.

## ⚠️ Trade-off & risiko yang harus diputuskan

1. **Overcommit → tabrakan antar job yang "patuh".** Walau tiap proses dibatasi plafonnya, bila
   **jumlah plafon** di satu GPU melebihi VRAM fisik (mis. 2× job @40 GB di GPU 46 GB), kedua job
   bisa sama-sama di bawah plafonnya tapi **totalnya melewati kapasitas fisik** → OOM menimpa job
   yang tak bersalah. Reservasi (syarat #2 saat ini) mencegah ini; model longgar menukarnya dengan
   utilisasi. Perlu keputusan: **izinkan overcommit (risiko OOM "undian")** atau **tetap jaga jumlah
   plafon ≤ VRAM fisik** (lebih aman, tapi sebagian sifat "masuk walau sisa 500 MB" berkurang).
2. **Penegakan hanya untuk PyTorch & TensorFlow.** Framework lain (JAX, CuPy, llama.cpp, binari
   CUDA mentah) **tidak** terbatasi hook ini → bisa melewati plafon dan menabrak tetangga. "Hard cap"
   belum universal.
3. **Alternatif penegakan keras**: **MPS** (`CUDA_MPS_PINNED_DEVICE_MEM_LIMIT`) atau **MIG** memberi
   partisi VRAM yang ditegakkan di tingkat driver/hardware (universal), tapi dengan keterbatasan
   konfigurasi (MIG = ukuran tetap; MPS = satu pengguna/konteks). Pertimbangkan bila cakupan
   framework-level dirasa kurang.

## Rencana implementasi (bertahap, aman)

1. Tambah setelan `GPU_ADMIT_MIN_FREE_MB` (default = `GPU_MIN_FREE_MEMORY_MB`) — "ambang masuk".
2. Ubah `pick_gpu_for`: syarat #3 pakai `GPU_ADMIT_MIN_FREE_MB` (bukan `required_mb`). Beri opsi
   `GPU_ALLOW_OVERCOMMIT` untuk melonggarkan syarat #2 (reservasi) bila overcommit diizinkan.
3. Untuk job 2 GPU: longgarkan syarat "kedua GPU kosong total" bila overcommit diizinkan
   (atau sediakan mode "butuh N GPU dengan ambang bebas minimal", bukan eksklusif penuh).
4. **Aktifkan `VRAM_HARD_LIMIT = True`** dan verifikasi `vram_guard` memang membatasi (ada uji
   `backend/tests/test_vram_guard.py`).
5. Uji skenario: (a) job masuk saat free kecil, (b) proses melewati plafon → OOM job itu saja,
   (c) dua job berbagi GPU tanpa menabrak bila jumlah plafon ≤ fisik, (d) perilaku job 2 GPU.
6. Pantau beberapa hari; siapkan rollback (kembalikan `pick_gpu_for` ke syarat free ≥ `required_mb`
   dan matikan overcommit) bila terjadi OOM beruntun.

## Berkas terkait

- `backend/app/services/gpu.py` — `pick_gpu_for`, `usable_total_mb`, ambang `GPU_*`.
- `backend/app/services/scheduler.py` — admission job GPU & cabang `multi_gpu`.
- `backend/app/services/reservations.py` — anggaran VRAM (`budget_mb`, `planned_mb`, `count`).
- `backend/app/services/provision.py` — `vram_guard_argv` (inject `CH_MAX_VRAM_MB`).
- `backend/runtime/vram_guard/sitecustomize.py` — penegakan plafon per-proses.
- `backend/app/core/config.py` — `VRAM_HARD_LIMIT`, `GPU_MIN_FREE_MEMORY_MB`,
  `GPU_SHARE_HEADROOM_MB`, `GPU_MAX_WORKLOADS_PER_GPU`, `GPU_SHARE_ENABLED`.
