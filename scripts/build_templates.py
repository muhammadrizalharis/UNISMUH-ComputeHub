"""Generator 6 template notebook galeri ComputeHub -> frontend/public/templates/.

Template = file .ipynb statis (nbformat 4) + katalog index.json, disajikan backend
sebagai aset statis; halaman /templates menampilkan galeri, klik -> notebook terbuka
di editor interaktif (sel dimuat via parseNotebook di klien).

Prinsip isi: self-contained (jalan TANPA file user; data dibuat di sel), bahasa
Indonesia, manfaatkan library wave 1+2 + model bersama /opt/ch-models bila ada
(SELALU dengan fallback download otomatis bila folder shared belum tersedia).

Regen:  cd backend && .venv/bin/python ../scripts/build_templates.py
Lalu:   cp -r frontend/public/templates frontend/dist/   (agar live tanpa rebuild)
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "templates"


def md(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": source.splitlines(keepends=True),
        "outputs": [],
        "execution_count": None,
    }


def notebook(cells: list[dict]) -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


# --------------------------------------------------------------------------- #
# 1. Transkripsi audio — faster-whisper
# --------------------------------------------------------------------------- #
WHISPER = notebook([
    md("""# 🎙️ Transkripsi Audio → Teks (Whisper)

Ubah rekaman **wawancara / ceramah / podcast** menjadi teks otomatis dengan
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) — versi Whisper yang
4× lebih cepat, berjalan di GPU L40S. Mendukung **bahasa Indonesia**.

**Yang kamu pelajari:** memuat model dari folder bersama server (tanpa download),
transkripsi dengan *timestamp*, dan menyimpan hasil ke penyimpanan pribadimu."""),
    code("""# Sel 1 — muat model. Server menyediakan model BERSAMA di /opt/ch-models
# (tidak perlu download!). Bila belum tersedia, otomatis download ukuran kecil.
import os
from faster_whisper import WhisperModel

shared = "/opt/ch-models/faster-whisper-small"
sumber = shared if os.path.isdir(shared) else "small"
model = WhisperModel(sumber, device="cuda", compute_type="float16")
print("Model siap dari:", sumber)"""),
    code("""# Sel 2 — siapkan audio. GANTI dengan file audiomu: klik ikon upload di
# explorer / seret file .mp3/.wav ke sini, lalu isi nama filenya di bawah.
# (Untuk demo tanpa file, sel ini membuat audio ucapan sintetis sederhana.)
AUDIO = "audio_saya.mp3"   # <-- ganti dengan nama file audiomu

import numpy as np, soundfile as sf
if not os.path.exists(AUDIO):
    sr = 16000
    t = np.linspace(0, 2.0, 2 * sr)
    gelombang = 0.05 * np.sin(2 * np.pi * 220 * t)   # nada uji 2 detik
    sf.write("contoh_nada.wav", gelombang, sr)
    AUDIO = "contoh_nada.wav"
    print("File audiomu belum ada — memakai nada uji (hasil transkrip akan kosong).")
print("Audio:", AUDIO)"""),
    code("""# Sel 3 — transkripsi + timestamp per segmen.
segments, info = model.transcribe(AUDIO, language="id", vad_filter=True)
print(f"Terdeteksi bahasa: {info.language} (probabilitas {info.language_probability:.0%})\\n")

baris = []
for seg in segments:
    baris.append(f"[{seg.start:6.1f}s → {seg.end:6.1f}s] {seg.text.strip()}")
    print(baris[-1])
if not baris:
    print("(tidak ada ucapan terdeteksi — unggah rekaman asli di Sel 2)")"""),
    code("""# Sel 4 — simpan transkrip ke penyimpanan pribadimu (menu Penyimpanan).
from pathlib import Path
out = Path("/persist/transkrip.txt")
out.write_text("\\n".join(baris) or "(kosong)", encoding="utf-8")
print("Tersimpan:", out)"""),
    md("""**Langkah lanjut:** untuk akurasi maksimal ganti ke model besar:
