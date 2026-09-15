// Riwayat versi platform. Satu versi = satu gelombang pengembangan nyata di repo
// (bukan penomoran otomatis per commit), supaya isinya bisa dibaca orang awam.

export const APP_VERSION = '1.7.0'

export type Release = {
  version: string
  date: string // tanggal rilis, format Indonesia
  title: string
  summary: string
  highlights: string[]
}

/** Terbaru di urutan pertama. */
export const RELEASES: Release[] = [
  {
    version: '1.7.0',
    date: '15 September 2026',
    title: 'Devbox & keandalan',
    summary:
      'Mahasiswa bisa memakai VS Code miliknya sendiri dengan tenaga server kampus, ditambah pembenahan besar pada jaringan dan pencadangan.',
    highlights: [
      'Devbox: ngoding di VS Code sendiri (laptop atau peramban), komputasi tetap di server.',
      'Panel Devbox untuk admin + deteksi menganggur agar GPU tidak tertahan percuma.',
      'Laporan bulanan diperluas jadi 14 seksi dan sesi notebook kini meninggalkan jejak audit.',
      'Cadangan tahan-ransomware, arsip mingguan, dan pemeriksaan integritas otomatis.',
      'Perbaikan jaringan (MTU 1400) yang menyembuhkan Devbox, job, dan kernel yang gagal tersambung dari jaringan kampus.',
      'Isolasi antar-kontainer diperketat: pekerjaan milik pengguna berbeda tidak bisa saling menghubungi.',
    ],
  },
  {
    version: '1.6.0',
    date: '17 Agustus 2026',
    title: 'Laporan lengkap & dockerisasi',
    summary:
      'Laporan pemakaian jadi dokumen yang bisa dipertanggungjawabkan, dan layanan inti dipindah ke kontainer.',
    highlights: [
      'Backend berjalan di dalam Docker sehingga lebih mudah dipulihkan.',
      'Laporan server menjadi PDF lengkap: riwayat harian, rincian per jam, temuan, dan rekomendasi.',
      'Atribusi pemakai layanan AI bersama — terlihat siapa memakai berapa.',
      'Pengukuran RAM/VRAM per job diperbaiki (sebelumnya selalu nol karena memantau proses yang keliru).',
      'Job dua GPU eksklusif dan sesi login terpisah per tab peramban.',
      'Explorer berkas banyak tab + menu klik-kanan; identitas situs & SEO dibenahi.',
    ],
  },
  {
    version: '1.5.0',
    date: '31 Juli 2026',
    title: 'Operasional & pengawasan',
    summary:
      'Platform mulai bisa menjaga dirinya sendiri: memberi kabar saat bermasalah dan punya jalur pemulihan.',
    highlights: [
      'Mode pemeliharaan dan bot operator Telegram (status, GPU, job, cadangan).',
      'Peringatan penting dikirim lewat email sekaligus Telegram; ada pemantau dari luar server.',
      'Cadangan luar-situs terenkripsi ke Google Drive + skrip pemulihan produksi.',
      'Menu Saran untuk semua peran dan log aktivitas admin.',
      'Peran mengikuti pintu masuk: satu orang bisa masuk sebagai dosen lewat SSO atau sebagai admin lewat pintu admin.',
      'Halaman Kebijakan Privasi, Syarat & Ketentuan, Cookie, dan Hak Cipta.',
    ],
  },
  {
    version: '1.4.0',
    date: '23 Juli 2026',
    title: 'Satu pintu SSO & wajah baru',
    summary:
      'Masuk cukup dengan akun kampus, dan tampilan platform dirombak agar layak dipakai sehari-hari.',
    highlights: [
      'Login satu pintu lewat SSO UNISMUH (Keycloak, OIDC + PKCE).',
      'Mode gelap di seluruh aplikasi.',
      'Halaman Landing dan Login didesain ulang beserta animasinya.',
      'Terminal web di dalam notebook (bash + git) untuk perintah yang butuh interaksi.',
      'Galeri template notebook siap pakai + model AI bersama (Whisper, YOLO, IndoBERT, OCR).',
      'Panduan mahasiswa dalam bentuk PDF yang bisa diunduh.',
    ],
  },
  {
    version: '1.3.0',
    date: '9 Juli 2026',
    title: 'Asisten AI & basis data kampus',
    summary:
      'Asisten AI berjalan penuh di server kampus, dan basis data dipindahkan dari cloud ke kampus.',
    highlights: [
      'Asisten AI memakai Ollama di server kampus — tanpa kunci API dan tanpa biaya langganan.',
      'Model AI dapat diatur per peran maupun per pengguna oleh admin.',
      'Asisten AI bisa membaca gambar (grafik/tangkapan layar) dan menimpa sel lewat tombol Terapkan.',
      'Basis data pindah ke server kampus sehingga jauh lebih cepat.',
      'Unduh satu folder atau seluruh ruang kerja sebagai .zip.',
      'Halaman Bantuan yang isinya menyesuaikan peran pembacanya.',
    ],
  },
  {
    version: '1.2.0',
    date: '30 Juni 2026',
    title: 'Isolasi per pengguna',
    summary:
      'Setiap pengguna mendapat ruang kerjanya sendiri yang tidak bisa diintip pengguna lain.',
    highlights: [
      'Satu pengguna satu kontainer: job dan kernel berjalan terisolasi, tanpa hak root.',
      'Penyimpanan pribadi permanen (/persist) + halaman Penyimpanan untuk menjelajah, unggah, unduh, dan hapus berkas.',
      'Jaringan kernel dipisahkan dari layanan lain yang berjalan di server bersama.',
      'Keamanan sesi: satu perangkat per akun, token penyegar, dan header keamanan.',
      'Halaman Landing publik pertama.',
      'Kuota penyimpanan per pengguna, simpan otomatis notebook, cadangan harian, dan pengujian otomatis.',
    ],
  },
  {
    version: '1.1.0',
    date: '26 Juni 2026',
    title: 'Notebook interaktif & berbagi GPU',
    summary:
      'Bekerja langsung di peramban ala Google Colab, dan satu GPU bisa dipakai beberapa orang.',
    highlights: [
      'Notebook interaktif dengan kernel Python hidup — variabel bertahan antar sel.',
      'Explorer berkas, pratinjau, dan ekspor .ipynb lengkap dengan outputnya.',
      'Batas CPU/RAM/VRAM per peran, plus penyesuaian khusus per pengguna.',
      'Antrean otomatis dan berbagi GPU yang sadar VRAM (beberapa sesi dalam satu GPU).',
      'Dukungan job CPU, bukan hanya GPU.',
      'Asisten AI di panel kanan notebook, serta halaman Profil dengan foto.',
    ],
  },
  {
    version: '1.0.0',
    date: '24 Juni 2026',
    title: 'Fondasi platform',
    summary:
      'Rilis pertama: mengantre dan menjalankan pekerjaan GPU secara tertib untuk banyak pengguna.',
    highlights: [
      'Penjadwal sadar-GPU: pekerjaan menunggu giliran, satu job satu GPU.',
      'Dashboard pemantauan GPU, CPU, dan RAM secara langsung.',
      'Akun dan peran mahasiswa, dosen, serta admin.',
      'Empat cara mengirim pekerjaan: tempel kode, notebook .ipynb, unggah ZIP, dan repositori GitHub.',
      'Kuota GPU harian dan batas waktu per pekerjaan yang ditentukan otomatis.',
      'Pengamanan dasar: pembatasan percobaan login, pembersihan berkas lama, dan rotasi log.',
    ],
  },
]
