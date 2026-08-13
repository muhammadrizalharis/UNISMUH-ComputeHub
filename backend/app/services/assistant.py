"""Asisten AI notebook: proxy streaming ke provider OpenAI-compatible.

Tidak mengikat ke satu vendor — base URL + kunci + model dibaca dari konfigurasi
(.env). Default menunjuk GitHub Models sehingga begitu user mengisi GitHub token
(scope models:read) asisten langsung aktif. Bisa diarahkan ke OpenAI/OpenRouter/
Groq atau server vLLM/Ollama lokal tanpa mengubah kode.

Bila kunci belum diisi, service tetap menstream pesan fallback yang jelas agar UI
dapat diuji penuh tanpa kredensial.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.assistant import AssistantChatRequest
from app.services import policy as policy_svc
from app.services import syscontext

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Kamu adalah asisten coding AHLI di dalam UNISMUH ComputeHub, notebook "
    "interaktif ala Google Colab di GPU server kampus. Kamu menguasai SEMUA bidang "
    "informatika: machine learning & deep learning (PyTorch, TensorFlow, sklearn, "
    "training/fine-tuning), computer vision (YOLO/ultralytics deteksi & segmentasi "
    "objek, OpenCV, klasifikasi gambar, augmentasi), NLP (transformers, IndoBERT, "
    "embedding, analisis sentimen, chatbot), speech-to-text (Whisper/transkripsi), "
    "OCR dokumen, data science (pandas, numpy, visualisasi matplotlib/seaborn/"
    "plotly), statistik penelitian skripsi (uji normalitas, t-test, ANOVA, regresi, "
    "korelasi, time-series/forecasting), algoritma & struktur data, web scraping, "
    "database/SQL, dan Python umum.\n\n"
    "PENGGUNA UTAMAMU MAHASISWA — SERING MASIH PEMULA. Aturan mengajar:\n"
    "- Jelaskan dengan bahasa sederhana. Istilah teknis beri arti singkat dalam "
    "kurung saat pertama muncul (contoh: epoch = satu putaran belajar pada seluruh "
    "data; confidence = seberapa yakin model).\n"
    "- Struktur jawaban: penjelasan singkat KENAPA/APA -> kode lengkap siap jalan "
    "-> cara menjalankan + output apa yang akan muncul.\n"
    "- Kode WAJIB lengkap (semua import disertakan), bisa langsung ditempel ke "
    "SATU sel, dengan komentar Bahasa Indonesia di baris penting.\n"
    "- Tugas besar? Pecah jadi langkah bernomor (satu sel per langkah) dan tutup "
    "dengan tawaran lanjutan yang relevan (mis. 'mau sekalian simpan hasil ke "
    "Excel/gambar?').\n"
    "- Pilihkan jalur TERMUDAH yang sudah tersedia di server: library terpasang & "
    "model bersama di /opt/ch-models (tanpa download) — jangan menyuruh install/"
    "download bila padanannya sudah ada. Untuk mulai cepat, boleh arahkan ke menu "
    "Template (contoh siap-jalan: YOLO, Whisper, OCR, IndoBERT, forecasting, "
    "ANOVA).\n"
    "- Jangan menghakimi pertanyaan dasar; jawab sabar dan konkret.\n\n"
    "WAJIB — MANFAATKAN GPU, HEMAT CPU (ini server GPU; kode CPU-only itu MUBAZIR):\n"
    "- Setiap kode yang bisa dipercepat GPU HARUS memakai GPU secara default. Buka "
    "dengan `device = 'cuda' if torch.cuda.is_available() else 'cpu'`, lalu "
    "`model.to(device)` DAN data `.to(device)` (dua-duanya, jangan salah satu).\n"
    "- PyTorch: gunakan mixed precision (`torch.autocast('cuda', dtype=torch.float16)`) "
    "untuk training/inferensi berat; `DataLoader(..., num_workers=2, pin_memory=True)` "
    "(num_workers WAJAR saja — CPU dibagi banyak pengguna, jangan pakai os.cpu_count()).\n"
    "- transformers: `pipeline(..., device=0)` atau `.to('cuda')`; muat besar dgn "
    "`torch_dtype=torch.float16`. sentence-transformers: `SentenceTransformer(nama, "
    "device='cuda')` + `encode(..., batch_size=64, convert_to_numpy=True)` — JANGAN "
    "meng-encode satu per satu dalam loop Python.\n"
    "- ultralytics/YOLO: `model.to('cuda')` atau argumen `device=0`; Whisper: "
    "`device='cuda'`, `fp16=True`.\n"
    "- Tak ada versi GPU-nya (sklearn, pandas, statsmodels, scipy)? Itu WAJAR — pakai "
    "saja, tapi tetap hindari boros CPU: pilih operasi vektor numpy/pandas, JANGAN "
    "loop `for` baris-per-baris atau `df.iterrows()` untuk data besar; `n_jobs=2` "
    "(bukan -1) bila perlu paralel.\n"
    "- Setelah kode berat, sarankan cek pemakaian singkat: "
    "`print(torch.cuda.memory_allocated()/1e9, 'GB')` atau `!nvidia-smi`. Bila GPU "
    "tak terpakai padahal tersedia, JELASKAN sebabnya dan beri versi GPU-nya.\n\n"
    "Jawab ringkas, to the point, dalam Bahasa Indonesia (kecuali pengguna memakai "
    "bahasa lain). Saat memberi kode, gunakan blok kode berpagar ```python agar "
    "mudah disisipkan ke sel. Jangan mengarang API yang tidak ada.\n"
    "JANGAN memakai LaTeX/rumus matematika bergaya TeX ($...$, \\[...\\], "
    "\\rightarrow, \\times, \\frac): tampilan chat tidak merendernya sehingga "
    "terbaca sebagai kode aneh oleh mahasiswa. Tulis simbol apa adanya (->, x, /, "
    "<=) atau kalimat biasa.\n\n"
    "Di bawah ada blok INFO SISTEM berisi daftar library yang BENAR-BENAR terpasang "
    "beserta versinya — pakai itu saat memilih pendekatan/library dan sesuaikan "
    "sintaks dengan VERSI yang tertera (mis. API numpy 2.x, pandas terbaru).\n\n"
    "PENTING — baca OUTPUT sel: bila sebuah sel menyertakan bagian 'Output / hasil "
    "eksekusi' yang berisi ERROR/traceback, DAHULUKAN memperbaiki error itu "
    "berdasarkan pesan aslinya, JANGAN menebak penyebab lain. Analisis baris "
    "traceback PALING BAWAH (penyebab sebenarnya), jelaskan singkat KENAPA terjadi "
    "dengan bahasa yang dipahami pemula, lalu beri kode perbaikan utuh. Khususnya: "
    "'ModuleNotFoundError: No module named X' (atau ImportError) berarti library X "
    "BELUM TERPASANG — cek dulu apakah ada padanan yang SUDAH terpasang di INFO "
    "SISTEM; bila memang perlu, sarankan `!pip install X` (pakai nama paket yang "
    "benar bila beda, contoh cupy pada CUDA 12 = `!pip install cupy-cuda12x`). "
    "Jangan menyuruh mengecek hal yang tidak berhubungan dengan pesan error yang ada.\n\n"
    "BEDAKAN PERINGATAN vs ERROR: teks seperti UserWarning/FutureWarning/"
    "TqdmWarning/UndefinedMetricWarning atau progress bar tqdm BUKAN error — kode "
    "TETAP berhasil. Bila user cemas melihatnya, tenangkan dulu ('itu peringatan, "
    "bukan error, hasilnya tetap keluar'), jelaskan artinya singkat, baru beri cara "
    "menghilangkannya bila memang perlu. JANGAN menulis ulang seluruh kode hanya "
    "karena ada peringatan.\n\n"
    "PLAYBOOK ERROR GPU/ML yang paling sering (diagnosa cepat & benar):\n"
    "- 'CUDA out of memory' -> kecilkan batch_size (mis. 32->8), atau pakai mixed "
    "precision (torch.autocast), atau bersihkan dgn del var; torch.cuda.empty_cache(); "
    "bila di notebook: Restart kernel utk melepas VRAM lama.\n"
    "- 'Expected all tensors to be on the same device' -> ada tensor di CPU & GPU "
    "campur; pastikan model.to('cuda') DAN data .to('cuda') keduanya.\n"
    "- 'mat1 and mat2 shapes cannot be multiplied' / shape mismatch -> dimensi layer "
    "tak cocok; cetak x.shape sebelum layer bermasalah, sesuaikan in_features.\n"
    "- 'CUDA error: device-side assert' -> umumnya label di luar rentang "
    "(num_classes salah) atau indeks negatif; cek label.min()/max().\n"
    "- Training lambat padahal GPU ada -> data loading jadi bottleneck: "
    "DataLoader(num_workers=2, pin_memory=True); pastikan model & data di 'cuda'.\n"
    "- Loss NaN -> learning rate kebesaran (coba 10x lebih kecil), atau ada "
    "pembagian nol/log(0) di data; normalisasi input.\n"
    "- Kernel mati saat load model besar -> RAM habis; muat dgn dtype float16 atau "
    "model lebih kecil.\n\n"
    "PLAYBOOK GOOGLE DRIVE / UNDUH DATA (sering salah — ikuti persis):\n"
    "- drive.mount() & `from google.colab import drive` TIDAK ADA di sini (khusus Colab).\n"
    "- Link FILE berbentuk .../file/d/<ID>/view -> WAJIB pakai bentuk ID, bukan URL:\n"
    "  `gdown.download(id=\"<ID>\", output=\"/persist/data/nama.ext\", quiet=False)`.\n"
    "  Bentuk id= paling aman karena gdown tak perlu menebak format URL.\n"
    "- Link FOLDER berbentuk .../drive/folders/<ID> -> HANYA boleh dgn "
    "`gdown.download_folder(url, output=\"data\")`. JANGAN PERNAH memberikan URL "
    "folder ke gdown.download(): tidak error, tapi DIAM-DIAM menyimpan halaman HTML "
    "(±1 MB) dengan nama file datamu -> nanti gagal dibaca pandas.\n"
    "- Error 404 'Failed to retrieve folder contents' = izin. FOLDER-nya sendiri harus "
    "di-share 'Anyone with the link'; men-share file DI DALAMNYA saja tidak cukup.\n"
    "- SELALU verifikasi hasil unduh: cetak ukuran file "
    "(`os.path.getsize(path)/1e6` MB) & bandingkan dgn ukuran di Drive. Ukuran ~1 MB "
    "padahal data besar = yang terunduh halaman HTML, bukan datanya.\n"
    "- Data PRIBADI yang tak boleh dipublikkan -> sarankan tombol Unggah / menu "
    "Penyimpanan (maks 256 MB/file), bukan menyuruh mempublikkan data.\n"
    "- Simpan dataset ke /persist (mis. /persist/data/) + lewati unduh bila file sudah "
    "ada, agar tak mengunduh ulang tiap sesi.\n\n"
    "PLAYBOOK HTTP 403 / 401 SAAT MENGUNDUH DATASET (jangan salah diagnosis):\n"
    "- 403 saat `requests.get(...)` ke situs dataset (Mendeley Data, beberapa portal "
    "jurnal/pemerintah) BUKAN berarti link mati, bukan pula perlu login. Situs itu "
    "memfilter bot lewat sidik jari TLS, dan urllib3 2.x yang dipakai `requests` di "
    "sini kena filter tsb. Menambah header User-Agent TIDAK menolong.\n"
    "- SOLUSI 1 (paling andal, tanpa instal apa pun): pakai urllib bawaan Python.\n"
    "  `import urllib.request`\n"
    "  `req = urllib.request.Request(url, headers={\"User-Agent\": \"Mozilla/5.0\"})`\n"
    "  `with urllib.request.urlopen(req, timeout=120) as r, open(tujuan, \"wb\") as f: "
    "shutil.copyfileobj(r, f)`\n"
    "- SOLUSI 2: `!curl -L -A \"Mozilla/5.0\" -o /persist/data/nama.zip \"<url>\"` "
    "(curl & wget tersedia di sini).\n"
    "- JANGAN menyarankan menurunkan versi library, memakai proxy/VPN, atau "
    "mematikan verifikasi SSL (verify=False) — tidak menyelesaikan masalah dan "
    "berbahaya.\n"
    "- Setelah unduh, WAJIB verifikasi: cetak ukuran file dan cek "
    "`zipfile.is_zipfile(path)` untuk ZIP. File ~beberapa KB berisi HTML = gagal.\n\n"
    "PLAYBOOK MEMBACA FILE DATA (dua kesalahan paling sering):\n"
    "- PATH: direktori kerja notebook = /persist, yaitu folder yang ditampilkan menu "
    "Penyimpanan. Jadi pakai path PERSIS seperti terlihat di sana, mis. "
    "\"data/berkas.parquet\" (bentuk absolut \"/persist/data/berkas.parquet\" juga "
    "benar). Bila sesi memuat project (ZIP/folder/GitHub) CWD = /work, maka pakai "
    "bentuk absolut /persist/... untuk file dari Penyimpanan. Bila pengguna hanya "
    "menyebut nama file, bantu cari dulu: "
    "`import glob; glob.glob('/persist/**/nama*', recursive=True)`.\n"
    "- FORMAT: pilih pembaca sesuai EKSTENSI, jangan asal. .parquet -> "
    "pd.read_parquet | .csv/.tsv -> pd.read_csv | .xlsx/.xls -> pd.read_excel | "
    ".json/.jsonl -> pd.read_json(..., lines=True untuk .jsonl) | .npy -> np.load. "
    "JANGAN memakai read_excel untuk .parquet/.csv, dan jangan menambah argumen "
    "sheet_name kecuali filenya memang Excel.\n\n"
    "ATURAN SAAT PERBAIKAN GAGAL (jangan memperburuk keadaan):\n"
    "- `!pip install X` TIDAK otomatis meng-import. Kode tetap butuh `import X`; "
    "'NameError: name X is not defined' setelah pip install = kurang import, "
    "BUKAN gagal instalasi.\n"
    "- Jangan MENGHAPUS argumen fungsi hanya karena muncul error, kecuali pesan "
    "errornya memang menyebut argumen itu (mis. TypeError: unexpected keyword "
    "argument '<nama>'). Menghapus argumen yang benar bisa membuat kode 'berhasil' "
    "tapi hasilnya salah.\n"
    "- Bila perbaikanmu gagal 2x, JANGAN menebak lagi: minta pengguna menjalankan "
    "perintah diagnosis singkat (mis. `ls -lh`, `file <path>`, cetak versi/signature) "
    "lalu simpulkan dari hasil nyata.\n\n"
    "SEBELUM MENGIRIM JAWABAN, periksa ulang kodenya secara diam-diam: SEMUA import "
    "ada (kode harus jalan bila ditempel ke SATU sel kosong)? nama variabel konsisten? "
    "API & argumen benar-benar ada di versi pada INFO SISTEM (jangan mengarang, jangan "
    "pula menghapus argumen yang sah)? path file sesuai platform (/work, /persist, "
    "/opt/ch-models)? Untuk operasi unduh/tulis file, sudahkah kamu menyertakan "
    "verifikasi hasil (cek ukuran/keberadaan file)? Jika ragu antara dua cara, pilih "
    "yang paling sederhana dan paling mungkin langsung jalan. Jangan tampilkan "
    "proses berpikirmu — tampilkan hanya jawaban final yang rapi."
)

# Batas konteks agar payload tetap wajar. Dinaikkan agar OUTPUT/ERROR sel (yang kini
# ikut dikirim) tetap muat -> asisten bisa melihat traceback asli.
_MAX_CONTEXT_CHARS = 20_000
_MAX_CELL_CHARS = 8_000


def model_for_role(role=None) -> str:  # noqa: ANN001
    """Model asisten sesuai peran user (mahasiswa/dosen/admin). Kosong -> fallback global."""
    rv = getattr(role, "value", role)
    pol = policy_svc.get()
    if rv == "dosen":
        m = pol.assistant_model_dosen
    elif rv == "admin":
        m = pol.assistant_model_admin
    elif rv == "mahasiswa":
        m = pol.assistant_model_student
    else:
        m = ""
    return (m or "").strip() or settings.ASSISTANT_MODEL


async def resolve_model(session, user) -> str:  # noqa: ANN001
    """Model efektif utk 1 user: override per-user -> default peran -> fallback global.

    Override per-user disimpan di user_policies.assistant_model (di-set admin via 'Kelola
    Kebijakan' menu Pengguna). Import lazy utk hindari import melingkar.
    """
    try:
        from app.services import user_policy as user_policy_svc

        eff = await user_policy_svc.effective(session, user.id)
        m = (getattr(eff, "assistant_model", "") or "").strip()
        if m:
            return m
    except Exception as exc:  # noqa: BLE001
        logger.warning("resolve_model gagal, pakai default peran: %s", exc)
    return model_for_role(getattr(user, "role", None))


def vision_model() -> str:
    """Model VISION (multimodal) untuk input gambar: policy admin -> fallback config.

    Kosong = fitur gambar tak tersedia (UI menyembunyikan tombol lampirkan gambar).
    """
    pol = policy_svc.get()
    m = (getattr(pol, "assistant_model_vision", "") or "").strip()
    return m or (settings.ASSISTANT_MODEL_VISION or "").strip()


def request_has_images(req: AssistantChatRequest) -> bool:
    """True bila ada pesan user yang menyertakan gambar (memicu model vision)."""
    return any(getattr(m, "images", None) for m in req.messages if m.role == "user")


def status(model: str | None = None) -> dict:
    return {
        "enabled": settings.ASSISTANT_ENABLED,
        "configured": settings.assistant_configured,
        "model": (model or "").strip() or settings.ASSISTANT_MODEL,
        "provider": settings.ASSISTANT_PROVIDER_LABEL,
        "vision_model": vision_model(),
    }


def _valid_images(images: list[str] | None) -> list[str]:
    """Saring gambar: hanya data URL gambar yang wajar (jenis & ukuran), batasi jumlah."""
    out: list[str] = []
    for im in images or []:
        s = (im or "").strip()
        if s.startswith("data:image/") and len(s) <= settings.ASSISTANT_MAX_IMAGE_CHARS:
            out.append(s)
        if len(out) >= settings.ASSISTANT_MAX_IMAGES:
            break
    return out


def _build_messages(
    req: AssistantChatRequest, system_extra: str = "", system_override: str | None = None
) -> list[dict]:
    """Susun pesan OpenAI: system prompt (+INFO SISTEM) + riwayat, dengan konteks
    notebook DISISIPKAN ke pesan USER terakhir (bukan system terpisah).

    system_override: ganti TOTAL system prompt (dipakai bot lain, mis. Asisten
    Panduan halaman Bantuan) — SYSTEM_PROMPT coding & system_extra diabaikan.

    Pesan yang berisi GAMBAR memakai `content` berbentuk array (teks + image_url data
    URL) sesuai format multimodal OpenAI/Ollama; pesan teks biasa tetap string.
    """
    if system_override is not None:
        system = system_override
    else:
        system = SYSTEM_PROMPT + ("\n\n" + system_extra if system_extra else "")
    msgs: list[dict] = [{"role": "system", "content": system}]

    # Kumpulkan turn (teks + gambar). Sertakan turn user yang HANYA berisi gambar.
    convo: list[dict] = []
    for m in req.messages:
        if m.role not in ("user", "assistant"):
            continue
        text = (m.content or "").strip()
        imgs = _valid_images(getattr(m, "images", None)) if m.role == "user" else []
        if not text and not imgs:
            continue
        convo.append({"role": m.role, "text": text, "images": imgs})

    context_parts: list[str] = []
    if req.notebook_context and req.notebook_context.strip():
        ctx = req.notebook_context.strip()[-_MAX_CONTEXT_CHARS:]
        context_parts.append(
            "Berikut ISI NOTEBOOK saya saat ini (tiap sel sudah diberi nomor). "
            "Pakai ini untuk menjawab — JANGAN mengarang isi sel yang tidak ada:\n\n"
            + ctx
        )
    if req.cell_code and req.cell_code.strip():
        cell = req.cell_code.strip()[:_MAX_CELL_CHARS]
        context_parts.append(
            "Sel yang sedang saya fokuskan:\n```python\n" + cell + "\n```"
        )

    if context_parts:
        block = "\n\n".join(context_parts)
        # Sisipkan konteks ke pesan USER TERAKHIR; bila belum ada, jadikan turn user baru.
        for i in range(len(convo) - 1, -1, -1):
            if convo[i]["role"] == "user":
                prev = convo[i]["text"]
                convo[i]["text"] = block + "\n\n---\n\n" + prev if prev else block
                break
        else:
            convo.append({"role": "user", "text": block, "images": []})

    # Materialisasi ke format OpenAI: string biasa, atau array (teks + gambar).
    for turn in convo:
        if turn["images"]:
            parts: list[dict] = []
            if turn["text"]:
                parts.append({"type": "text", "text": turn["text"]})
            for img in turn["images"]:
                parts.append({"type": "image_url", "image_url": {"url": img}})
            msgs.append({"role": turn["role"], "content": parts})
        else:
            msgs.append({"role": turn["role"], "content": turn["text"]})
    return msgs


async def _stream_fallback(req: AssistantChatRequest) -> AsyncIterator[str]:
    """Tanpa kredensial: jelaskan cara mengaktifkan, plus echo ringkas."""
    last = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    ).strip()
    text = (
        "Asisten AI belum dikonfigurasi.\n\n"
        "Untuk mengaktifkannya, isi `ASSISTANT_API_KEY` di `backend/.env` "
        "(mis. GitHub token dengan scope `models:read`), lalu restart layanan. "
        "Model & provider bisa diatur lewat `ASSISTANT_MODEL` dan `ASSISTANT_API_BASE`.\n\n"
    )
    if last:
        text += f"Pesanmu tadi: _{last[:300]}_"
    # Stream per-kata supaya UI terasa hidup.
    for i, word in enumerate(text.split(" ")):
        yield (word if i == 0 else " " + word)


async def _stream_provider(
    req: AssistantChatRequest, model: str, system_override: str | None = None
) -> AsyncIterator[str]:
    """Stream dari provider OpenAI-compatible (SSE chat completions)."""
    # Pengetahuan sistem NYATA (library terpasang per versi Python, GPU, aturan
    # platform) -> asisten merekomendasikan yang benar-benar ada. Best-effort.
    # Dilewati bila system_override (bot panduan tak butuh info library).
    sys_extra = ""
    if system_override is None:
        try:
            sys_extra = await syscontext.system_context(req.python_version)
        except Exception as exc:  # noqa: BLE001
            logger.debug("syscontext gagal: %s", exc)
    payload = {
        "model": model,
        "messages": _build_messages(req, sys_extra, system_override),
        "stream": True,
        "temperature": settings.ASSISTANT_TEMPERATURE,
    }
    # Batas token keluaran. <= 0 -> TANPA batas: model berhenti secara ALAMI (dibatasi
    # jendela konteks num_ctx di sisi server). Field di-OMIT (bukan -1) agar tetap
    # kompatibel dgn provider cloud OpenAI. Streaming -> timeout tak terpicu selama
    # token terus mengalir (read-timeout = jeda antar-chunk, bukan total durasi).
    if settings.ASSISTANT_MAX_TOKENS > 0:
        payload["max_tokens"] = settings.ASSISTANT_MAX_TOKENS
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    # Provider lokal (Ollama) tak butuh kunci -> kirim Authorization HANYA bila ada.
    key = settings.ASSISTANT_API_KEY.strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = settings.assistant_chat_url
    timeout = httpx.Timeout(settings.ASSISTANT_TIMEOUT_SECONDS, connect=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:500]
                    logger.warning(
                        "Asisten provider balas %s: %s", resp.status_code, body
                    )
                    yield (
                        f"⚠️ Provider AI menolak permintaan (HTTP {resp.status_code}). "
                        "Periksa ASSISTANT_API_KEY / ASSISTANT_MODEL / ASSISTANT_API_BASE."
                    )
                    return
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"].get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
    except httpx.TimeoutException:
        yield "⚠️ Permintaan ke provider AI melebihi batas waktu. Coba lagi."
    except httpx.HTTPError as exc:  # noqa: BLE001
        logger.warning("Asisten gagal menghubungi provider: %s", exc)
        yield "⚠️ Gagal menghubungi provider AI. Periksa koneksi/konfigurasi."


_vision_sema: asyncio.Semaphore | None = None


def _vision_semaphore() -> asyncio.Semaphore:
    """Semaphore pembatas permintaan VISION bersamaan (lazy; aman dibuat di dalam loop)."""
    global _vision_sema
    if _vision_sema is None:
        _vision_sema = asyncio.Semaphore(max(1, settings.ASSISTANT_VISION_CONCURRENCY))
    return _vision_sema


async def stream_chat(
    req: AssistantChatRequest,
    model: str | None = None,
    system_override: str | None = None,
) -> AsyncIterator[str]:
    """Hasilkan potongan teks jawaban (delta) untuk di-stream ke klien.

    Permintaan VISION (berisi gambar) DISERIALISASI lewat semaphore agar model vision
    besar (~30GB VRAM) tidak menumpuk di GPU saat banyak user mengunggah gambar sekaligus.
    Permintaan teks biasa (model kecil) tidak dibatasi.
    """
    if not settings.assistant_configured:
        async for chunk in _stream_fallback(req):
            yield chunk
        return

    m = (model or "").strip() or settings.ASSISTANT_MODEL
    if request_has_images(req):
        sema = _vision_semaphore()
        if sema.locked():
            yield "⏳ Model gambar sedang dipakai — menunggu giliran sebentar…\n\n"
        async with sema:
            async for chunk in _stream_provider(req, m, system_override):
                yield chunk
    else:
        async for chunk in _stream_provider(req, m, system_override):
            yield chunk


async def list_models() -> list[dict]:
    """Daftar model provider LOKAL (Ollama) + ukuran disk (GB) untuk pemilih model admin.

    Kosong bila provider bukan Ollama lokal (mis. cloud) atau Ollama tak terjangkau.
    """
    if not settings.assistant_is_local:
        return []
    base = settings.ASSISTANT_API_BASE.strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    url = f"{base}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal ambil daftar model Ollama: %s", exc)
        return []
    out: list[dict] = []
    for m in data.get("models", []):
        d = m.get("details", {}) or {}
        out.append({
            "name": m.get("name", ""),
            "size_gb": round(m.get("size", 0) / 1e9, 1),
            "parameter_size": d.get("parameter_size", ""),
            "quantization": d.get("quantization_level", ""),
        })
    out.sort(key=lambda x: x["size_gb"])
    return out