`WhisperModel("/opt/ch-models/faster-whisper-large-v3", device="cuda", compute_type="float16")`
— tetap tanpa download karena sudah disediakan server. Ukur akurasi dengan
`jiwer` (Word Error Rate) bila kamu punya transkrip acuan."""),
])

# --------------------------------------------------------------------------- #
# 2. OCR dokumen Indonesia
# --------------------------------------------------------------------------- #
OCR = notebook([
    md("""# 📄 OCR Dokumen Bahasa Indonesia

Ekstrak teks dari **gambar / dokumen scan / PDF** dengan dua mesin sekaligus:
**Tesseract** (cepat, dukungan resmi bahasa Indonesia) dan **EasyOCR** (deep
learning, tahan gambar miring/noise). Template ini *self-contained* — gambar
contoh dibuat otomatis, tinggal ganti dengan filemu.

**Yang kamu pelajari:** OCR gambar, OCR PDF multi-halaman, dan membandingkan hasil."""),
    code("""# Sel 1 — buat gambar dokumen contoh (ganti dgn: img = Image.open("fileku.jpg")).
from PIL import Image, ImageDraw

img = Image.new("RGB", (900, 220), "white")
d = ImageDraw.Draw(img)
d.text((30, 30),  "SURAT KETERANGAN AKTIF KULIAH", fill="black")
d.text((30, 80),  "Nama    : Andi Pratama", fill="black")
d.text((30, 120), "Program : Teknik Informatika, Unismuh Makassar", fill="black")
d.text((30, 160), "Status  : Aktif — Semester Ganjil 2026/2027", fill="black")
img = img.resize((1800, 440))   # perbesar = OCR lebih akurat
img"""),
    code("""# Sel 2 — Tesseract dengan bahasa Indonesia (lang="ind").
import pytesseract
teks = pytesseract.image_to_string(img, lang="ind")
print(teks)"""),
    code("""# Sel 3 — EasyOCR (deep learning; pakai model bersama server bila ada).
import os, easyocr, numpy as np

kw = {}
if os.path.isdir("/opt/ch-models/easyocr"):
    kw = dict(model_storage_directory="/opt/ch-models/easyocr",
              user_network_directory="/opt/ch-models/easyocr", download_enabled=False)
reader = easyocr.Reader(["id", "en"], gpu=True, **kw)
for kotak, teks, skor in reader.readtext(np.array(img)):
    print(f"{skor:.0%}  {teks}")"""),
    code("""# Sel 4 — OCR PDF: konversi tiap halaman jadi gambar, lalu OCR.
# Contoh PDF dibuat dgn matplotlib; ganti "contoh.pdf" dengan PDF-mu.
import matplotlib.pyplot as plt
from pdf2image import convert_from_path

fig, ax = plt.subplots(figsize=(8.5, 4))
ax.text(0.05, 0.7, "LAPORAN PRAKTIKUM", fontsize=20, weight="bold")
ax.text(0.05, 0.45, "Pengolahan Citra Digital — Modul 3", fontsize=14)
ax.text(0.05, 0.25, "Disusun oleh Kelompok 5", fontsize=12)
ax.axis("off"); fig.savefig("contoh.pdf"); plt.close(fig)

halaman = convert_from_path("contoh.pdf", dpi=200)
for i, hal in enumerate(halaman, 1):
    print(f"--- Halaman {i} ---")
    print(pytesseract.image_to_string(hal, lang="ind"))"""),
    md("""**Langkah lanjut:** untuk dokumen nyata, unggah file lewat explorer lalu ganti
path di Sel 1/4. Gabungkan dengan `pandas` untuk mengekstrak tabel, atau simpan
hasil ke `/persist` agar permanen."""),
])

# --------------------------------------------------------------------------- #
# 3. IndoBERT — embedding & klasifikasi teks Indonesia
# --------------------------------------------------------------------------- #
INDOBERT = notebook([
    md("""# 🇮🇩 NLP Bahasa Indonesia dengan IndoBERT

