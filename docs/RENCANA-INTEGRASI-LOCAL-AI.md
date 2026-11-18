# Rencana: Pemanfaatan Layanan local-ai untuk ComputeHub

Status: **Sebagian dikerjakan (v1.41.0).** Usulan 2, 3, dan 4 sudah diterapkan;
usulan 1 disepakati untuk tidak dikerjakan (lihat alasan di bawah).
Disusun atas permintaan admin (Muhammad Rizal Haris).

## Latar belakang

Server hpc-ai juga menjalankan stack **local-ai** (Docker Compose) yang menyediakan
berbagai layanan AI. Dokumen ini memetakan layanan mana yang dapat memperkaya
ComputeHub dan mana yang sebaiknya tetap berdiri sendiri, agar pengembangan
berikutnya terarah dan tidak tumpang tindih.

Saat ini ComputeHub baru memanfaatkan **Ollama** (port 11434) untuk Asisten AI,
bot Panduan, gateway kunci API, dan Copilot di devbox.

## Penjelasan singkat tiap layanan

| Layanan | Fungsi |
|---|---|
| **Ollama** (11434, 11435, 11436, 11437, 11438) | Menjalankan model bahasa (LLM) secara lokal. 11434 adalah penyeimbang beban; 11435/11436 instance per GPU; 11437 khusus model embedding `bge-m3`; 11438 untuk model besar dua GPU. |
| **SearXNG** (1003) | Mesin pencari gabungan yang mengembalikan hasil dalam JSON, termasuk kategori ilmiah. |
| **Crawl4AI** (1004) | Mengambil isi utama sebuah halaman web menjadi teks bersih. |
| **Apache Tika** (1007) | Mengekstrak teks dari berbagai jenis berkas (PDF, DOCX, PPTX, XLSX). Ringan dan tanpa GPU. |
| **Docling** (1010) | Ekstraksi PDF yang lebih cermat (tabel, rumus, hasil pindaian/OCR) menjadi Markdown. Menggunakan GPU (±2,1 GB). |
| **Qdrant** (1006) | Basis data vektor untuk pencarian berdasarkan kemiripan makna. |
| **Jupyter** (1008) | Sandbox eksekusi kode Python, menyala sesuai permintaan. |
| **Nextcloud + ONLYOFFICE** (1011/1012) | Penyimpanan berkas dan penyunting dokumen di peramban. |
| **n8n** (1002) | Otomasi alur kerja; dipakai local-ai untuk proses RAG dokumen Nextcloud. |
| **Open WebUI** (1005) | Antarmuka obrolan untuk Ollama. |

## Usulan prioritas

| # | Layanan | Manfaat bagi ComputeHub | Status |
|---|---|---|---|
| 1 | **Instance Ollama tersendiri** (11435/11436) | Asisten AI, bot Panduan, dan gateway tetap responsif ketika instance utama sedang melayani beban dari aplikasi lain. | **Tidak dikerjakan.** Ollama sudah memuat model sesuai permintaan dan GPU tidak selalu penuh; instance tersendiri hanya mengurangi antrean saat 11434 sibuk, tidak menambah kapasitas GPU. |
| 2 | **Apache Tika** (+ Docling sebagai cadangan) | Pengguna dapat melampirkan PDF/DOCX/PPTX ke Asisten AI untuk dibahas. | **Selesai.** Tombol klip di Asisten AI → `POST /assistant/extract`. Tika dahulu; Docling dipakai bila hasil Tika terlalu sedikit (PDF pindaian). Berkas tidak disimpan. |
| 3 | **SearXNG** (+ Crawl4AI) | Asisten AI dapat merujuk informasi dan dokumentasi terbaru dari web. | **Selesai.** Tombol "Cari di web" di Asisten AI; jawaban mencantumkan sumber bernomor. Crawl4AI mengambil isi 2 halaman teratas. |
| 4 | **bge-m3 + Qdrant** (RAG) | Bot Panduan menjawab dari kumpulan dokumentasi yang lebih luas; peluang fitur "tanya dokumen". | **Selesai.** Koleksi Qdrant `computehub_help` diisi ulang otomatis tiap jam dari panduan PDF, `docs/PANDUAN-PENGGUNA.md`, dan `docs/panduan/*`; potongan relevan ditambahkan ke prompt bot Bantuan. |

