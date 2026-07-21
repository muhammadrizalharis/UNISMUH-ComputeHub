#!/usr/bin/env python3
"""Generate PDF "Panduan Mahasiswa" -> frontend/public/panduan-mahasiswa.pdf.

Dijalankan MANUAL saat isi panduan berubah, hasilnya di-commit (dilayani sebagai
aset statis; tombol unduh ada di halaman Bantuan).
  cd backend && .venv/bin/python ../scripts/build_student_guide.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "panduan-mahasiswa.pdf"

BRAND = (31, 102, 242)
INK = (30, 41, 59)
MUTED = (100, 116, 139)

SECTIONS: list[tuple[str, list[str]]] = [
    ("1. Masuk ke ComputeHub", [
        "Buka https://computehub.lab.if.unismuh.ac.id lalu klik Masuk.",
        "Cara utama: tombol \"Masuk dengan SSO Unismuh\" - pakai akun kampus (NIM/email kampus).",
        "Akun lokal (username CHxxxx + password) hanya untuk akun yang dibuatkan admin.",
        "Satu akun hanya bisa login di SATU perangkat pada saat bersamaan.",
    ]),
    ("2. Dashboard & kuota", [
        "Dashboard menampilkan kondisi server langsung: CPU, RAM, dan 2x GPU NVIDIA L40S.",
        "Mahasiswa punya KUOTA GPU HARIAN (rolling 24 jam). Sisa kuota tampil di Dashboard.",
        "Grafik \"Pemakaian GPU Anda - 14 hari terakhir\" menunjukkan riwayat pemakaianmu.",
        "Ikon lonceng = notifikasi (job selesai/gagal, kuota hampir habis, pengumuman).",
    ]),
    ("3. Menjalankan job batch (latar belakang)", [
        "Menu Daftar Job -> Submit Job. Job batch TETAP JALAN walau laptop dimatikan.",
        "Sumber program: Tempel Kode, Notebook (.ipynb), Upload Folder, atau GitHub Repo.",
        "Belum tahu mulai dari mana? Klik salah satu \"Mulai dari contoh\" (Cek GPU, Training PyTorch, dll).",
        "Jadwalkan (opsional): isi tanggal & jam agar job jalan nanti, mis. malam saat GPU sepi.",
        "Selesai/gagal -> kamu dapat notifikasi lonceng + email. Log & output bisa diunduh di detail job.",
        "Job pakai scikit-learn/pandas saja? Pilih Perangkat = CPU (tidak memakai kuota GPU).",
    ]),
    ("4. Notebook interaktif (ala Google Colab)", [
        "Menu Buat Job -> Notebook Interaktif. Kernel Python hidup dengan GPU; variabel bertahan antar-sel.",
        "Jalankan sel: tombol Run atau Shift+Enter. Editor memberi peringatan error otomatis + autocomplete.",
        "Pintasan (saat tidak mengetik): A = sel di atas, B = di bawah, D D = hapus, M = markdown.",
        "Salah hapus? Klik \"Kembalikan sel\". Mau mulai bersih? Klik \"Bersihkan\".",
        "PENTING: notebook interaktif butuh koneksi. Simpan berkala (tombol Simpan) ke Penyimpanan.",
        "Kernel idle 30 menit dimatikan otomatis agar GPU bisa dipakai teman lain.",
    ]),
    ("5. Penyimpanan pribadi (/persist)", [
        "Menu Penyimpanan = folder pribadimu yang PERMANEN antar-sesi (terisolasi dari user lain).",
        "File hasil job/notebook, dataset upload, dan pip install --user tersimpan di sini.",
        "Bisa unduh per-file, per-folder (.zip), atau seluruh workspace. Ada kuota disk per-user.",
    ]),
    ("6. Mengakses dataset", [
        "Google Drive: perintah Colab (drive.mount) TIDAK berlaku di sini.",
        "File Drive yang di-share publik -> pakai gdown.download(\"LINK\", \"data.csv\").",
        "File sendiri -> tombol Upload di notebook / Upload Folder saat submit job.",
    ]),
    ("7. Aturan main (biar adil untuk semua)", [
        "GPU wajib untuk komputasi berat; job CPU-only pilih Perangkat CPU.",
        "Mahasiswa: 1 job berjalan pada satu waktu; sisanya otomatis antre (FIFO).",
        "Batas waktu job mahasiswa mengikuti SISA kuota harianmu.",
        "Kuota habis -> tunggu jendela 24 jam bergeser; kuota pulih otomatis.",
        "Job di Sampah terhapus permanen otomatis setelah 7 hari.",
    ]),
    ("8. Masalah umum & solusinya", [
        "\"CUDA out of memory\" -> kecilkan batch size / model; VRAM-mu dibatasi kebijakan.",
        "Job gagal instan -> baca log di detail job; sering karena error import/sintaks.",
        "\"GPU sedang penuh\" -> job tetap masuk ANTRIAN dan jalan otomatis saat kosong.",
        "Kernel mati saat ditinggal -> memang di-reap saat idle 30 menit; jalankan ulang sel.",
        "Email notifikasi masuk Spam -> tandai \"Bukan spam\" sekali agar berikutnya masuk inbox.",
    ]),
    ("9. Butuh bantuan?", [
        "Halaman Bantuan di aplikasi memuat panduan terbaru + FAQ.",
        "Hubungi admin lab / asisten untuk reset password atau kendala akun.",
    ]),
]


def san(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


def main() -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    # Sampul mini
    pdf.set_fill_color(*BRAND)
    pdf.rect(0, 0, 210, 34, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 18)
    pdf.set_xy(12, 8)
    pdf.cell(0, 10, san("Panduan Mahasiswa - UNISMUH ComputeHub"))
    pdf.set_font("helvetica", "", 11)
    pdf.set_xy(12, 19)
    pdf.cell(0, 8, san("Platform Komputasi GPU - Fakultas Teknik Informatika"))

    pdf.set_xy(12, 42)
    pdf.set_text_color(*INK)

    for title, points in SECTIONS:
        pdf.set_font("helvetica", "B", 12.5)
        pdf.set_text_color(*BRAND)
        pdf.multi_cell(0, 7, san(title))
        pdf.set_text_color(*INK)
        pdf.set_font("helvetica", "", 10.5)
        for p in points:
            pdf.set_x(16)
            pdf.multi_cell(0, 5.6, san(f"-  {p}"))
        pdf.ln(2.5)

    pdf.set_font("helvetica", "I", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 5, san(
        "Dokumen ini dibuat dari halaman Bantuan aplikasi. "
        "Versi terbaru selalu tersedia di menu Bantuan ComputeHub."
    ))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(bytes(pdf.output()))
    print(f"OK: {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