Pakai **IndoBERT** (BERT yang dilatih khusus bahasa Indonesia) untuk mengubah
kalimat menjadi *embedding* — lalu bangun **pendeteksi kemiripan** dan
**klasifikasi sentimen** sederhana di atasnya. Model diambil dari folder bersama
server (tanpa download ±500 MB!).

**Yang kamu pelajari:** tokenisasi, mean-pooling embedding, cosine similarity,
dan melatih classifier ringan di atas fitur BERT."""),
    code("""# Sel 1 — muat IndoBERT dari model bersama server (fallback: download).
import os, torch
from transformers import AutoTokenizer, AutoModel

sumber = "/opt/ch-models/indobert-base-p1"
if not os.path.isdir(sumber):
    sumber = "indobenchmark/indobert-base-p1"
tok = AutoTokenizer.from_pretrained(sumber)
bert = AutoModel.from_pretrained(sumber).cuda().eval()
print("IndoBERT siap dari:", sumber)"""),
    code("""# Sel 2 — fungsi embedding kalimat (mean pooling atas token).
@torch.no_grad()
def embed(kalimat: list[str]) -> torch.Tensor:
    enc = tok(kalimat, padding=True, truncation=True, max_length=64, return_tensors="pt")
    enc = {k: v.cuda() for k, v in enc.items()}
    out = bert(**enc).last_hidden_state          # [batch, token, 768]
    mask = enc["attention_mask"].unsqueeze(-1)
    vec = (out * mask).sum(1) / mask.sum(1)       # rata-rata token nyata
    return torch.nn.functional.normalize(vec, dim=1).cpu()

emb = embed(["kuliah pagi ini seru sekali", "dosen menjelaskan dengan menarik",
             "server gpu kampus sangat membantu", "makanan di kantin kurang enak"])
print("Bentuk embedding:", tuple(emb.shape))"""),
    code("""# Sel 3 — kemiripan antar kalimat (cosine similarity) + heatmap.
import matplotlib.pyplot as plt

sim = emb @ emb.T
label = ["kuliah seru", "dosen menarik", "GPU membantu", "kantin kurang"]
fig, ax = plt.subplots(figsize=(5, 4))
im = ax.imshow(sim, cmap="viridis", vmin=0, vmax=1)
ax.set_xticks(range(4), label, rotation=30, ha="right")
ax.set_yticks(range(4), label)
for i in range(4):
    for j in range(4):
        ax.text(j, i, f"{sim[i, j]:.2f}", ha="center", va="center", color="white")
fig.colorbar(im); ax.set_title("Kemiripan semantik (IndoBERT)"); plt.tight_layout()"""),
    code("""# Sel 4 — klasifikasi sentimen mini: fitur BERT + LogisticRegression.
from sklearn.linear_model import LogisticRegression

data = [
    ("aplikasinya bagus dan cepat", 1), ("pelayanan ramah, sangat puas", 1),
    ("fiturnya lengkap, mantap", 1),    ("keren banget, recommended", 1),
    ("lambat dan sering error", 0),     ("kecewa, tidak sesuai harapan", 0),
    ("jelek, buang-buang uang", 0),     ("parah, tidak bisa dipakai", 0),
]
teks, y = [t for t, _ in data], [l for _, l in data]
clf = LogisticRegression().fit(embed(teks), y)

uji = ["produk ini luar biasa membantu", "menyesal beli, kualitas buruk"]
for kalimat, prob in zip(uji, clf.predict_proba(embed(uji))[:, 1]):
    print(f"{prob:.0%} positif — {kalimat}")"""),
    md("""**Langkah lanjut:** ganti data mini dengan dataset asli (upload CSV → `pandas`),
atau **fine-tune** penuh dengan `transformers.Trainer` untuk akurasi maksimal.
Dataset sentimen Indonesia populer: IndoNLU (SmSA)."""),
])

# --------------------------------------------------------------------------- #
# 4. Deteksi objek YOLO
# --------------------------------------------------------------------------- #
YOLO_NB = notebook([
    md("""# 🎯 Deteksi Objek dengan YOLOv8

Deteksi objek (orang, kendaraan, hewan, dll.) dalam gambar **dalam hitungan
milidetik** di GPU. Bobot model diambil dari folder bersama server —
langsung jalan tanpa download.

