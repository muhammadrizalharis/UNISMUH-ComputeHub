// Riwayat versi platform. Satu versi = satu gelombang pengembangan nyata di repo
// (bukan penomoran otomatis per commit), supaya isinya bisa dibaca orang awam.

export const APP_VERSION = '1.15.0'

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
    version: '1.15.0',
    date: '24 September 2026',
    title: 'Unggah seret-lepas dan panel fleksibel',
    summary:
      'Penyimpanan menerima file maupun folder dengan drag-and-drop, dan lebar panel folder dapat disesuaikan tanpa mengubah data atau sesi komputasi.',
    highlights: [
      'Seret satu atau beberapa file/folder dari komputer ke Penyimpanan atau langsung ke folder tujuan. Struktur subfolder dan folder kosong dipertahankan.',
      'Tombol Unggah juga mendukung banyak file. Unggahan dikirim bertahap dengan indikator progres dan tetap mengikuti batas 256 MB per file.',
      'Pembatas panel folder dapat digeser atau diatur dengan keyboard; lebar tersimpan di browser. Klik ganda pembatas mengembalikan ukuran awal.',
      'Layar mobile tetap memakai susunan vertikal. Perubahan antarmuka menggunakan API yang sudah ada tanpa restart backend.',
    ],
  },
  {
    version: '1.14.0',
    date: '24 September 2026',
    title: 'Penyimpanan tanpa batas jumlah item',
    summary:
      'Folder proyek tidak lagi tersembunyi ketika workspace berisi lebih dari 4.000 item. Daftar dimuat per folder dan dilanjutkan saat digulir, tanpa batas total jumlah berkas.',
    highlights: [
      'Semua folder dan berkas pengguna dapat dijangkau, termasuk proyek yang urutannya setelah folder dataset besar.',
      'Isi folder dimuat ketika dibuka; halaman berikutnya dimuat saat digulir atau melalui tombol Muat berikutnya.',
      'Berlaku di halaman Penyimpanan dan explorer notebook, termasuk layar mobile. Pemuatan yang gagal dapat dicoba ulang.',
      'Data, kuota disk, batas unggahan, dan isolasi antar-pengguna tetap dipertahankan. Folder cache internal tetap disembunyikan seperti sebelumnya.',
    ],
  },
  {
    version: '1.13.0',
    date: '21 September 2026',
    title: 'VS Code Desktop dari mana saja, sekali pasang',
    summary:
      'VS Code Desktop di laptop sendiri kini menjadi cara utama memakai devbox: menyambung lewat alamat ComputeHub yang sama dengan browser — tanpa WiFi kampus, tanpa VPN, tanpa akun GitHub, dan tanpa mengatur SSH sendiri.',
    highlights: [
      'Menu Devbox menyediakan pemasang sekali-klik untuk Windows dan macOS/Linux. Jalankan sekali per laptop; kunci dan konfigurasi dipasang otomatis, tanpa hak administrator.',
      'Setelah itu cukup: F1 → Remote-SSH: Connect to Host → nama devbox Anda. Terminal, extension, debugger, dan GPU berjalan di server seperti biasa.',
      'Bisa dipakai dari rumah, kos, atau tethering — koneksi dibungkus HTTPS ke domain kampus, jadi tidak butuh VPN dan tidak melewati relay Microsoft yang sering tersendat.',
      'Devbox yang sedang mati menyala sendiri ketika Anda menyambung dari VS Code.',
      'Cukup 3 langkah: nyalakan devbox, dobel-klik pemasang, lalu klik "Buka di VS Code Desktop" — tidak ada perintah yang perlu dihafal dan VS Code tidak menanyakan platform.',
      'Laptop hilang? Tombol "buat kunci baru" mencabut akses laptop lama seketika. Akses hanya berlaku untuk devbox milik sendiri dan ikut mati bila akun dinonaktifkan.',
      'Jalur browser tetap tersedia sebagai pelengkap untuk komputer lab atau pinjaman, dan tunnel Microsoft masih ada sebagai cadangan di bagian "Cara lama".',
    ],
  },
  {
    version: '1.12.0',
    date: '21 September 2026',
    title: 'Devbox dibuka lewat alamat kampus',
    summary:
      'VS Code devbox kini terbuka langsung di browser melalui alamat ComputeHub, tanpa akun GitHub dan tanpa relay Microsoft yang sering tersendat dari jaringan kampus.',
    highlights: [
      'Tombol "Buka VS Code di browser" membuka IDE di tab baru melalui domain ComputeHub. Jalur ini tidak melewati layanan luar sehingga tidak terpengaruh gangguan jaringan kampus ke Azure.',
      'Devbox siap dalam hitungan detik: tidak ada lagi langkah kode otorisasi GitHub untuk pemakaian di browser.',
      'VS Code Desktop tetap tersedia sebagai pilihan: tunnel Microsoft disiapkan hanya saat diminta, dengan otorisasi GitHub sekali.',
      'Akses IDE dilindungi tiket sekali-pakai dan cookie sesi milik pemilik devbox; hanya pemilik yang dapat membukanya, dan logout memutus IDE.',
      'Deteksi koneksi dan penghentian otomatis memperhitungkan kedua jalur (browser dan Desktop). Bundel VS Code web dibagikan antar devbox agar pemakaian pertama tidak mengunduh ulang.',
    ],
  },
  {
    version: '1.11.0',
    date: '20 September 2026',
    title: 'Batas runtime per akun Linux',
    summary:
      'Administrator utama dapat memasang batas CPU dan RAM pada satu akun Linux langsung dari ComputeHub, tanpa terminal dan tanpa menimpa aturan admin IT.',
    highlights: [
      'Panel Akun Linux mendapat editor per akun: kuota CPU (core), RAM lunak, dan RAM maksimum. Hanya administrator utama; wajib mengetik ulang nama akun sebagai konfirmasi.',
      'Batas bersifat runtime: berlaku seketika dan hilang saat server reboot. Tombol "Kembalikan ke aturan sistem" melepas hanya aturan yang dipasang ComputeHub.',
      'Aturan yang sudah dipasang admin IT (drop-in permanen atau runtime pihak lain) dideteksi dan dilindungi — permintaan ditolak, bukan ditimpa.',
      'Setiap pemasangan dan pelepasan tercatat di Log Aktivitas Admin. Fitur dikendalikan LINUX_LIMITS_WRITE_ENABLED (default mati).',
      'Cakupan tetap proses login akun (SSH/terminal); container Docker dan VRAM GPU tidak tercakup.',
    ],
  },
  {
    version: '1.10.0',
    date: '20 September 2026',
    title: 'Panel akun Linux baca-saja',
    summary:
      'Administrator dapat melihat batas resource per akun Linux dari aturan aktif sistem, tanpa mengubah kebijakan admin IT.',
    highlights: [
      'Panel Akun Linux pada Pengaturan menampilkan kuota CPU, RAM lunak, RAM maksimum, serta batas PID dan thread per akun.',
      'Batas kelompok induk ikut diperhitungkan. Tidak ada nilai awal yang disalin dari kebijakan peran ComputeHub.',
      'Perubahan aturan Linux terbaca pada pembaruan otomatis; sumber batas dan indeks CPU efektif tersedia pada rincian akun.',
      'Akun tanpa slice aktif atau data yang belum terbaca tidak ditampilkan seolah tanpa batas. Proses Docker di luar slice dan VRAM dinyatakan di luar cakupan.',
      'Akses khusus admin, tanpa operasi Simpan atau perubahan OS. Pengaturan batas sungguhan melalui UI belum diaktifkan.',
    ],
  },
  {
    version: '1.9.0',
    date: '20 September 2026',
    title: 'Devbox berhenti setelah VS Code terputus',
    summary:
      'Devbox membebaskan sumber daya secara otomatis saat pengguna meninggalkan VS Code, dengan jeda untuk menyambung kembali.',
    highlights: [
      'Penghentian otomatis setelah semua koneksi VS Code terputus selama dua menit secara bawaan, diperiksa berkala.',
      'Menyambung kembali membatalkan penghentian; menutup satu jendela tidak mematikan devbox jika jendela lain masih tersambung.',
      'Status koneksi dan hitung mundur tampil di halaman Devbox. Kejadian putus, sambung ulang, dan alasan berhenti masuk jejak audit.',
      'Program di dalam devbox ikut berhenti, tetapi container dan berkas tersimpan tidak dihapus. Reservasi GPU dilepas setelah container berhasil dihentikan.',
      'Panduan web, bot bantuan, dan PDF diperbarui; Job Batch tetap tersedia untuk pekerjaan yang harus berjalan setelah VS Code ditutup.',
    ],
  },
  {
    version: '1.8.0',
    date: '19 September 2026',
    title: 'Audit & Penyimpanan',
    summary:
      'Setiap sesi Devbox kini meninggalkan jejak audit lengkap, dan halaman Penyimpanan bisa menerima unggahan satu folder utuh.',
    highlights: [
      'Jejak audit Devbox: siapa menyalakan/menghentikan (pemilik, admin, atau sistem), kapan, kenapa, lama menyala, dan waktu GPU yang benar-benar terpakai — semua terbaca di halaman detail job.',
      'Halaman detail job Devbox dibenahi: jenis job jelas, log daur hidup tampil, dan label "Waktu GPU dipakai" menjelaskan angka yang dulu membingungkan.',
      'Unggah folder utuh di halaman Penyimpanan — struktur subfolder dipertahankan, dikirim berpotong-potong sehingga folder besar tetap lolos batas jaringan kampus.',
      'Halaman Riwayat Versi publik (/rilis) dengan lencana versi di footer situs.',
      'Perbaikan ketahanan pengujian saat pengumuman/pemeliharaan sedang aktif.',
    ],
  },
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