### Konfigurasi (backend/.env)

Semua fitur nonaktif bila alamatnya kosong, sehingga ComputeHub tetap berjalan tanpa local-ai.

| Fitur | Variabel |
|---|---|
| Lampiran dokumen | `ASSISTANT_TIKA_URL`, `ASSISTANT_DOCLING_URL` (opsional), `ASSISTANT_DOC_MAX_BYTES`, `ASSISTANT_DOC_MAX_FILES`, `ASSISTANT_DOC_MAX_CHARS` |
| Cari di web | `ASSISTANT_SEARXNG_URL`, `ASSISTANT_CRAWL4AI_URL` + `ASSISTANT_CRAWL4AI_TOKEN` (opsional), `ASSISTANT_WEB_RESULTS`, `ASSISTANT_WEB_FETCH_PAGES`, `ASSISTANT_WEB_MAX_CHARS` |
| RAG bot Bantuan | `HELP_RAG_QDRANT_URL`, `HELP_RAG_EMBED_URL`, `HELP_RAG_EMBED_MODEL`, `HELP_RAG_COLLECTION`, `HELP_RAG_TOP_K`, `HELP_RAG_MIN_SCORE`, `HELP_RAG_REINDEX_SECONDS` |

## Layanan yang tidak direncanakan untuk ComputeHub

| Layanan | Pertimbangan |
|---|---|
| Jupyter | Fungsinya sudah tersedia di ComputeHub (notebook, kernel GPU, devbox) lengkap dengan kuota dan pelaporan. |
| Nextcloud, ONLYOFFICE | Di luar cakupan; ComputeHub sudah memiliki penyimpanan per pengguna dan pencadangan. |
| n8n | Backend ComputeHub dapat memanggil layanan terkait secara langsung sehingga lebih sederhana. |
| Open WebUI, llm-gateway | Peran serupa sudah dipenuhi Asisten AI dan gateway ComputeHub. |
| Ollama model besar (11438) | Memakai kedua GPU sekaligus sehingga berpotensi mengurangi ruang bagi pengguna ComputeHub. |
| ComfyUI, Tor | Bukan bagian stack local-ai untuk ComputeHub / tidak relevan dengan kebutuhan platform. |

## Catatan keamanan (saran)

Beberapa layanan (Jupyter 1008 dan ComfyUI 8188/8180/8181) masih mendengarkan pada
semua antarmuka jaringan. Disarankan membatasinya ke `127.0.0.1` atau jaringan
Tailscale, dengan koordinasi bersama pemilik layanan masing-masing.

## Hal lain yang menunggu keputusan

- Mendaftarkan kembali project `local-ai` sebagai peminjam cadangan VRAM melalui panel Admin.
- Skrip *on-demand* untuk Docling (menyala saat dibutuhkan, berhenti saat menganggur) — kini butir D3 di [RENCANA-FITUR-V2.md](RENCANA-FITUR-V2.md).
- ~~Merapikan kernel notebook lama yang sudah tidak terpakai.~~ Selesai (14 kernel dihentikan).
- ~~Penyempurnaan pencatatan `durasi_detik` untuk permintaan gateway non-stream.~~ Selesai (v1.41.1).
- ~~Penyusunan draf daftar fitur v2.~~ Selesai: [RENCANA-FITUR-V2.md](RENCANA-FITUR-V2.md).

## Langkah selanjutnya

1. Memantau pemakaian fitur dokumen dan pencarian web setelah rilis.
2. Menambah materi panduan di `docs/panduan/` agar jawaban bot Bantuan makin lengkap.
3. Memperbarui status dokumen ini setiap kali ada butir baru yang disepakati.