**Yang kamu pelajari:** inferensi YOLO, membaca hasil deteksi (kelas, skor,
kotak), dan visualisasi."""),
    code("""# Sel 1 — muat model dari folder bersama (fallback: download otomatis).
import os
from ultralytics import YOLO

bobot = "/opt/ch-models/yolo/yolov8n.pt"
model = YOLO(bobot if os.path.exists(bobot) else "yolov8n.pt")
print("Model:", model.model_name if hasattr(model, "model_name") else bobot)"""),
    code("""# Sel 2 — deteksi pada gambar contoh bawaan (ganti dengan gambarmu:
# hasil = model("foto_saya.jpg")).
from ultralytics.utils import ASSETS

hasil = model(ASSETS / "bus.jpg")[0]
print(f"{len(hasil.boxes)} objek terdeteksi:")
for box in hasil.boxes:
    nama = hasil.names[int(box.cls)]
    print(f"  {nama:12s} skor={float(box.conf):.0%}  kotak={[round(v) for v in box.xyxy[0].tolist()]}")"""),
    code("""# Sel 3 — visualisasi hasil (kotak + label digambar otomatis).
import matplotlib.pyplot as plt

anotasi = hasil.plot()               # BGR -> balik ke RGB utk matplotlib
plt.figure(figsize=(7, 8))
plt.imshow(anotasi[..., ::-1])
plt.axis("off"); plt.title("Deteksi YOLOv8"); plt.show()"""),
    code("""# Sel 4 — (opsional) segmentasi instance: bentuk objek, bukan sekadar kotak.
seg_bobot = "/opt/ch-models/yolo/yolov8n-seg.pt"
seg = YOLO(seg_bobot if os.path.exists(seg_bobot) else "yolov8n-seg.pt")
hseg = seg(ASSETS / "bus.jpg")[0]
plt.figure(figsize=(7, 8)); plt.imshow(hseg.plot()[..., ::-1])
plt.axis("off"); plt.title("Segmentasi instance"); plt.show()"""),
    md("""**Langkah lanjut:** latih dengan datasetmu sendiri (`model.train(data="data.yaml",
epochs=50)`) — L40S sanggup; unggah dataset lewat menu Upload Folder. Untuk video,
`model("video.mp4", stream=True)`."""),
])

# --------------------------------------------------------------------------- #
# 5. Forecasting time-series
# --------------------------------------------------------------------------- #
FORECAST = notebook([
    md("""# 📈 Prediksi Time-Series (Auto-ARIMA)

Ramalkan nilai masa depan (penjualan, suhu, harga, jumlah pengunjung…) dengan
**pmdarima `auto_arima`** — mencari model ARIMA terbaik **otomatis**, tanpa
tuning manual. Data contoh dibuat di sel (ganti dengan CSV-mu).

**Yang kamu pelajari:** dekomposisi pola, pemilihan model otomatis, forecast
dengan interval kepercayaan, dan evaluasi MAE/MAPE."""),
    code("""# Sel 1 — data contoh: penjualan harian 2 tahun (tren + musiman mingguan).
# Ganti dengan datamu:  df = pd.read_csv("data.csv", parse_dates=["tanggal"])
import numpy as np, pandas as pd

rng = np.random.default_rng(42)
hari = pd.date_range("2024-07-01", periods=730, freq="D")
tren = np.linspace(100, 180, 730)
musiman = 25 * np.sin(2 * np.pi * np.arange(730) / 7)        # pola mingguan
noise = rng.normal(0, 8, 730)
df = pd.DataFrame({"tanggal": hari, "penjualan": tren + musiman + noise})
df = df.set_index("tanggal")
df.plot(figsize=(11, 3), title="Penjualan harian (2 tahun)");"""),
    code("""# Sel 2 — bagi data latih/uji & cari model ARIMA terbaik OTOMATIS.
from pmdarima import auto_arima

