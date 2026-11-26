// Riwayat versi platform. Satu versi = satu gelombang pengembangan nyata di repo
// (bukan penomoran otomatis per commit), supaya isinya bisa dibaca orang awam.

export const APP_VERSION = '2.0.1'

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
    version: '2.0.1',
    date: '26 November 2026',
    title: 'Devbox tidak lagi sering terputus, login GitHub tidak hilang',
    summary:
      'Perbaikan keluhan "keluar terus dari server" dan "keluar akun GitHub" di Devbox, baik lewat VS Code Desktop maupun browser.',
    highlights: [
      'Devbox kini menunggu 30 menit (sebelumnya 2 menit) setelah koneksi VS Code putus, jadi jaringan yang putus sebentar tidak lagi mematikan devbox; VS Code menyambung kembali sendiri.',
      'Selama halaman ComputeHub masih terbuka (mis. sedang memasukkan kode GitHub), devbox tidak dimatikan karena koneksi VS Code putus.',
      'Login GitHub untuk VS Code Desktop dan sesi GitHub di VS Code browser disimpan selama akun aktif; pembersihan disk hanya membuang program server VS Code yang bisa disiapkan ulang otomatis.',
      'Memperbaiki pembersihan otomatis yang salah menganggap devbox lama tidak dipakai sehingga login GitHub pengguna aktif ikut terhapus.',
      'Kotak kode GitHub di halaman Devbox menjelaskan bahwa GitHub hanya diperlukan untuk VS Code Desktop; VS Code di browser bisa langsung dipakai.',
    ],
  },
  {
    version: '2.0.0',
    date: '24 November 2026',
    title: 'Ruang Kelas: dosen dan mahasiswa dalam satu kelas',
    summary:
      'Menu baru Ruang Kelas. Dosen membuat kelas praktikum, mahasiswa bergabung cukup dengan kode kelas.',
    highlights: [
      'Dosen dan admin membuat kelas lalu membagikan kode 8 karakter; mahasiswa bergabung lewat menu Ruang Kelas.',
      'Pengajar bisa menambahkan anggota langsung dengan menempel daftar email, username, atau NIM, atau mencari nama.',
      'Satu kelas boleh punya beberapa pengajar (dosen atau asisten).',
      'Pendaftaran bisa ditutup, kode bisa diganti, dan kelas yang selesai bisa diarsipkan.',
      'Mahasiswa hanya melihat pengajar dan jumlah peserta, bukan data teman sekelas.',
      'Materi kelas: pengajar mengunggah file atau folder apa saja (atau membagikan dari Penyimpanan); mahasiswa menekan Ambil salinan dan materinya masuk ke folder Kelas/ tanpa menimpa pekerjaan lama.',
      'Kuota GPU kelas: pengajar memberi tambahan kuota GPU harian bagi peserta selama periode praktikum, dengan batas untuk dosen yang diatur admin.',
      'Ruang kerja kelas: mahasiswa otomatis mendapat folder Kelas/<nama kelas>/ dan tombol Buka di Devbox yang membuka VS Code hanya di folder itu dengan simpan otomatis.',
      'Pantau Kelas: pengajar dan asisten melihat isi folder kelas tiap mahasiswa secara baca-saja dan hampir langsung — hanya folder kelas, bukan layar atau berkas lain.',
      'Unggah di Penyimpanan, Notebook, dan materi kelas kini tanpa batas ukuran per file; yang berlaku hanya kuota penyimpanan.',
      'Nyalakan devbox kini langsung menyiapkan tunnel VS Code Desktop tanpa klik tambahan.',
      'Status online: admin (Laporan dan Pengguna) serta pengajar (Pantau Kelas) melihat apakah pengguna sedang membuka ComputeHub — Online, Aktif X mnt lalu, atau Offline.',
      'VS Code di browser tidak lagi menanyakan "trust this folder" dan tidak masuk Restricted Mode, sehingga Python dan Jupyter langsung aktif.',
    ],
  },
  {
    version: '1.45.0',
    date: '24 November 2026',
    title: 'Sitasi Mendeley otomatis di Devbox',
    summary:
      'Asisten AI di Devbox kini bisa mengubah sitasi bernomor di paper Word Anda menjadi sitasi Mendeley yang aktif.',
    highlights: [
      'Cukup minta di panel Chat, mis. "tolong sitasi paper saya dengan Mendeley", lalu sebutkan berkas .docx dan .ris Anda.',
      'Mendukung Mendeley Desktop (Cite-O-Matic) maupun Mendeley web/Reference Manager (add-in Mendeley Cite).',
      'Berkas asli tidak diubah; hasilnya berkas baru yang tinggal dibuka di Word lalu di-Refresh.',
      'Rujukan hanya diambil dari berkas RIS Anda, tidak dikarang, dan semuanya diproses di server kampus.',
    ],
  },
  {
    version: '1.44.0',
    date: '21 November 2026',
    title: 'Lihat grafik training langsung di web (TensorBoard)',
    summary:
      'Pantau grafik loss, akurasi, dan metrik lain dari training Anda tanpa perintah terminal. Cukup tekan tombol Lihat grafik.',
    highlights: [
      'Tombol Lihat grafik tersedia di Penyimpanan, Detail job, dan toolbar Notebook.',
      'Folder log dicari otomatis; tampilkan satu run atau beberapa sekaligus untuk dibandingkan.',
      'Grafik diperbarui sendiri selama training masih berjalan.',
      'Berjalan di CPU sehingga tidak memakai GPU atau kuota GPU, hanya bisa dibuka oleh Anda, dan mati sendiri setelah 15 menit tidak dibuka.',
    ],
  },
  {
    version: '1.43.0',
    date: '19 November 2026',
    title: 'Tanya Dokumen: tanya isi skripsi, jurnal, dan modul Anda',
    summary:
      'Menu baru untuk menyimpan dokumen pribadi lalu bertanya tentang isinya. Jawaban diambil dari dokumen Anda sendiri dan menyertakan sumbernya.',
    highlights: [
      'Unggah PDF, Word, PowerPoint, Excel, atau teks; dokumen tersimpan di folder Dokumen-AI dan bisa ditanya kapan saja.',
      'Setiap jawaban mencantumkan sumber [D1], [D2] beserta nama berkas dan bagiannya, sehingga mudah dicek ulang.',
      'Centang dokumen tertentu untuk membatasi pertanyaan hanya ke dokumen itu.',
      'Dokumen hanya bisa dilihat dan dicari oleh pemiliknya, dan memakai kuota penyimpanan biasa.',
    ],
  },
  {
    version: '1.42.3',
    date: '19 November 2026',
    title: 'Perkiraan waktu tunggu antrean lebih akurat',
    summary:
      'Perkiraan kapan job yang mengantre mulai berjalan kini dihitung dengan aturan yang sama seperti penjadwal, dan alasan menunggunya ditampilkan dengan jelas.',
    highlights: [
      'Daftar Job dan detail job menampilkan alasan menunggu: GPU penuh, menunggu jadwal, kuota harian habis, atau menunggu job/Devbox Anda yang lain.',
      'Devbox dan notebook yang menyala tidak lagi dihitung sebagai job yang memakai slot antrean.',
      'Job yang belum pernah dijalankan diperkirakan dari rata-rata durasi job sebelumnya, bukan langsung 1 jam.',
    ],
  },
  {
    version: '1.42.2',
    date: '18 November 2026',
    title: 'Pustaka Devbox & notebook diperbarui',
    summary:
      'Lingkungan Python di Devbox dan notebook kini memakai versi pustaka terbaru, dan Devbox otomatis ikut memakai lingkungan terbaru saat dinyalakan kembali.',
    highlights: [
      'Pustaka seperti transformers, tokenizers, numba, dan geopandas diperbarui ke versi terbaru yang kompatibel dengan tiap versi Python.',
      'Devbox yang dinyalakan ulang otomatis memakai lingkungan terbaru; file di folder rumah (/persist) tetap aman.',
      'Isi folder /tmp dari Devbox lama telah diamankan ke folder _tmp-devbox-lama-2026-11-18 di folder rumah pemiliknya.',
    ],
  },
  {
    version: '1.42.1',
    date: '18 November 2026',
    title: 'Asisten AI lebih cepat saat satu GPU penuh',
    summary:
      'Asisten AI, bot Bantuan, dan Copilot Chat di Devbox kini otomatis memakai GPU yang paling lega sehingga tidak lagi lambat ketika salah satu GPU sedang penuh.',
    highlights: [
      'Permintaan AI diarahkan ke GPU dengan memori kosong terbanyak, bukan dibagi rata.',
      'Mencegah model berjalan di CPU (jawaban bisa menunggu beberapa menit dan membebani server).',
    ],
  },
  {
    version: '1.42.0',
    date: '18 November 2026',
    title: 'Laporan jam GPU bulanan & pemantauan email',
    summary:
      'Admin kini bisa melihat jam GPU per pengguna setiap bulan dan langsung tahu bila pengiriman email bermasalah.',
    highlights: [
      'Laporan → Jam GPU Bulanan: pilih bulan, lihat jam GPU per pengguna dan per peran (batch, notebook, Devbox), lalu unduh CSV.',
      'Jam GPU dihitung dengan aturan yang sama seperti kuota: hanya saat VRAM benar-benar dipakai.',
      'Koneksi email (SMTP) diuji otomatis tiap 6 jam; bila gagal, admin langsung diberi tahu lewat Telegram dan halaman Peringatan menampilkan penyebabnya.',
    ],
  },
  {
    version: '1.41.2',
    date: '18 November 2026',
    title: 'Halaman Bantuan & panduan PDF diperbarui',
    summary:
      'Isi Bantuan, panduan PDF, dan bot Bantuan diselaraskan dengan fitur terbaru dan aturan yang berlaku saat ini.',
    highlights: [
      'Bagian baru Asisten AI: melampirkan dokumen, mencari di web dengan daftar sumber, dan bot Bantuan yang merujuk panduan.',
      'Penjelasan GPU otomatis menggantikan pilihan GPU/CPU yang sudah tidak ada.',
      'Kuota GPU harian ditegaskan: 6 jam, pulih tiap tengah malam WITA, dihitung hanya saat VRAM benar-benar dipakai.',
      'Ditambahkan: Copilot Chat lewat Ollama di Devbox, Tempat Sampah 7 hari, terminal yang tetap berjalan, dan login Google + Minta Akses.',
      'Koreksi: kapasitas L40S 48 GB dan aturan Sampah job yang tidak lagi berlaku.',
    ],
  },
  {
    version: '1.41.1',
    date: '18 November 2026',
    title: 'Durasi pemakaian kunci API Ollama tercatat akurat',
    summary:
      'Lama permintaan non-stream lewat gateway Ollama kini dihitung sejak permintaan dikirim, sehingga laporan pemakaian menampilkan waktu yang sebenarnya.',
    highlights: [
      'Sebelumnya permintaan non-stream tercatat hampir 0 detik karena waktu menunggu model menjawab tidak ikut terhitung.',
    ],
  },
  {
    version: '1.41.0',
    date: '18 November 2026',
    title: 'Asisten AI bisa membaca dokumen & mencari di web',
    summary:
      'Asisten AI notebook kini bisa membaca dokumen yang dilampirkan dan menyertakan hasil pencarian internet beserta sumbernya. Bot Bantuan juga menjawab berdasarkan isi panduan resmi.',
    highlights: [
      'Tombol klip di Asisten AI: lampirkan PDF, Word, Excel, PowerPoint, CSV, dll. (maks 3 dokumen per pesan) untuk diringkas atau ditanyakan isinya. Dokumen hanya dibaca, tidak disimpan di server.',
      'Tombol "Cari di web": jawaban memakai hasil pencarian internet terbaru dan mencantumkan daftar sumber yang bisa diklik.',
      'Bot Bantuan mencari bagian panduan pengguna yang relevan dengan pertanyaan, sehingga jawabannya lebih tepat.',
    ],
  },
  {
    version: '1.40.4',
    date: '18 November 2026',
    title: 'Label proses ComputeHub Devbox dipersingkat',
    summary: 'Di laporan aktivitas proses, service cadangan VRAM kini cukup tampil sebagai "ComputeHub · Devbox".',
    highlights: ['Keterangan "(cadangan VRAM untuk user ComputeHub)" dihapus dari label proses.'],
  },
  {
    version: '1.40.3',
    date: '18 November 2026',
    title: 'Panduan cara pakai peminjam cadangan VRAM',
    summary:
      'Setiap peminjam cadangan VRAM kini punya tombol "Cara pakai" yang langsung terbuka saat peminjam baru ditambahkan: penjelasan mode otomatis & on demand, plus perintah siap salin.',
    highlights: [
      'Perintah memakai nama container GPU dan alamat gateway jaringan project yang sebenarnya.',
      'Perintah nyalakan/matikan container, pinjam di muka, cek status, kembalikan, dan contoh kode Python.',
      'Container yang pernah memakai GPU diingat, jadi panduan tetap benar walau container sedang dimatikan.',
    ],
  },
  {
    version: '1.40.2',
    date: '18 November 2026',
    title: 'Kantong VRAM berganti nama: ComputeHub Devbox',
    summary:
      'Service pemegang cadangan VRAM kini bernama computehub-devbox dan tampil di laporan proses sebagai "ComputeHub · Devbox (cadangan VRAM untuk user ComputeHub)". Istilah "kantong" di Admin diganti "cadangan".',
    highlights: [
      'Skrip & service: scripts/computehub_devbox.py / computehub-devbox.service; nama proses computehub-devb.',
      'Panel Admin: "ComputeHub Devbox (cadangan VRAM)" dan "Peminjam cadangan".',
      'Alamat API /api/v1/vram-pocket tetap sama agar aplikasi peminjam tidak perlu diubah.',
    ],
  },
  {
    version: '1.40.1',
    date: '18 November 2026',
    title: 'Nama proses Kantong VRAM bercirikan ComputeHub',
    summary:
      'Proses pemegang kantong VRAM kini tampil sebagai "ComputeHub · Kantong VRAM" di laporan proses, bukan skrip Python vram_pocket_daemon.py.',
    highlights: [
      'Skrip dan service diganti nama: computehub_kantong_vram.py / computehub-kantong-vram.service.',
      'Nama proses di top/ps: computehub-vram.',
    ],
  },
  {
    version: '1.40.0',
    date: '18 November 2026',
    title: 'Pinjam kantong VRAM dari aplikasi lain',
    summary:
      'Project Docker Compose yang didaftarkan super admin (mis. local-ai) kini boleh memakai VRAM kantong tanpa batas waktu: kantong melepas VRAM saat container-nya memakai GPU dan memegangnya lagi setelah model di-unload.',
    highlights: [
      'Daftar peminjam diatur di Admin → Kantong VRAM; pemakaian per GPU dan container peminjam tampil langsung.',
      'Pinjam di muka sebelum memuat model lewat POST /api/v1/vram-pocket/borrow dari dalam container (dikenali dari IP container, tanpa kunci).',
      'Pinjaman kembali otomatis 60 detik setelah GPU project diam, atau bila model tak pernah dimuat dalam 10 menit.',
    ],
  },
  {
    version: '1.39.2',
    date: '18 November 2026',
    title: 'Pemakai Ollama tercatat lengkap',
    summary:
      'Tabel Pemakai Layanan LLM kini mencatat pemakaian Copilot dari devbox dan kunci API per akun ComputeHub (sebelumnya hanya Asisten web), serta menyebut pemilik container yang terhubung ke Ollama.',
    highlights: [
      'Kolom "Lewat" merinci asal permintaan: Asisten web, Devbox, atau Kunci API.',
      'Koneksi dari backend ComputeHub sendiri tidak lagi tampil sebagai pemakaian pribadi akun Linux yang menjalankannya.',
      'Asal container menyebut pemiliknya, mis. "local-ai-nextcloud-ai-worker · milik muhammadrizalharis".',
    ],
  },
  {
    version: '1.39.1',
    date: '18 November 2026',
    title: 'Workload semua pengguna lebih rinci',
    summary:
      'Selain container Docker, proses yang dijalankan sebagai service systemd kini menyebut nama service-nya, dan label umum diberi rincian aplikasi. Berlaku untuk proses semua pengguna.',
    highlights: [
      'Contoh: "Generatif gambar (diffusion) · service comfyui@0", "API / Web server (server:app) · service ai-f5tts", "Node / Frontend (Next.js v16.4.1) · service user codeunical-web".',
      'Service bawaan tampil "Service sistem (nginx)"; sesi login biasa dan pemicu generik seperti cron tidak ditempelkan.',
    ],
  },
  {
    version: '1.39.0',
    date: '17 November 2026',
    title: 'Proses di dalam container Docker kini dikenali',
    summary:
      'Di Laporan Server dan laporan per pengguna, proses yang berjalan di dalam container tidak lagi tampil sekadar "Skrip Python", melainkan "Docker / proyek / layanan" (mis. Docker / local-ai / docling) beserta nama container-nya.',
    highlights: [
      'Berlaku untuk proses utama, proses pendukung, proses teratas, dan tabel proses GPU. Pemilik proses tetap memakai UID asli di server.',
      'Data container dibaca dari Docker secara read-only dan di-cache 45 detik. Bila Docker tak terjangkau tampil "Docker (nama tidak tersedia)".',
    ],
  },
  {
    version: '1.38.0',
    date: '17 November 2026',
    title: 'Model Asisten AI bisa dipilih lebih dari satu',
    summary:
      'Di Limit khusus pengguna dan di default per peran, admin kini bisa mencentang beberapa model Ollama sekaligus. Semua model yang dicentang tampil di Copilot Chat devbox, sedangkan model ★ utama tetap dipakai Asisten AI web.',
    highlights: [
      'Urutan bisa diatur lewat "jadikan utama"; model embedding disembunyikan dari pilihan.',
      'Bila pengguna dan perannya sama-sama kosong, devbox otomatis menampilkan semua model yang mendukung tools (siap mode agent).',
    ],
  },
  {
    version: '1.37.0',
    date: '17 November 2026',
    title: 'Model Ollama kampus di Copilot Chat devbox',
    summary:
      'Di devbox, Copilot Chat bisa langsung memakai model Ollama server kampus lewat alamat bawaan localhost:11434, jadi pengguna tanpa akun GitHub maupun Copilot tetap punya asisten AI di VS Code.',
    highlights: [
      'Model yang muncul mengikuti Model Asisten AI di Limit khusus pengguna (kosong = default peran). Model lain tidak terlihat dan ditolak.',
      'Tanpa kunci API: devbox dikenali otomatis dari container-nya, dengan batas permintaan per pengguna agar Ollama tetap lega.',
    ],
  },
  {
    version: '1.36.0',
    date: '17 November 2026',
    title: 'Kantong VRAM dan GPU otomatis untuk semua pekerjaan',
    summary:
      'ComputeHub kini bisa memesan sejumlah VRAM (awal 16 GB) di server bersama, sehingga pengguna ComputeHub tetap kebagian GPU walau pengguna server lain sedang ramai. Semua job, notebook, dan devbox otomatis mendapat GPU; slot dan kuota GPU hanya terpakai saat kode benar-benar memakai VRAM.',
    highlights: [
      'Pengaturan > Kantong VRAM (admin utama): nyalakan atau matikan kantong dengan satu sakelar dan atur ukurannya. Saat dimatikan, VRAM yang dipegang dilepas dalam hitungan detik.',
      'Kode user mengambil VRAM dari kantong lebih dulu; bila kantong habis, user memakai VRAM umum di GPU yang sama. Kantong tidak pernah merebut VRAM yang sedang dipakai pengguna lain.',
      'Form Submit kini hanya GPU (opsi 2 GPU eksklusif tetap ada). Kode tanpa CUDA seperti scikit-learn tetap berjalan normal tanpa memakai VRAM maupun kuota GPU; job yang menunggu GPU lebih dari 10 menit dijalankan tanpa GPU.',
      'Slot GPU dan kuota harian dihitung dari pemakaian VRAM nyata, bukan dari GPU yang sekadar dipegang. TensorFlow dan JAX hanya mengambil VRAM sesuai kebutuhan.',
    ],
  },
  {
    version: '1.35.0',
    date: '16 November 2026',
    title: 'Riwayat disk dan rekaman pelaku lonjakan',
    summary:
      'Sisa disk server kini dicatat tiap 10 menit dan tampil sebagai grafik di halaman Laporan (khusus admin). Bila disk tiba-tiba turun drastis, sistem otomatis merekam proses yang paling banyak menulis saat itu, jadi penyebabnya tidak perlu ditebak-tebak lagi.',
    highlights: [
      'Laporan > Pemakaian Disk: grafik sisa disk 24 jam, 7 hari, atau 30 hari, lengkap dengan laju penurunan tercepat.',
      'Lonjakan (sisa disk turun 50 GB atau lebih dalam sekitar 1 jam) direkam beserta proses penulis terbesar, log container Docker yang membengkak, dan job yang sedang berjalan. Admin juga mendapat kabar lewat Telegram.',
      'Riwayat disimpan 90 hari di server saja, tidak di repo.',
      'Rincian disk kini memisahkan file sementara (/tmp), log sistem, /opt, home root, dan program sistem (/usr), sehingga yang membengkak langsung kelihatan dan tidak lagi tersembunyi di "Sistem & lainnya".',
    ],
  },
  {
    version: '1.34.1',
    date: '15 November 2026',
    title: 'Pembaruan keamanan: PostgreSQL, Chromium, dan pustaka Python di lingkungan job',
    summary:
      'Menindaklanjuti berita celah keamanan dan peringatan GitHub, seluruh komponen yang terdampak ditambal tanpa mengganggu job yang sedang berjalan. Database naik ke PostgreSQL 17.12, Chromium untuk scraping naik ke versi 159, dan semua 85 peringatan dependensi GitHub ditutup.',
    highlights: [
      'Database ComputeHub naik dari PostgreSQL 17.7 ke 17.12 (menutup CVE-2026-6460); data, akun, dan kuota tetap utuh, jeda hanya sekitar 1 detik.',
      'Lingkungan job: Playwright 1.65.2 dengan Chromium 159 (menutup zero-day CVE-2026-125350), plus nltk, datasets, pypdf, keras, accelerate, dan scrapy versi aman. Semua 85 peringatan GitHub tertutup.',
      'Pemberitahuan ke pengguna: banner pengumuman, bagian baru "Keamanan file & model" di halaman Bantuan, dan pesan otomatis saat keras dipakai di image Python 3.10 (pilih image Python 3.11 ke atas untuk keras yang sudah ditambal).',
    ],
  },
  {
    version: '1.34.0',
    date: '15 November 2026',
    title: 'Laporan realtime, backup susulan otomatis, dan email yang lebih andal',
    summary:
      'Halaman Laporan kini menampilkan pemakaian disk dan penyimpanan per akun yang akurat dan selalu segar. Backup mingguan yang terlewat karena server mati kini disusulkan otomatis, arsip lama di Google Drive dihapus permanen, dan email notifikasi dikirim ulang bila koneksi sempat putus.',
    highlights: [
      'Laporan: pemakaian disk server memakai GB desimal seperti df dan rinciannya sama persis dengan total; tabel baru "Penyimpanan Akun ComputeHub" diperbarui otomatis; data pengguna server (CPU/RAM/VRAM) segar tiap detik.',
      'Backup: bila arsip penuh terakhir di Drive lebih dari 7 hari (jadwal Minggu terlewat), arsip penuh susulan dibuat otomatis; arsip lama di Drive langsung dihapus permanen, tidak menumpuk di Trash.',
      'Email: gangguan koneksi dicoba ulang hingga 3 kali, dan galat sebenarnya (misalnya password aplikasi ditolak) kini tercatat jelas.',
      'Satuan akurat: angka berbasis 1024 (RAM, VRAM, kuota, ukuran file) kini berlabel MiB/GiB; nilai kuota tidak berubah, hanya labelnya yang lebih tepat.',
    ],
  },
  {
    version: '1.33.0',
    date: '13 November 2026',
    title: 'Peringatan suhu GPU dan pembaruan fondasi frontend',
    summary:
      'Admin kini menerima peringatan lewat Telegram dan email saat suhu GPU melewati ambang batas, sehingga GPU yang terlalu panas cepat ditangani. Fondasi frontend diperbarui ke React 19 dan TypeScript 7.',
    highlights: [
      'Ambang suhu GPU (bawaan 85°C) bisa diatur di konfigurasi alert; tiap GPU yang melewatinya memicu notifikasi ke seluruh admin.',
      'Frontend naik ke React 19, TypeScript 7, dan react-query 5.106 tanpa perubahan tampilan.',
      'Perbaikan: jendela atur limit dan kredensial pengguna kini selalu muncul di tengah layar, tidak perlu di-scroll.',
      'Pembaruan dependensi rutin dihentikan agar tidak menumpuk; tambalan keamanan tetap diterima otomatis.',
    ],
  },
  {
    version: '1.32.0',
    date: '10 November 2026',
    title: 'Autentikasi 2FA, panel Monitoring, dan penjaga penyimpanan NFS',
    summary:
      'Akun admin bisa memakai verifikasi dua langkah (2FA). Super admin mendapat panel Monitoring untuk memantau kesehatan backend secara langsung. Server kini juga menjaga agar penyimpanan data pengguna di VM selalu terpasang sebelum aplikasi berjalan.',
    highlights: [
      '2FA opsional untuk akun login-password: aplikasi authenticator (TOTP) dan kode pemulihan sekali pakai, diatur dari halaman Profil.',
      'Panel Monitoring khusus super admin: request/detik, error, latensi, CPU/RAM, katalog 21 metrik dengan grafik mini, dan tautan ke Grafana.',
      'Penyimpanan NFS dipasang otomatis sebelum backend menyala (misalnya setelah listrik padam), diawasi tiap 5 menit, dan dipasang ulang dengan alert bila terlepas.',
      'Grafik tren ukuran backup beserta proyeksi 30/90 hari; 175 tes otomatis kini dijalankan di setiap perubahan kode.',
    ],
  },
  {
    version: '1.31.2',
    date: '9 November 2026',
    title: 'Perbaikan: panel "Pemakaian disk Devbox" tak lagi menggantung',
    summary:
      'Dari pengujian menyeluruh ditemukan endpoint pemakaian disk Devbox bisa menggantung lebih dari 60 detik karena menelusuri ratusan ribu berkas VS Code/extension di atas NFS pada tiap permintaan. Kini hasilnya dihitung di latar belakang dan di-cache, sehingga halaman Laporan/Pengaturan admin tetap responsif.',
    highlights: [
      'Endpoint /devbox/disk kini membalas seketika (±7 ms) dengan data tercache; angka dihitung ulang di latar (TTL 10 menit) tanpa memblokir permintaan.',
      'Panel Devbox otomatis memperbarui angka begitu perhitungan latar selesai (polling ringan hanya selama menghitung), lalu berhenti.',
      'Tanpa perubahan perilaku lain; hanya menghilangkan potensi hang pada kartu pemakaian disk Devbox.',
    ],
  },
  {
    version: '1.31.1',
    date: '9 November 2026',
    title: 'Penguatan keamanan renderer Markdown (escaping tanda kutip)',
    summary:
      'Hasil audit keamanan menyeluruh (perspektif penyerang) tidak menemukan celah berbahaya. Satu temuan ringan ditutup secara tuntas: fungsi escaping renderer Markdown kini juga meng-escape tanda kutip (" dan \'), menutup kemungkinan penyuntikan atribut HTML lewat URL tautan — tanpa perubahan tampilan apa pun.',
    highlights: [
      'esc() kini meng-escape lima karakter sensitif HTML (& < > " \') sesuai standar OWASP, bukan hanya tiga.',
      'Defense-in-depth: menutup kelas kerentanan "attribute injection" sepenuhnya, bukan hanya payload tertentu.',
      'Tanpa dampak fungsional: render Markdown untuk teks normal tetap sama persis; hanya perbaikan di jalur escaping.',
    ],
  },
  {
    version: '1.31.0',
    date: '9 November 2026',
    title: 'Tombol "Reklamasi Drive": bebaskan ruang cadangan di Google Drive seketika',
    summary:
      'Kartu "Cadangan & Pemulihan" kini punya tombol "Reklamasi Drive" (admin utama). Setelah menghapus data dalam jumlah besar, admin bisa langsung membuang snapshot kedaluwarsa & menulis ulang pack (restic forget + prune) agar ruang di Drive segera dibebaskan — tanpa menunggu prune mingguan otomatis.',
    highlights: [
      'Normalnya tak perlu: Drive sudah menyusut sendiri lewat prune mingguan. Tombol ini untuk kasus penghapusan besar yang ingin langsung melegakan ruang.',
      'Aman: produksi tidak disentuh — hanya menata ulang repo cadangan di Drive; kebijakan retensi tetap 7 harian / 4 mingguan / 3 bulanan.',
      'Berjalan lewat agen host dengan konfirmasi; kemajuan & hasil (byte dibebaskan, snapshot tersisa) tampil di kartu permintaan dan tercatat sebagai bukti audit.',
    ],
  },
  {
    version: '1.30.0',
    date: '9 November 2026',
    title: 'Verifikasi retensi cadangan: pastikan backup lama di Drive benar-benar dihapus',
    summary:
      'Kartu "Cadangan & Pemulihan" kini menampilkan verifikasi retensi: apakah cadangan harian, mingguan, dan bulanan yang lama di Google Drive benar-benar dihapus dan diganti yang baru — bukan sekadar teks kebijakan. Pengecekan read-only (tidak menghapus apa pun) berjalan tiap backup.',
    highlights: [
      'Panel "Retensi backup di Drive" dengan verdict per tingkat: snapshot restic (7 harian · 4 mingguan · 3 bulanan), arsip penuh mingguan (8 terbaru), dan arsip inti config/DB (90 hari).',
      'Deteksi dini bila cadangan lama menumpuk (mis. retensi tak berjalan) lewat badge "Perlu dicek" dan plafon jumlah snapshot yang wajar.',
      'Skrip read-only scripts/backup-check.sh memeriksa langsung ke Drive lalu menulis status; dipanggil otomatis di akhir tiap backup dan bisa dijalankan kapan saja.',
    ],
  },
  {
    version: '1.29.0',
    date: '2 November 2026',
    title: 'Akses Ollama: status live — tahu siapa yang dipakai & sedang jalan/idle',
    summary:
      'Panel Akses Ollama kini menampilkan status real-time: apakah Ollama aktif, model apa yang sedang dimuat, berapa permintaan sedang berjalan, dan kunci (pemilik) mana yang sedang memakainya. Tiap kunci diberi badge "sedang dipakai" atau "idle".',
    highlights: [
      'Banner status: Ollama aktif/mati + versi, jumlah permintaan yang sedang diproses beserta nama pemiliknya, dan daftar model yang sedang dimuat (hangat) atau "dingin" bila tak ada.',
      'Badge per-kunci: hijau "sedang dipakai" (dengan jumlah permintaan paralel) saat kunci itu aktif, atau "idle" saat menganggur — diperbarui otomatis tiap 5 detik.',
      'Menjawab "siapa persisnya": untuk pemakai lewat API key, atribusi memakai identitas pemilik kunci (nama/NIM/role), bukan sekadar UID socket yang menyatu jadi localhost.',
    ],
  },
  {
    version: '1.28.0',
    date: '26 Oktober 2026',
    title: 'Menu admin dirapikan: akun Linux, akses Ollama, dan log admin jadi menu sendiri',
    summary:
      'Tiga panel yang dulu menumpuk di halaman “Pengaturan” kini jadi menu tersendiri di sidebar admin, sehingga lebih cepat diakses dan tak perlu scroll panjang.',
    highlights: [
      'Sidebar admin baru berurutan: Laporan, Peringatan, Pengguna, Cadangan, Permintaan Akses, Pengaturan Akun Linux, Akses API Key Ollama, Log Aktivitas Admin, lalu Pengaturan.',
      '“Pengaturan Akun Linux” (batas CPU/RAM per akun), “Akses API Key Ollama”, dan “Log Aktivitas Admin” kini punya halaman masing-masing.',
      'Halaman “Pengaturan” kini fokus ke setelan sistem (pengumuman, mode pemeliharaan, kuota per peran, model asisten) tanpa panel yang sudah dipindah.',
    ],
  },
  {
    version: '1.27.0',
    date: '26 Oktober 2026',
    title: 'Batas akun Linux: opsi permanen (bertahan reboot, terlihat admin IT)',
    summary:
      'Panel batas akun Linux kini bisa memasang batas CPU/RAM secara permanen — bertahan setelah server reboot dan terlihat admin IT di terminal. Perubahan admin IT tetap terbaca otomatis, sehingga dua arah: IT ⇄ ComputeHub.',
    highlights: [
      'Opsi “Terapkan permanen”: batas ditulis ke berkas drop-in khusus ComputeHub (90-computehub.conf) yang bertahan setelah reboot dan muncul di `systemctl cat` admin IT.',
      'Berkas ComputeHub TERPISAH dari folder set-property admin IT, jadi tidak pernah saling menimpa; akun yang sudah diatur IT tetap ditolak untuk diubah dari UI.',
      '“Kembalikan ke aturan sistem” melepas batas runtime maupun permanen milik ComputeHub, tanpa menyentuh aturan admin IT. Badge akun menunjukkan status “permanen” atau “runtime”.',
    ],
  },
  {
    version: '1.26.0',
    date: '25 Oktober 2026',
    title: 'Kunci Ollama: pemilik dari daftar pengguna + info siap-salin',
    summary:
      'Membuat kunci Ollama kini memilih pemilik dari daftar pengguna web (bukan ketik manual), sehingga NIM dan role ikut otomatis. Setelah dibuat, semua info (alamat, kunci, model, pemilik) tampil dalam satu blok siap-salin.',
    highlights: [
      'Kolom pemilik kini dropdown dari pengguna web; role dan NIM (bagian depan email mahasiswa) tersimpan otomatis bersama kunci dan tampil di daftar.',
      'Setelah kunci dibuat, muncul satu blok siap-salin berisi alamat gateway, kunci, model yang diizinkan, identitas pemilik, plus contoh Python & curl — cukup sekali salin untuk dikirim ke pemilik.',
      'Tombol “Salin semua” dan “Salin kunci saja” memudahkan distribusi; kunci mentah tetap hanya ditampilkan sekali.',
    ],
  },
  {
    version: '1.25.0',
    date: '23 Oktober 2026',
    title: 'Akses Ollama lewat API key untuk pengguna luar',
    summary:
      'Admin kini bisa membuat kunci API Ollama dari halaman Pengaturan, sehingga rekan di luar server bisa memakai model Ollama kampus lewat jembatan ComputeHub tanpa akun server.',
    highlights: [
      'Panel “Akses Ollama (API key)” di Pengaturan: buat kunci dengan nama pemilik, pilih model yang diizinkan, batas paralel, laju (req/menit), batas token, dan tanggal kedaluwarsa.',
      'Kunci ditampilkan sekali saat dibuat (sisanya hanya awalan), bisa diaktif/nonaktifkan atau dihapus; pemakaian terakhir dan jumlah permintaan ikut terpantau.',
      'Gateway kompatibel OpenAI (/v1/chat/completions, /v1/models) dan native Ollama (/api/chat, /api/generate, /api/tags); endpoint kelola model (pull/push/delete) diblokir. Semua pembuatan/ubah/hapus kunci tercatat di Log Aktivitas.',
    ],
  },
  {
    version: '1.24.2',
    date: '22 Oktober 2026',
    title: 'Log Aktivitas Admin: filter, riwayat lengkap, dan ekspor CSV',
    summary:
      'Log Aktivitas Admin di halaman Pengaturan kini bisa disaring dan ditelusuri sampai entri paling lama, lalu diekspor untuk keperluan audit.',
    highlights: [
      'Saring berdasarkan jenis aksi (atau satu grup, mis. semua aksi kuota penyimpanan), admin pelaku, kata kunci pada detail/target, dan rentang tanggal (WITA).',
      'Tampil 100 entri per halaman beserta jumlah totalnya; tombol Lebih lama/Lebih baru untuk menelusuri riwayat.',
      'Ekspor CSV mengikuti filter yang aktif (maks. 50.000 baris, bisa dibuka di Excel). Setiap ekspor ikut tercatat di log.',
    ],
  },
  {
    version: '1.24.1',
    date: '18 Oktober 2026',
    title: 'Terminal tetap jalan saat pindah menu atau window',
    summary:
      'Shell terminal kini milik sesi kernel, bukan milik panel. Pindah menu, pindah window/tab, atau menyembunyikan panel tidak lagi mematikan proses di terminal.',
    highlights: [
      'Saat kembali, panel terminal muncul lagi dan tersambung ke shell yang sama; output yang keluar selama ditinggal diputar ulang.',
      'Koneksi yang terputus (jaringan atau proxy) tersambung ulang otomatis. Membuka terminal yang sama di tab lain akan mengambil alih koneksi.',
      'Tombol X kini hanya menyembunyikan panel. Tombol Hentikan baru menghentikan shell beserta prosesnya; shell juga berhenti lewat exit atau saat kernel dimatikan.',
    ],
  },
  {
    version: '1.24.0',
    date: '17 Oktober 2026',
    title: 'Google lokal, pratinjau terkunci, dan permintaan akses',
    summary:
      'Akun lokal kini dibuat otomatis lewat Google pribadi. Dashboard live langsung tersedia; fitur lain terkunci sampai disetujui admin.',
    highlights: [
      'Pintu /welcome/user khusus Google, terpisah dari SSO kampus, pengelola, dan akun Linux/SSH. Login password lokal tidak lagi digunakan.',
      'Semua menu komputasi, job, penyimpanan, bantuan, dan saran tetap bisa dibuka sebagai pratinjau berikon kunci tanpa input atau eksekusi; API fitur juga dikunci.',
      'Menu Minta Akses mengirim pesan persisten ke seluruh admin aktif dan super admin. Admin menyetujui atau menolak dengan catatan serta peran mahasiswa/dosen.',
      'Persetujuan membuka seluruh fitur sesuai peran dan kuota, tanpa perlu login ulang. Penonaktifan akun tetap terpisah dari akses fitur.',
      'Login Google memerlukan konfigurasi OAuth Web khusus ComputeHub; status belum dikonfigurasi ditampilkan jelas tanpa fallback password.',
    ],
  },
  {
    version: '1.23.0',
    date: '17 Oktober 2026',
    title: 'Pintu akun lokal dengan aktivasi admin',
    summary:
      'Akun lokal tanpa SSO masuk melalui /welcome/user. Admin biasa maupun super admin dapat membuat akun, memilih peran mahasiswa/dosen, lalu mengaktifkannya.',
    highlights: [
      'Akun lokal baru selalu nonaktif sampai disetujui admin. Kuota, isolasi data, sesi tunggal, dan pembatasan login tetap mengikuti aturan platform.',
      'Pintu lokal terpisah dari login SSO dan pengelola. Akun lokal tidak memperoleh hak admin atau akses Linux/SSH.',
      'Sumber akun Lokal dan ComputeHub (SSO/pengelola) ditandai pada daftar pengguna, profil, serta laporan; akun Linux tetap terpisah.',
      'Penonaktifan atau perubahan peran mencabut sesi lama. Email kredensial memuat URL lokal dan status aktivasi.',
    ],
  },
  {
    version: '1.22.1',
    date: '9 Oktober 2026',
    title: 'Unduh PDF per catatan cadangan',
    summary:
      'Setiap catatan di riwayat Cadangan & Pemulihan kini bisa diunduh sebagai laporan PDF (ikon unduh di kolom Aksi atau tombol Unduh PDF di detail) untuk lampiran audit.',
    highlights: [
      'Isi PDF: kotak status, ringkasan (jenis, waktu, durasi, sumber pencatat, ketersediaan arsip di server), seluruh data tercatat berlabel, dan Detail Backup lengkap (PostgreSQL, workspace per akun, komponen, waktu & lingkungan, berkas) bila catatan membawa manifest.',
      'Nama berkas berpola cadangan_<jenis>_<nomor>_<tanggal_jam>.pdf; tersedia untuk semua admin.',
    ],
  },
  {
    version: '1.22.0',
    date: '9 Oktober 2026',
    title: 'Backup harian ke Drive — yang besar hanya di Drive',
    summary:
      'Kebijakan penyimpanan cadangan baru: arsip inti kecil tiap hari di server + Drive, snapshot restic harian langsung ke repo di Google Drive, arsip penuh mingguan hanya di Drive (salinan server dihapus setelah terverifikasi).',
    highlights: [
      'Arsip inti harian (database + roles + konfigurasi + log job, tanpa workspace; puluhan MB): 30 hari di server, 90 hari di Drive — jalur pulih database tercepat.',
      'Snapshot restic harian (dedup, 7/4/3) ditulis langsung ke repo di Google Drive; repo lokal 43 GB dihapus. Unggahan harian hanya blok yang berubah.',
      'Arsip penuh (Minggu / Backup sekarang) diunggah ke Drive dengan verifikasi ukuran + md5, lalu salinan server dihapus; Drive menyimpan 8 arsip penuh terbaru. Uji pulih dan Pulihkan… dari arsip Drive mengunduh berkasnya lebih dulu.',
      'Tab Arsip di Drive kini menampilkan rincian (manifest) dan SHA256 tiap arsip; pemantau memeriksa kesegaran arsip inti (48 jam), arsip penuh (9 hari), dan repo restic (48 jam) di Drive.',
    ],
  },
  {
    version: '1.21.0',
    date: '9 Oktober 2026',
    title: 'Aksi per baris di riwayat cadangan',
    summary:
      'Tabel riwayat Cadangan & Pemulihan kini punya kolom Aksi: detail lengkap untuk setiap jenis catatan, uji pulih / pulihkan langsung dari baris, serta hapus catatan dan berkas arsip (administrator utama).',
    highlights: [
      'Detail lengkap untuk semua jenis catatan (backup, offsite, restore, uji pulih, pemantau): status, keterangan, angka kunci, seluruh data tercatat dengan label yang mudah dibaca, sumber pencatat, dan ketersediaan arsip di server.',
      'Catatan backup yang arsipnya masih ada memuat Detail Backup penuh plus tombol Uji pulih dan Pulihkan… di dalam modal maupun di barisnya.',
      'Hapus catatan riwayat dan/atau berkas arsip di server (beserta .sha256 dan manifest) — wajib ketik HAPUS, dijalankan agen host, tercatat di Log Aktivitas Admin dan riwayat; salinan Google Drive dipindah ke folder versi pada sinkronisasi berikutnya, snapshot restic tidak berubah.',
      'Tombol hapus juga tersedia di tab Arsip server pada Sumber pemulihan.',
    ],
  },
  {
    version: '1.20.1',
    date: '9 Oktober 2026',
    title: 'Menu Cadangan & Pemulihan tersendiri',
    summary:
      'Cadangan & Pemulihan dipindah dari halaman Pengaturan menjadi menu Admin tersendiri "Cadangan" di sidebar (Laporan · Peringatan · Pengguna · Cadangan · Pengaturan).',
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
      'Tombol Unggah juga mendukung banyak file. Unggahan dikirim bertahap dengan indikator progres dan tetap mengikuti batas 256 MB per file (batas ini dihapus di v2.0.0).',
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
