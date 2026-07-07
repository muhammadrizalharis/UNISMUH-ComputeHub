# UNISMUH ComputeHub

Platform orkestrasi job GPU ala Google Colab untuk server kampus bersama
(akses non-admin). Mahasiswa & dosen submit pekerjaan (kode, notebook, ZIP,
GitHub repo); semua **wajib berjalan di GPU**. Dilengkapi monitoring real-time,
kuota per-user, laporan penggunaan resource, dan peringatan batas (email + PDF).

## Fitur utama
- **Notebook interaktif (ala Colab/VS Code)** dari 4 sumber — tempel kode Python,
  unggah `.ipynb`, upload project `.zip`, atau clone GitHub repo — semuanya jalan
  di **kernel hidup di GPU** (variabel persist antar-sel, output langsung tampil).
  Dilengkapi **file explorer**, **unduh project (.zip)**, **ekspor notebook
  (.ipynb)**, dan **commit & push balik ke GitHub**. Sel & GPU baru aktif setelah
  kamu mulai/ unggah (hemat GPU di server bersama).
- **Submit job batch** (antrian + ETA, timeout, auto-`pip install`) tetap tersedia
  lewat halaman Daftar Job untuk eksekusi non-interaktif.
- **Penjadwal GPU-aware**: enforcement GPU (CPU ditolak), antrian + ETA,
  batas waktu otomatis (belajar dari riwayat), auto-`pip install`.
- **Kebijakan per-peran & per-mahasiswa**: kuota GPU harian, batas job paralel,
  plafon VRAM/RAM — diatur admin tanpa restart.
- **Monitoring live**: CPU/RAM/GPU dengan grafik besar, utilisasi & VRAM per GPU.
- **Laporan penggunaan resource** (mirip laporan HPC): siapa memakai GPU/CPU,
  analisis workload otomatis (OCR/training/diffusion/API/…), unduh HTML.
- **Peringatan batas** CPU/RAM/GPU/disk → kirim laporan **PDF ke email**.
- **Hemat CPU**: proses platform di-`nice` agar tidak mengganggu user lain.

## Antarmuka
Aplikasi web (SPA): React + TypeScript + Vite + Tailwind.

## Akses
Platform internal kampus — Fakultas Teknik, Informatika UNISMUH Makassar.
Akun dibuat oleh administrator; registrasi publik dinonaktifkan.

> Dokumentasi teknis (arsitektur, konfigurasi, environment, dan deployment)
> bersifat internal dan tidak disertakan di repositori publik ini.
