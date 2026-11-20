# Rencana: Daftar Fitur ComputeHub v2

Status: **DRAF — bahan diskusi, belum ada yang disetujui untuk dikerjakan.**
Disusun atas permintaan admin (Muhammad Rizal Haris) setelah rilis v1.41.0.

## Tujuan v2

Versi 1.x sudah membangun fondasi: notebook & job GPU, Devbox, penyimpanan
berkuota, cadangan ke Drive, SSO + 2FA, Asisten AI, gateway Ollama, pemantauan,
dan peminjaman cadangan VRAM. Arah v2 yang diusulkan:

1. **Mendukung proses belajar-mengajar** (dosen ↔ mahasiswa), bukan hanya pemakaian perorangan.
2. **Pembagian GPU yang adil dan dapat direncanakan**, terutama menjelang tenggat tugas akhir.
3. **Menuntaskan utang operasional** agar platform tetap andal tanpa banyak campur tangan admin.

Setiap butir diberi perkiraan **manfaat** dan **usaha** (S = beberapa jam, M = 1–2 hari,
L = beberapa hari) sebagai bahan memilih prioritas.

## A. Pembelajaran (dosen & mahasiswa)

| # | Fitur | Manfaat | Usaha | Catatan |
|---|---|---|---|---|
| A1 | **Ruang Kelas** — dosen membuat kelas, mahasiswa bergabung dengan kode kelas | Tinggi | L | Peran `dosen` sudah ada, tetapi belum ada konsep kelas. Dasar bagi A2–A4. |
| A2 | **Bagikan notebook ke kelas** — dosen membagikan notebook/templat, mahasiswa mendapat salinan masing-masing | Tinggi | M | Memanfaatkan halaman Templat yang sudah ada. |
| A3 | **Kuota GPU per kelas** — dosen/admin menetapkan jatah jam GPU untuk satu kelas selama periode praktikum | Sedang | M | Melengkapi kuota GPU harian per mahasiswa yang sudah berjalan. |
| A4 | **Pantauan progres kelas** — dosen melihat siapa yang sudah menjalankan notebook/job dan statusnya | Sedang | M | Hanya ringkasan; isi kode mahasiswa tetap privat kecuali dibagikan. |

## B. Pembagian GPU

| # | Fitur | Manfaat | Usaha | Catatan |
|---|---|---|---|---|
| B1 | **Reservasi slot GPU** — memesan GPU untuk rentang waktu tertentu (mis. latihan model skripsi semalam) | Tinggi | L | ❌ Tidak dikerjakan (keputusan 19 Nov 2026): jadwal job dan antrean otomatis dianggap cukup. |
| B2 | **Perkiraan waktu tunggu antrean** — menampilkan estimasi kapan job mulai berjalan | Sedang | M | ✅ Selesai v1.42.3: tampilan posisi & ETA sudah ada sejak awal; kini simulasinya meniru scheduler (slot dari kebijakan admin, sesi interaktif tak memakai slot, jadwal, batas job per pengguna, kuota habis) dan estimasi durasi memakai median riwayat bila nama job belum pernah dijalankan. |
| B3 | **Laporan jam GPU bulanan per pengguna/fakultas** | Sedang | S | ✅ Selesai v1.42.0: Laporan → Jam GPU Bulanan (per pengguna & peran, unduh CSV). Pengelompokan per fakultas/prodi menunggu data fakultas di akun pengguna. |

## C. Data & AI

| # | Fitur | Manfaat | Usaha | Catatan |
|---|---|---|---|---|
| C1 | **Dataset bersama (baca-saja)** — dataset umum (mis. MNIST, CIFAR, korpus Bahasa Indonesia) tersedia di semua notebook/Devbox tanpa unduh ulang | Tinggi | M | ❌ Tidak dikerjakan (keputusan 19 Nov 2026). |
| C2 | **Tanya Dokumen pribadi** — pengguna mengunggah kumpulan dokumen (jurnal, materi kuliah) lalu bertanya kepada Asisten AI | Tinggi | M | ✅ Selesai v1.43.0: menu **Tanya Dokumen**. Berkas asli disimpan di `/persist/Dokumen-AI` (memakai kuota penyimpanan, tanpa batas jumlah/ukuran lain), diindeks di latar (Tika/Docling → bge-m3 → Qdrant, satu koleksi dengan filter `user_id`), jawaban mencantumkan sumber [D1]…; folder adalah sumber kebenaran sehingga berkas yang ditaruh/dihapus lewat Penyimpanan ikut tersinkron. |
| C3 | **Pelacakan eksperimen** — melihat grafik TensorBoard dari job/notebook langsung di web | Sedang | M | 🔜 Dijadwalkan (keputusan 19 Nov 2026). Hasil uji: TensorBoard di image `ch-compute` berfungsi, dan lewat Devbox sudah bisa dipakai (port forwarding VS Code). Yang belum ada: penampil di web ComputeHub untuk log job/notebook (proxy per pengguna dengan cek login, mati otomatis bila tidak dibuka). |

## D. Operasional & keandalan (utang yang sudah diketahui)

| # | Pekerjaan | Manfaat | Usaha | Catatan |
|---|---|---|---|---|
| D1 | **Cadangan penuh susulan** — bila cadangan penuh hari Minggu terlewat (server mati), jalankan susulan otomatis | Tinggi | S | ✅ Sudah ada sejak 15 Nov 2026 (`COMPUTEHUB_TAR_CATCHUP_DAYS=7` di `scripts/backup.sh`). |
| D2 | **Pemeriksaan pengiriman email (SMTP)** | Sedang | S | ✅ Selesai v1.42.0: uji login SMTP tiap 6 jam, Telegram admin saat gagal/pulih, status tampil di halaman Peringatan. |
| D3 | **Docling sesuai permintaan** — menyala saat dibutuhkan, berhenti saat menganggur | Sedang | S | ⏸️ Ditahan (18 Nov 2026): Docling sengaja tetap menyala agar tidak ada jeda cold start; ±2,1 GB VRAM GPU1 dianggap sepadan. |
| D4 | **Pembaruan image `ch-compute`** agar versi pustaka sesuai berkas requirements | Rendah | S | ✅ Selesai v1.42.2: pin dipecah per versi Python (transformers, mlxtend, geopandas butuh Python ≥3.11), salinan requirements kini dibandingkan per isi, dan `scripts/ensure_images.sh --rebuild` membangun ulang image + jangkar + cadangan sekali jalan. |
| D5 | **Pembatasan port layanan pihak lain** ke `127.0.0.1`/jaringan privat (rincian tidak ditulis di repo publik) | Sedang | S | ⏸️ Dibiarkan seperti sekarang (keputusan 18 Nov 2026). |

## Usulan urutan

1. **Gelombang 1 (cepat, berisiko rendah):** D1, D2, B3, D3.
2. **Gelombang 2 (nilai tinggi bagi pengguna):** B2, C2.
3. **Gelombang 3 (fitur besar):** A1 → A2 → A3/A4.

Urutan ini hanya saran. Butir mana pun dapat ditambah, digabung, atau dicoret
sesuai kebutuhan kampus.

## Pertanyaan untuk dibahas

- Apakah Ruang Kelas (A1) dibutuhkan semester ini, atau cukup berbagi templat?
- Apakah laporan jam GPU (B3) perlu dikelompokkan per fakultas/program studi?

## Langkah selanjutnya

1. Membahas dan memilih butir bersama admin.
2. Untuk butir terpilih, menyusun rincian teknis dan pengujian sebelum implementasi.
3. Memperbarui status dokumen ini setiap kali sebuah butir disepakati atau selesai.
