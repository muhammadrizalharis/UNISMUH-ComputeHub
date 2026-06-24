# UNISMUH ComputeHub

Platform orkestrasi job GPU ala Google Colab untuk server kampus bersama
(akses non-admin). Mahasiswa & dosen submit pekerjaan (kode, notebook, ZIP,
GitHub repo); semua **wajib berjalan di GPU**. Dilengkapi monitoring real-time,
kuota per-user, laporan penggunaan resource, dan peringatan batas (email + PDF).

## Fitur utama
- **Submit job** dari 4 sumber: tempel kode Python, notebook `.ipynb`
  (dieksekusi penuh + unduh hasil), upload project `.zip`, atau clone GitHub repo.
- **Penjadwal GPU-aware**: enforcement GPU (CPU ditolak), antrian + ETA,
  batas waktu otomatis (belajar dari riwayat), auto-`pip install`.
- **Kebijakan per-peran & per-mahasiswa**: kuota GPU harian, batas job paralel,
  plafon VRAM/RAM — diatur admin tanpa restart.
- **Monitoring live**: CPU/RAM/GPU dengan grafik besar, utilisasi & VRAM per GPU.
- **Laporan penggunaan resource** (mirip laporan HPC): siapa memakai GPU/CPU,
  analisis workload otomatis (OCR/training/diffusion/API/…), unduh HTML.
- **Peringatan batas** CPU/RAM/GPU/disk → kirim laporan **PDF ke email**.
- **Hemat CPU**: proses platform di-`nice` agar tidak mengganggu user lain.

## Arsitektur
- **Backend**: FastAPI (async), SQLAlchemy 2.0, SQLite (default) / PostgreSQL,
  penjadwal in-process (asyncio), NVML/`nvidia-smi` untuk GPU, `fpdf2` untuk PDF.
- **Frontend**: React + TypeScript + Vite + Tailwind (SPA, dilayani backend).

```
SERVER-KAMPUS/
├── backend/   # FastAPI app (app/), .env.example, requirements
└── frontend/  # React SPA (src/), Vite
```

## Menjalankan (development)

### Backend
```bash
cd backend
python3 -m venv --system-site-packages .venv   # mewarisi torch/psutil bila ada
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # lalu isi SECRET_KEY (acak), SMTP (opsional)
.venv/bin/python -m app.seed              # buat admin pertama (TANPA --demo utk produksi)
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8088
```

### Frontend
```bash
cd frontend
npm install
npm run build        # output ke dist/, otomatis dilayani backend
# atau: npm run dev  (mode pengembangan)
```

Buka `http://127.0.0.1:8088`.

## Konfigurasi penting (`.env`)
| Variabel | Keterangan |
|---|---|
| `SECRET_KEY` | **WAJIB** diganti string acak panjang |
| `ENFORCE_GPU` | `true` = job tanpa GPU ditolak |
| `PLATFORM_NICE` | prioritas CPU proses platform (15 = mengalah) |
| `SMTP_HOST` … | konfigurasi email peringatan (opsional) |
| `STUDENT_DAILY_GPU_SECONDS_QUOTA` | kuota GPU harian mahasiswa |

