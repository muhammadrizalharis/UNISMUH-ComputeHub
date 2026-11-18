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
| B1 | **Reservasi slot GPU** — memesan GPU untuk rentang waktu tertentu (mis. latihan model skripsi semalam) | Tinggi | L | Perlu aturan adil: batas durasi per pemesanan, persetujuan admin untuk slot panjang. |
| B2 | **Perkiraan waktu tunggu antrean** — menampilkan estimasi kapan job mulai berjalan | Sedang | M | Antrean dan prioritas job sudah ada; tinggal estimasi dari riwayat durasi. |
| B3 | **Laporan jam GPU bulanan per pengguna/fakultas** | Sedang | S | Data pemakaian sudah tercatat; perlu agregasi dan ekspor PDF/CSV untuk pimpinan. |

## C. Data & AI

| # | Fitur | Manfaat | Usaha | Catatan |
|---|---|---|---|---|
| C1 | **Dataset bersama (baca-saja)** — dataset umum (mis. MNIST, CIFAR, korpus Bahasa Indonesia) tersedia di semua notebook/Devbox tanpa unduh ulang | Tinggi | M | Hemat kuota pengguna dan bandwidth; pola serupa dengan `shared_models`. |
| C2 | **Tanya Dokumen pribadi** — pengguna mengunggah kumpulan dokumen (jurnal, materi kuliah) lalu bertanya kepada Asisten AI | Tinggi | M | Melanjutkan fondasi v1.41.0 (Tika + bge-m3 + Qdrant); satu koleksi per pengguna, dihitung dalam kuota. |
| C3 | **Pelacakan eksperimen** — melihat grafik TensorBoard dari job/notebook langsung di web | Sedang | M | TensorBoard sudah terpasang di image; perlu penampil yang aman per pengguna. |

## D. Operasional & keandalan (utang yang sudah diketahui)

| # | Pekerjaan | Manfaat | Usaha | Catatan |
|---|---|---|---|---|
| D1 | **Cadangan penuh susulan** — bila cadangan penuh hari Minggu terlewat (server mati), jalankan susulan otomatis | Tinggi | S | Penyebab arsip penuh sempat basi pada November. |
| D2 | **Pemeriksaan pengiriman email (SMTP)** | Sedang | S | Pernah gagal ("Connection unexpectedly closed"); notifikasi job dan peringatan bergantung padanya. |
| D3 | **Docling sesuai permintaan** — menyala saat dibutuhkan, berhenti saat menganggur | Sedang | S | Menghemat ±2,1 GB VRAM saat tidak dipakai. |
| D4 | **Pembaruan image `ch-compute`** agar versi pustaka sesuai berkas requirements | Rendah | S | Sekaligus menyertakan pembaruan keamanan terbaru. |
| D5 | **Pembatasan port layanan pihak lain** (Jupyter 1008, ComfyUI) ke `127.0.0.1`/Tailscale | Sedang | S | Perlu koordinasi dengan pemilik layanan. |

## Usulan urutan

1. **Gelombang 1 (cepat, berisiko rendah):** D1, D2, B3, D3.
2. **Gelombang 2 (nilai tinggi bagi pengguna):** C1, C2.
3. **Gelombang 3 (fitur besar):** A1 → A2 → A3/A4, lalu B1.

Urutan ini hanya saran. Butir mana pun dapat ditambah, digabung, atau dicoret
sesuai kebutuhan kampus.

## Pertanyaan untuk dibahas

- Apakah Ruang Kelas (A1) dibutuhkan semester ini, atau cukup berbagi templat?
- Untuk reservasi GPU (B1), berapa lama batas wajar satu pemesanan, dan perlukah persetujuan dosen pembimbing?
- Dataset apa saja yang paling sering dipakai mahasiswa (C1)?
- Apakah laporan jam GPU (B3) perlu dikelompokkan per fakultas/program studi?

## Langkah selanjutnya

1. Membahas dan memilih butir bersama admin.
2. Untuk butir terpilih, menyusun rincian teknis dan pengujian sebelum implementasi.
3. Memperbarui status dokumen ini setiap kali sebuah butir disepakati atau selesai.