latih, uji = df.iloc[:-30], df.iloc[-30:]     # 30 hari terakhir utk evaluasi
model = auto_arima(
    latih["penjualan"], seasonal=True, m=7,   # musiman mingguan
    stepwise=True, suppress_warnings=True, trace=True,
)
print("\\nModel terpilih:", model.order, "musiman:", model.seasonal_order)"""),
    code("""# Sel 3 — forecast 30 hari + interval kepercayaan 95%, lalu evaluasi.
import matplotlib.pyplot as plt

ramal, ik = model.predict(n_periods=30, return_conf_int=True)
ramal = pd.Series(ramal, index=uji.index)

mae = (ramal - uji["penjualan"]).abs().mean()
mape = ((ramal - uji["penjualan"]).abs() / uji["penjualan"]).mean() * 100
print(f"MAE = {mae:.1f}   MAPE = {mape:.1f}%")

fig, ax = plt.subplots(figsize=(11, 4))
latih["penjualan"].iloc[-120:].plot(ax=ax, label="data latih")
uji["penjualan"].plot(ax=ax, label="aktual", color="black")
ramal.plot(ax=ax, label="forecast", color="crimson")
ax.fill_between(uji.index, ik[:, 0], ik[:, 1], alpha=0.2, color="crimson", label="IK 95%")
ax.legend(); ax.set_title("Forecast 30 hari ke depan"); plt.tight_layout()"""),
    md("""**Langkah lanjut:** coba `prophet` (juga terpasang) untuk data dengan hari
libur, atau `sktime` untuk pipeline ML time-series penuh (klasifikasi, regresi,
validasi silang temporal)."""),
])

# --------------------------------------------------------------------------- #
# 6. Statistik penelitian
# --------------------------------------------------------------------------- #
STATISTIK = notebook([
    md("""# 🧮 Statistik Penelitian: Uji ANOVA (ala SPSS)

Analisis statistik lengkap untuk skripsi — langsung di notebook dengan
**pingouin**: uji normalitas, homogenitas, ANOVA satu arah, *post-hoc*, dan
*effect size*. Output berupa tabel rapi yang siap disalin ke laporan.

**Yang kamu pelajari:** alur uji hipotesis yang benar + visualisasi publikasi."""),
    code("""# Sel 1 — data contoh: nilai ujian 3 kelompok metode belajar.
# Ganti dengan datamu:  df = pd.read_excel("data.xlsx")
import numpy as np, pandas as pd, pingouin as pg

rng = np.random.default_rng(7)
df = pd.DataFrame({
    "metode": ["Ceramah"] * 30 + ["Diskusi"] * 30 + ["Praktikum"] * 30,
    "nilai": np.concatenate([
        rng.normal(70, 8, 30),   # Ceramah
        rng.normal(75, 8, 30),   # Diskusi
        rng.normal(82, 8, 30),   # Praktikum
    ]).round(1),
})
df.groupby("metode")["nilai"].describe().round(2)"""),
    code("""# Sel 2 — uji asumsi: normalitas per kelompok (Shapiro-Wilk) & homogenitas (Levene).
print("Normalitas (p > 0.05 = normal):")
display(pg.normality(df, dv="nilai", group="metode").round(4))
print("Homogenitas varians (p > 0.05 = homogen):")
display(pg.homoscedasticity(df, dv="nilai", group="metode").round(4))"""),
    code("""# Sel 3 — ANOVA satu arah + effect size (eta-squared).
anova = pg.anova(df, dv="nilai", between="metode", detailed=True)
display(anova.round(4))
p = anova.loc[0, "p-unc"]
print(f"Kesimpulan: {'ADA' if p < 0.05 else 'TIDAK ada'} perbedaan signifikan antar metode (p={p:.4f}).")"""),
    code("""# Sel 4 — post-hoc Tukey HSD: pasangan mana yang berbeda?
pg.pairwise_tukey(df, dv="nilai", between="metode").round(4)"""),
    code("""# Sel 5 — visual publikasi: boxplot + titik data.
import matplotlib.pyplot as plt, seaborn as sns

