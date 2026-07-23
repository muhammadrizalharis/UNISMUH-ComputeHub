#!/usr/bin/env python3
"""Generate PDF "Panduan Mahasiswa" -> frontend/public/panduan-mahasiswa.pdf.

Desain v2: sampul gelap ala banner GitHub (grid + judul + chip status), kartu
seksi berwarna dengan ikon, tabel, blok kode, dan kotak TIPS/PENTING — bukan
sekadar teks. Dijalankan MANUAL saat isi berubah, hasil di-commit:
  cd backend && .venv/bin/python ../scripts/build_student_guide.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "panduan-mahasiswa.pdf"
LOGO = ROOT / "frontend" / "public" / "logos" / "logo-unismuh-computehub-256.png"
FDIR = Path("/usr/share/fonts/truetype/dejavu")

# Palet (senada web + banner GitHub)
DARK = (10, 14, 23)        # latar sampul
PANEL = (13, 21, 38)       # panel gelap
BRAND = (31, 102, 242)     # biru brand
CYAN = (34, 211, 238)
VIOLET = (139, 92, 246)
GREEN = (34, 197, 94)
AMBER = (245, 158, 11)
ROSE = (244, 63, 94)
INK = (30, 41, 59)
MUTED = (100, 116, 139)
SOFT = (241, 245, 249)     # latar kartu terang
LINE = (226, 232, 240)

PAGE_W = 210


class Guide:
    def __init__(self) -> None:
        from fpdf import FPDF

        self.pdf = FPDF()
        p = self.pdf
        p.set_auto_page_break(auto=True, margin=18)
        p.add_font("Sans", "", str(FDIR / "DejaVuSans.ttf"))
        p.add_font("Sans", "B", str(FDIR / "DejaVuSans-Bold.ttf"))
        p.add_font("Sans", "I", str(FDIR / "DejaVuSans-Oblique.ttf"))
        p.add_font("Mono", "", str(FDIR / "DejaVuSansMono.ttf"))
        p.add_font("Mono", "B", str(FDIR / "DejaVuSansMono-Bold.ttf"))

    # ---------------------------------------------------------------- sampul
    def cover(self) -> None:
        p = self.pdf
        p.add_page()
        p.set_fill_color(*DARK)
        p.rect(0, 0, 210, 297, "F")
        # grid dekoratif
        p.set_draw_color(20, 32, 55)
        p.set_line_width(0.2)
        for y in range(0, 300, 12):
            p.line(0, y, 210, y)
        for x in range(0, 212, 12):
            p.line(x, 0, x, 297)
        # aksen atas & bawah
        p.set_fill_color(*CYAN)
        p.rect(0, 0, 210, 1.6, "F")
        p.set_fill_color(*VIOLET)
        p.rect(0, 295.4, 210, 1.6, "F")
        # logo dalam "cincin"
        p.set_draw_color(*CYAN)
        p.set_line_width(0.8)
        p.ellipse(105 - 23, 62 - 23, 46, 46)
        if LOGO.exists():
            p.image(str(LOGO), x=105 - 18, y=62 - 18, w=36, h=36)
        # judul
        p.set_text_color(125, 211, 252)
        p.set_font("Mono", "B", 13)
        p.set_xy(0, 96)
        p.cell(210, 8, "U N I S M U H", align="C")
        p.set_text_color(255, 255, 255)
        p.set_font("Sans", "B", 34)
        p.set_xy(0, 106)
        p.cell(210, 16, "ComputeHub", align="C")
        p.set_text_color(148, 163, 184)
        p.set_font("Mono", "", 10.5)
        p.set_xy(0, 124)
        p.cell(210, 7, "« PANDUAN MAHASISWA · GPU · DEEP LEARNING »", align="C")
        # boot line
        p.set_text_color(74, 222, 128)
        p.set_font("Mono", "", 9.5)
        p.set_xy(0, 136)
        p.cell(210, 6, "> initializing compute_core .......... [ OK ]", align="C")
        # chip status
        chips = [("SCHEDULER ONLINE", GREEN), ("2× L40S 46GB", (118, 185, 0)),
                 ("PY 3.10–3.13", CYAN), ("AI COPILOT", VIOLET)]
        total = sum(10 + len(t) * 2.1 + 8 for t, _ in chips) + (len(chips) - 1) * 4
        x = (210 - total) / 2
        y = 152
        for label, col in chips:
            w = 10 + len(label) * 2.1 + 8
            p.set_fill_color(*PANEL)
            p.set_draw_color(30, 58, 95)
            p.rect(x, y, w, 9, style="DF", round_corners=True, corner_radius=4.5)
            p.set_fill_color(*col)
            p.ellipse(x + 4, y + 3.2, 2.6, 2.6, "F")
            p.set_text_color(148, 163, 184)
            p.set_font("Mono", "", 7.5)
            p.set_xy(x + 8.5, y + 1.4)
            p.cell(w - 10, 6, label)
            x += w + 4
        # kartu ringkasan isi
        p.set_fill_color(*PANEL)
        p.set_draw_color(30, 58, 95)
        p.rect(30, 175, 150, 84, style="DF", round_corners=True, corner_radius=5)
        p.set_text_color(*CYAN)
        p.set_font("Sans", "B", 11)
        p.set_xy(38, 181)
        p.cell(0, 7, "Apa yang kamu pelajari di panduan ini")
        items = [
            "Login SSO · Dashboard & kuota GPU harian",
            "Job batch (jalan walau laptop mati) & notebook interaktif",
            "Memilih versi Python 3.10 – 3.13 per pekerjaan",
            "Asisten AI yang membaca error & tahu library server",
            "Penyimpanan pribadi, dataset, library, dan aturan main",
        ]
        p.set_text_color(203, 213, 225)
        p.set_font("Sans", "", 9.5)
        yy = 191
        for it in items:
            p.set_xy(40, yy)
            p.set_text_color(*CYAN)
            p.cell(5, 6, "◆")
            p.set_text_color(203, 213, 225)
            p.cell(0, 6, it)
            yy += 8
        p.set_text_color(*MUTED)
        p.set_font("Mono", "", 8)
        p.set_xy(0, 262)
        p.cell(210, 6, "computehub.lab.if.unismuh.ac.id", align="C")
        p.set_xy(0, 270)
        p.set_font("Sans", "", 8.5)
        p.cell(210, 6, "Fakultas Teknik · Informatika · UNISMUH Makassar", align="C")

    # ---------------------------------------------------------- komponen isi
    def _ensure(self, need: float) -> None:
        p = self.pdf
        if p.get_y() + need > 297 - 18:
            p.add_page()

    def header_bar(self) -> None:
        p = self.pdf
        p.set_fill_color(*DARK)
        p.rect(0, 0, 210, 14, "F")
        p.set_fill_color(*CYAN)
        p.rect(0, 14, 210, 0.8, "F")
        p.set_text_color(148, 163, 184)
        p.set_font("Mono", "", 8)
        p.set_xy(12, 3.4)
        p.cell(0, 7, "UNISMUH ComputeHub · Panduan Mahasiswa")
        p.set_xy(-60, 3.4)
        p.cell(48, 7, f"hal. {p.page_no() - 1}", align="R")

    def section(self, num: str, title: str, color: tuple) -> None:
        p = self.pdf
        self._ensure(22)
        y = p.get_y() + 3
        p.set_fill_color(*color)
        p.rect(12, y, 11, 11, style="F", round_corners=True, corner_radius=3)
        p.set_text_color(255, 255, 255)
        p.set_font("Sans", "B", 12)
        p.set_xy(12, y + 1.8)
        p.cell(11, 7, num, align="C")
        p.set_text_color(*INK)
        p.set_font("Sans", "B", 13.5)
        p.set_xy(27, y + 1.5)
        p.cell(0, 8, title)
        p.set_draw_color(*LINE)
        p.set_line_width(0.4)
        p.line(27, y + 11.5, 198, y + 11.5)
        p.set_y(y + 15)

    def bullets(self, points: list[str], accent: tuple = BRAND) -> None:
        p = self.pdf
        p.set_font("Sans", "", 9.8)
        for pt in points:
            self._ensure(12)
            y = p.get_y()
            p.set_text_color(*accent)
            p.set_xy(16, y)
            p.cell(5, 5.8, "•")
            p.set_text_color(*INK)
            p.set_xy(21, y)
            p.multi_cell(177, 5.8, pt)
            p.set_y(p.get_y() + 0.8)
        p.ln(1)

    def tip(self, text: str, kind: str = "tips") -> None:
        p = self.pdf
        styles = {
            "tips": (GREEN, (240, 253, 244), "TIPS"),
            "warn": (AMBER, (255, 251, 235), "PENTING"),
            "no": (ROSE, (255, 241, 242), "JANGAN"),
        }
        col, bg, label = styles[kind]
        p.set_font("Sans", "", 9.3)
        lines = len(p.multi_cell(160, 5.4, text, dry_run=True, output="LINES"))
        h = lines * 5.4 + 7
        self._ensure(h + 4)
        y = p.get_y() + 1
        p.set_fill_color(*bg)
        p.rect(16, y, 182, h, style="F", round_corners=True, corner_radius=3)
        p.set_fill_color(*col)
        p.rect(16, y, 2.2, h, style="F", round_corners=True, corner_radius=1.1)
        p.set_text_color(*col)
        p.set_font("Sans", "B", 8.2)
        p.set_xy(22, y + 2)
        p.cell(0, 4.5, label)
        p.set_text_color(*INK)
        p.set_font("Sans", "", 9.3)
        p.set_xy(22, y + 6.6)
        p.multi_cell(172, 5.4, text)
        p.set_y(y + h + 3)

    def code(self, lines: list[str]) -> None:
        p = self.pdf
        h = len(lines) * 5.4 + 6
        self._ensure(h + 4)
        y = p.get_y() + 1
        p.set_fill_color(*PANEL)
        p.rect(16, y, 182, h, style="F", round_corners=True, corner_radius=3)
        p.set_font("Mono", "", 8.8)
        yy = y + 3
        for ln in lines:
            p.set_xy(21, yy)
            p.set_text_color(74, 222, 128)
            p.cell(4, 5.4, ">")
            p.set_text_color(226, 232, 240)
            p.set_xy(26, yy)
            p.cell(0, 5.4, ln)
            yy += 5.4
        p.set_y(y + h + 3)

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float],
              accent: tuple = BRAND) -> None:
        p = self.pdf
        self._ensure(9 + len(rows) * 8)
        x0 = 16
        y = p.get_y() + 1
        p.set_fill_color(*accent)
        p.set_text_color(255, 255, 255)
        p.set_font("Sans", "B", 9)
        x = x0
        for htxt, w in zip(headers, widths):
            p.set_xy(x, y)
            p.cell(w, 7.5, f"  {htxt}", fill=True)
            x += w
        y += 7.5
        p.set_font("Sans", "", 9)
        for i, row in enumerate(rows):
            hrow = 7.5
            p.set_fill_color(*(SOFT if i % 2 == 0 else (255, 255, 255)))
            x = x0
            p.set_text_color(*INK)
            for cell, w in zip(row, widths):
                p.set_xy(x, y)
                p.cell(w, hrow, f"  {cell}", fill=True)
                x += w
            y += hrow
        p.set_draw_color(*LINE)
        p.rect(x0, p.get_y() + 1, sum(widths), y - (p.get_y() + 1))
        p.set_y(y + 3)

    # ------------------------------------------------------------------ body
    def build(self) -> None:
        p = self.pdf
        self.cover()

        p.add_page()
        self.header_bar()
        p.set_y(20)

        # 1 -----------------------------------------------------------------
        self.section("1", "Masuk ke ComputeHub", BRAND)
        self.bullets([
            "Buka https://computehub.lab.if.unismuh.ac.id lalu klik Masuk.",
            "Cara utama: tombol \"Masuk dengan SSO Unismuh\" — pakai akun kampus (NIM / email kampus).",
            "Akun lokal (username CHxxxx + password) hanya untuk akun yang dibuatkan admin.",
        ])
        self.tip("Satu akun hanya bisa login di SATU perangkat pada saat bersamaan. "
                 "Login di perangkat lain akan memutus sesi sebelumnya.", "warn")

        # 2 -----------------------------------------------------------------
        self.section("2", "Dashboard & kuota GPU harian", CYAN)
        self.bullets([
            "Dashboard menampilkan kondisi server langsung: CPU, RAM, dan 2× GPU NVIDIA L40S 46GB.",
            "Mahasiswa punya KUOTA GPU HARIAN (rolling 24 jam). Sisa kuota tampil di kartu Dashboard.",
            "Grafik \"Pemakaian GPU Anda — 14 hari terakhir\" menunjukkan riwayat pemakaianmu.",
            "Ikon lonceng = notifikasi: job selesai/gagal, kuota hampir habis, dan pengumuman admin.",
        ], CYAN)
        self.tip("Kuota terpakai hanya saat job/notebook GPU berjalan. Pekerjaan CPU "
                 "(pandas, scikit-learn) TIDAK memakan kuota GPU.", "tips")

        # 3 -----------------------------------------------------------------
        self.section("3", "Job batch — jalan walau laptop mati", VIOLET)
        self.bullets([
            "Menu Daftar Job → Submit Job. Job batch TETAP JALAN walau laptop dimatikan/koneksi putus.",
            "Sumber program: Tempel Kode, Notebook (.ipynb), Upload Folder, atau GitHub Repo.",
            "Belum tahu mulai dari mana? Klik \"Mulai dari contoh\" (Cek GPU, Training PyTorch, dll).",
            "Jadwalkan (opsional): isi tanggal & jam agar job jalan nanti — mis. malam hari saat GPU sepi.",
            "Selesai/gagal → notifikasi lonceng + email. Log & seluruh output bisa diunduh di detail job.",
        ], VIOLET)
        self.table(
            ["Kapan pakai apa", "Pilih"],
            [
                ["Training / deep learning / CUDA", "Perangkat: GPU"],
                ["pandas · scikit-learn · statistik", "Perangkat: CPU (hemat kuota)"],
                ["Kode harus jalan lama tanpa ditunggu", "Job batch (bukan notebook)"],
                ["Eksperimen cepat, lihat output langsung", "Notebook interaktif"],
            ],
            [110, 72], VIOLET,
        )

        # 4 -----------------------------------------------------------------
        self.section("4", "Notebook interaktif (ala Google Colab)", BRAND)
        self.bullets([
            "Menu Buat Job → Notebook Interaktif. Kernel Python hidup di GPU; variabel bertahan antar-sel.",
            "Jalankan sel: tombol Run atau Shift+Enter. Editor punya deteksi error + autocomplete otomatis.",
            "Pintasan (saat tidak mengetik): A = sel di atas · B = di bawah · D D = hapus · M = markdown.",
            "Salah hapus? Klik \"Kembalikan sel\". Mau mulai bersih? Klik \"Bersihkan\".",
            "Pindah menu / tab tertutup sebentar? Aman — output di-replay saat kamu kembali.",
            "Baru mulai? Buka menu TEMPLATE: contoh siap-jalan (transkripsi Whisper, OCR dokumen "
            "Indonesia, IndoBERT, YOLO, forecasting, ANOVA) — klik kartu, tekan Run, lalu ganti "
            "data contohnya dengan datamu.",
        ])
        self.tip("Notebook interaktif butuh koneksi aktif. Simpan pekerjaan berkala dengan tombol "
                 "Simpan (masuk ke Penyimpanan). Kernel idle 30 menit dimatikan otomatis "
                 "agar GPU bisa dipakai teman lain.", "warn")

        # 5 -----------------------------------------------------------------
        self.section("5", "Memilih versi Python (3.10 – 3.13)", GREEN)
        self.bullets([
            "Setiap job & notebook bisa memilih versi Python di form Submit Job (bawah nama job) "
            "atau dropdown di toolbar notebook.",
            "SEMUA versi berisi library lengkap yang sama (PyTorch CUDA, TensorFlow, scikit-learn, "
            "transformers, ultralytics, +250 paket).",
            "Dropdown notebook terkunci saat kernel hidup — matikan kernel dulu untuk ganti versi.",
        ], GREEN)
        self.table(
            ["Versi", "PyTorch", "Kapan dipakai"],
            [
                ["3.10 (default)", "2.5.1 + CUDA 12.1", "Paling teruji — pilihan aman"],
                ["3.11 / 3.12", "2.5.1 + CUDA 12.1", "Butuh fitur Python lebih baru"],
                ["3.13", "2.6.0 + CUDA 12.4", "Paket & torch paling mutakhir"],
            ],
            [38, 52, 92], GREEN,
        )

        # 6 -----------------------------------------------------------------
        self.section("6", "Asisten AI — copilot koding di notebook", VIOLET)
        self.bullets([
            "Panel kanan notebook. Ia MEMBACA isi sel + output error asli, lalu memperbaikinya.",
            "Ia juga TAHU library apa saja yang terpasang di server — rekomendasinya sesuai sistem.",
            "Tombol \"Terapkan\" menimpa sel aktif dengan kode AI; \"Sel baru\" menambah di bawah.",
            "Bisa memahami gambar: lampirkan screenshot error / plot untuk dianalisis.",
        ], VIOLET)
        self.tip("Cara bertanya yang efektif: jalankan sel yang error dulu, lalu tanya "
                 "\"perbaiki error di sel 2\". Asisten membaca traceback aslinya — "
                 "jawaban jadi tepat sasaran.", "tips")

        # 7 -----------------------------------------------------------------
        self.section("7", "Penyimpanan pribadi, library & model bersama", CYAN)
        self.bullets([
            "Menu Penyimpanan = folder pribadimu yang PERMANEN antar-sesi (user lain tak bisa melihat).",
            "File hasil job/notebook, dataset upload, dan hasil pip install tersimpan di sini.",
            "Bisa unduh per-file, per-folder (.zip), atau seluruh workspace. Ada kuota disk per-user.",
            "Library populer sudah terpasang - cek dulu sebelum install (import saja langsung):",
            "ML/DL: torch, tensorflow, sklearn, transformers, ultralytics (YOLO), timm, optuna, shap.",
            "Suara & teks: faster-whisper (transkripsi), evaluate/rouge/sacrebleu/jiwer (metrik NLP).",
            "OCR & dokumen: easyocr, pytesseract (bahasa Indonesia!), pdf2image, pypdf, python-docx.",
            "Data & statistik: pmdarima, sktime, prophet, pingouin (ANOVA ala SPSS), duckdb.",
            "MODEL BERSAMA di /opt/ch-models (tanpa download, gratis kuota): Whisper small &",
            "large-v3, IndoBERT, sentence-transformer multibahasa, YOLOv8, model EasyOCR.",
        ], CYAN)
        self.code([
            "pip install nama-paket        # otomatis masuk penyimpanan pribadimu",
            "import torch; torch.cuda.is_available()   # cek GPU siap",
            'm = WhisperModel("/opt/ch-models/faster-whisper-small", device="cuda")',
        ])
        self.tip("Install-mu tersimpan per-versi Python dan hanya untuk akunmu — "
                 "tidak mungkin merusak library bersama atau mengganggu teman.", "tips")

        # 8 -----------------------------------------------------------------
        self.section("8", "Mengakses dataset", AMBER)
        self.bullets([
            "Perintah Colab drive.mount TIDAK berlaku di sini (bukan Google Colab).",
            "File Google Drive yang di-share publik → unduh dengan gdown:",
        ], AMBER)
        self.code([
            "gdown.download(\"https://drive.google.com/uc?id=FILE_ID\", \"data.csv\")",
        ])
        self.bullets([
            "File sendiri → tombol Upload di notebook, atau Upload Folder saat submit job.",
            "Dataset Kaggle → siapkan kaggle.json di Penyimpanan lalu pakai library kaggle.",
        ], AMBER)

        # 9 -----------------------------------------------------------------
        self.section("9", "Aturan main (biar adil untuk semua)", ROSE)
        self.bullets([
            "GPU wajib untuk komputasi berat; pekerjaan CPU-only pilih Perangkat CPU.",
            "Mahasiswa: 1 job berjalan pada satu waktu; sisanya otomatis antre (FIFO).",
            "Batas waktu job mahasiswa mengikuti SISA kuota harianmu — job tak dipotong selama kuota ada.",
            "Kuota habis → tunggu jendela 24 jam bergeser; kuota pulih otomatis tanpa perlu lapor.",
            "Job di Sampah terhapus permanen otomatis setelah 7 hari.",
        ], ROSE)
        self.tip("Jangan menjalankan loop tak berujung untuk \"menahan\" GPU — kuotamu sendiri "
                 "yang habis, dan sistem otomatis menghentikannya.", "no")

        # 10 ----------------------------------------------------------------
        self.section("10", "Masalah umum & solusinya", AMBER)
        self.table(
            ["Gejala", "Solusi"],
            [
                ["CUDA out of memory", "Kecilkan batch size / model (VRAM dibatasi kebijakan)"],
                ["Job gagal instan", "Baca log di detail job — biasanya error import/sintaks"],
                ["\"GPU sedang penuh\"", "Job masuk ANTRIAN & jalan otomatis saat kosong"],
                ["Kernel mati saat ditinggal", "Normal (idle 30 mnt) — jalankan ulang sel"],
                ["ModuleNotFoundError", "pip install nama-paket, atau tanya Asisten AI"],
                ["Email masuk Spam", "Tandai \"Bukan spam\" sekali agar berikutnya normal"],
            ],
            [72, 110], AMBER,
        )

        # 11 ----------------------------------------------------------------
        self.section("11", "Butuh bantuan?", BRAND)
        self.bullets([
            "Halaman Bantuan di aplikasi memuat panduan terbaru + FAQ + info presisi GPU.",
            "Asisten AI di notebook siap menjawab pertanyaan koding kapan saja.",
            "Hubungi admin lab / asisten untuk reset password atau kendala akun.",
        ])

        p.ln(2)
        p.set_font("Sans", "I", 8.5)
        p.set_text_color(*MUTED)
        p.multi_cell(0, 5, "Dokumen ini dibuat dari halaman Bantuan aplikasi. "
                           "Versi terbaru selalu tersedia di menu Bantuan ComputeHub.")

    def save(self) -> None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(bytes(self.pdf.output()))
        print(f"OK: {OUT} ({OUT.stat().st_size // 1024} KB, {self.pdf.page_no()} halaman)")


def main() -> None:
    g = Guide()
    g.build()
    g.save()


if __name__ == "__main__":
    main()
