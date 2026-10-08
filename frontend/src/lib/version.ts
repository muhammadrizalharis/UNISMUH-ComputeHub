// Riwayat versi platform. Satu versi = satu gelombang pengembangan nyata di repo
// (bukan penomoran otomatis per commit), supaya isinya bisa dibaca orang awam.

export const APP_VERSION = '1.20.1'

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
    version: '1.20.1',
    date: '9 Oktober 2026',
    title: 'Menu Cadangan & Pemulihan tersendiri',
    summary:
      'Cadangan & Pemulihan dipindah dari halaman Pengaturan menjadi menu Admin tersendiri di sidebar (Laporan · Peringatan · Pengguna · Cadangan & Pemulihan · Pengaturan).',
    highlights: [
      'Halaman /backup khusus: status cadangan, riwayat & bukti audit, Backup sekarang, Detail Backup, sumber pemulihan, uji pulih, dan wizard restore berada di satu tempat tanpa bercampur dengan pengaturan kebijakan.',
      'Halaman Pengaturan kembali ringkas: kebijakan platform, pengumuman, akun Linux, permintaan kuota, dan log aktivitas admin.',
    ],
  },
  {
    version: '1.20.0',
    date: '9 Oktober 2026',
    title: 'Backup & pemulihan dari web',
    summary:
      'Cadangan tidak lagi hanya bukti: administrator utama dapat membuat backup penuh, melihat rincian isi tiap backup, menguji pulih, dan memulihkan database/workspace langsung dari web — dengan titik rollback otomatis.',
    highlights: [
      'Tombol "Backup sekarang": arsip tar penuh (database + workspace + konfigurasi + log eksekusi) dibuat saat itu juga, dienkripsi, diunggah ke Drive, dan ditambah snapshot restic — tanpa menunggu jadwal Minggu.',
      '"Detail Backup" untuk setiap arsip: total ukuran, durasi, salinan off-site, isi PostgreSQL (nama db, ukuran dump, jumlah tabel, perkiraan baris, roles/globals), workspace per akun, komponen lain (.env, agen, log), verifikasi SHA256, waktu & lingkungan, dan daftar berkas.',
      'Tab "Sumber pemulihan": arsip di server, snapshot restic harian, salinan Google Drive, dan titik rollback — masing-masing bisa diuji pulih (Postgres sementara) atau dipulihkan ke produksi.',
      'Wizard restore dengan pilihan cakupan (database / workspace pengguna / konfigurasi), pemeriksaan sesi berjalan & agen host, tombol nyalakan mode pemeliharaan, dan frasa konfirmasi; progres dan log tampil langsung.',
      'Setiap restore otomatis menyimpan kondisi sebelum ditimpa sebagai titik rollback yang bisa dipulihkan kembali dari web.',
      'Eksekusi dilakukan agen di server (computehub-ops-agent), bukan oleh aplikasi web; semua tindakan tercatat di Log Aktivitas Admin dan bukti cadangan.',
    ],
  },
  {
    version: '1.19.0',
    date: '6 Oktober 2026',
    title: 'Kuota penyimpanan: peringatan bertahap & ajukan tambahan kuota',
    summary:
      'Kuota penyimpanan kini ditegakkan: saat penuh, unggahan serta job/notebook/Devbox baru ditolak (berkas tetap aman). Pengguna diperingatkan bertahap di 80/90/100% dan bisa mengajukan tambahan kuota langsung dari web untuk diputuskan admin.',
    highlights: [
      'Spanduk kuota di semua halaman: kuning mulai 80%, merah saat penuh, lengkap dengan pemakaian dan tombol "Ajukan tambahan kuota".',
      'Notifikasi lonceng + email dikirim sekali per tahap (80%, 90%, 100%), tidak berulang-ulang.',
      'Formulir pengajuan tambahan kuota (besaran GB + alasan); satu permintaan menunggu per akun, status tampil di spanduk dan halaman Penyimpanan.',
      'Pengaturan > Permintaan Kuota Penyimpanan untuk admin: setujui dengan besaran GB atau tolak dengan catatan; pemohon diberi tahu dan kuota naik otomatis, tercatat di audit.',
      'Pesan penolakan unggahan/job saat kuota penuh menjelaskan langkah selanjutnya (hapus berkas atau ajukan tambahan kuota).',
      'Plafon VRAM kini ditegakkan di dalam container ComputeHub (job, notebook, dan Devbox): PyTorch/TensorFlow dibatasi sebesar plafon akun, sehingga satu akun tidak bisa menghabiskan kartu GPU bersama. Batasnya tetap diatur lewat kebijakan per-user.',
      'Riwayat versi (halaman ini) kini khusus admin & super admin; pengguna biasa hanya melihat nomor versinya.',
    ],
  },
  {
    version: '1.18.0',
    date: '4 Oktober 2026',
    title: 'Bukti cadangan & pemulihan di web',
    summary:
      'Hasil backup harian, snapshot restic, salinan offsite, dan restore drill bulanan kini dicatat ke database dan tampil di Pengaturan, sehingga bukti audit tidak bergantung pada email atau Telegram.',
    highlights: [
      'Seksi "Cadangan & Pemulihan" di Pengaturan: kartu backup terakhir, snapshot restic, restore drill terakhir, arsip di server, plus riwayat yang bisa disaring dan diunduh CSV.',
      'Skrip backup, restore drill, dan pemantau offsite menulis bukti langsung ke tabel ops_events; bila database sedang tak terjangkau, catatan diantrekan dan dikirim ulang otomatis.',
      'Riwayat lama direkonstruksi dari arsip terenkripsi dan snapshot restic yang masih tersimpan (ditandai "rekonstruksi").',
      'Tampilan tetap aman pada backend lama: menampilkan pemberitahuan, bukan galat, sampai backend diperbarui pada waktu aman.',
      'Laporan > Statistik per Akun menambah kolom Penyimpanan: isi folder /persist tiap akun (dipindai tiap 5 menit) beserta kuotanya, tanpa membuka akun satu per satu.',
    ],
  },
  {
    version: '1.17.0',
    date: '2 Oktober 2026',
    title: 'Pindahkan file dan folder dengan seret-lepas',
    summary:
      'Di Penyimpanan, file atau folder bisa diseret ke folder lain atau ke area kosong untuk dipindahkan ke tingkat atas, seperti explorer VS Code. Peringatan disk kini memuat rinciannya langsung di pesan.',
    highlights: [
      'Seret baris file/folder lalu lepaskan di folder tujuan; lepaskan di area kosong daftar untuk memindahkannya ke tingkat atas Penyimpanan.',
      'Toolbar di atas daftar (ala explorer VS Code): Berkas baru, Folder baru, Segarkan, dan Ciutkan semua. Item baru dibuat di folder yang terakhir diklik.',
      'Folder yang tertutup terbuka otomatis saat kursor ditahan di atasnya, sehingga bisa langsung menuju subfolder yang lebih dalam.',
      'Memindahkan folder ke dalam dirinya sendiri atau ke folder asalnya ditolak; nama yang sudah ada di tujuan tidak ditimpa.',
      'Email dan Telegram peringatan disk menampilkan pemakaian partisi serta pemilik home terbesar di badan pesan, tanpa lagi menyebut lampiran yang tidak ada.',
    ],
  },
  {
    version: '1.16.0',
    date: '24 September 2026',
    title: 'Metrik Devbox yang dapat dibedakan',
    summary:
      'Laporan membedakan alokasi GPU, pemakaian resource terukur, dan data yang belum tersedia. Pencatatan otomatis memerlukan backend versi terbaru yang diaktifkan pada waktu aman.',
    highlights: [
      'CPU dan RAM dibaca dari container; VRAM serta utilisasi GPU hanya menghitung proses Devbox pemiliknya, bukan beban pengguna lain pada kartu yang sama.',
      'Sampel disimpan pada riwayat job dan memperbarui RAM/VRAM/CPU puncak serta rata-rata utilisasi GPU. Riwayat sebelum pengukuran tidak direka ulang.',
      'Tabel memakai sampel terbaru untuk Devbox, lengkap dengan waktu sampel. Nol, Belum diukur, Tidak tersedia, dan Data lama ditampilkan berbeda.',
      'GPU yang dialokasikan dan lama sesi hidup bukan bukti GPU sedang bekerja. Metrik GPU pada Devbox CPU ditandai Tidak berlaku.',
      'Backend tidak direstart selama ada pengguna aktif. Tampilan tetap kompatibel dengan backend lama sambil menunggu aktivasi pencatatan.',
    ],
  },
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