fig, ax = plt.subplots(figsize=(7, 4))
sns.boxplot(data=df, x="metode", y="nilai", hue="metode", palette="Set2", ax=ax, legend=False)
sns.stripplot(data=df, x="metode", y="nilai", color="0.25", size=3, ax=ax)
ax.set_title("Perbandingan nilai per metode belajar")
plt.tight_layout()"""),
    md("""**Langkah lanjut:** data tidak normal? pakai `pg.kruskal` (non-parametrik).
Dua kelompok saja? `pg.ttest`. Ada 2 faktor? `pg.anova(between=["a","b"])`.
Korelasi & regresi juga ada: `pg.corr`, `pg.linear_regression`."""),
])

# --------------------------------------------------------------------------- #
# Katalog galeri (dibaca halaman /templates)
# --------------------------------------------------------------------------- #
KATALOG = [
    {
        "id": "whisper-transkripsi",
        "judul": "Transkripsi Audio → Teks",
        "desc": "Ubah rekaman wawancara/ceramah jadi teks otomatis (bahasa Indonesia) dengan Whisper di GPU.",
        "tags": ["Speech", "Whisper", "GPU"],
        "level": "Pemula",
        "gradien": "from-sky-500 to-blue-600",
        "emoji": "🎙️",
    },
    {
        "id": "ocr-dokumen",
        "judul": "OCR Dokumen Indonesia",
        "desc": "Ekstrak teks dari gambar, dokumen scan, dan PDF — Tesseract (lang ind) + EasyOCR.",
        "tags": ["OCR", "Computer Vision", "PDF"],
        "level": "Pemula",
        "gradien": "from-amber-500 to-orange-600",
        "emoji": "📄",
    },
    {
        "id": "indobert-sentimen",
        "judul": "NLP Indonesia (IndoBERT)",
        "desc": "Embedding kalimat, kemiripan semantik, dan klasifikasi sentimen bahasa Indonesia.",
        "tags": ["NLP", "BERT", "Sentimen"],
        "level": "Menengah",
        "gradien": "from-rose-500 to-red-600",
        "emoji": "🇮🇩",
    },
    {
        "id": "yolo-deteksi",
        "judul": "Deteksi Objek (YOLOv8)",
        "desc": "Deteksi & segmentasi objek dalam gambar dalam milidetik — bobot sudah disediakan server.",
        "tags": ["Computer Vision", "YOLO", "GPU"],
        "level": "Pemula",
        "gradien": "from-violet-500 to-purple-600",
        "emoji": "🎯",
    },
    {
        "id": "forecasting-arima",
        "judul": "Prediksi Time-Series",
        "desc": "Ramalkan penjualan/suhu/harga dengan auto-ARIMA — pemilihan model otomatis + interval kepercayaan.",
        "tags": ["Time-Series", "Forecasting", "Statistik"],
        "level": "Menengah",
        "gradien": "from-emerald-500 to-teal-600",
        "emoji": "📈",
    },
    {
        "id": "statistik-anova",
        "judul": "Statistik Penelitian (ANOVA)",
        "desc": "Uji normalitas, ANOVA, post-hoc Tukey, effect size — ala SPSS, siap salin ke skripsi.",
        "tags": ["Statistik", "ANOVA", "Skripsi"],
        "level": "Pemula",
        "gradien": "from-cyan-500 to-sky-600",
        "emoji": "🧮",
    },
]

NOTEBOOKS = {
    "whisper-transkripsi": WHISPER,
    "ocr-dokumen": OCR,
    "indobert-sentimen": INDOBERT,
    "yolo-deteksi": YOLO_NB,
    "forecasting-arima": FORECAST,
    "statistik-anova": STATISTIK,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for tid, nb in NOTEBOOKS.items():
        path = OUT / f"{tid}.ipynb"
        path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
        n_cells = len(nb["cells"])
        print(f"[ok] {path.relative_to(ROOT)} ({n_cells} sel)")
    idx = OUT / "index.json"
    idx.write_text(json.dumps(KATALOG, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ok] {idx.relative_to(ROOT)} ({len(KATALOG)} template)")


if __name__ == "__main__":
    main()
