# Rencana: Tampilkan kemampuan (capabilities) tiap model Ollama di pemilih model

Status: **SELESAI / terimplementasi (Opsi A)** — lihat ringkasan di bawah.
Dibuat atas permintaan admin (Muhammad Rizal Haris).

> Implementasi: backend `list_models()` kini meneruskan `capabilities` + `context_length`
> dari `/api/tags` (terverifikasi dgn 14 model nyata). Frontend `ModelSelect` menampilkan
> kemampuan sebagai ikon ringkas di label opsi (👁 vision · 🔊 audio · 🧰 tools · 🧠 thinking
> · embed), ditambah legenda kecil di atas pemilih model. Model tanpa metadata tetap tampil
> normal (field default `[]`).

## Tujuan

Pada dropdown pemilih model (mis. pengaturan model asisten / gateway Ollama), saat ini
label hanya menampilkan **nama — ukuran · parameter**, contoh:

```
qwen3.6:latest — 23.9 GB · 36.0B
```

Admin ingin juga melihat **kemampuan** tiap model langsung di daftar, supaya tahu mana
yang mendukung `vision`, `tools`, `thinking`, `audio`, `embedding`, dsb. tanpa coba-coba.

## Data sudah tersedia dari Ollama, tapi belum diteruskan backend

`GET /api/tags` di server Ollama ini **sudah** mengembalikan `capabilities` per model,
contoh (dari dump admin):

```json
{
  "name": "gemma4:latest",
  "size": 9608350718,
  "details": { "parameter_size": "8.0B", "quantization_level": "Q4_K_M",
               "context_length": 131072 },
  "capabilities": ["completion", "vision", "audio", "tools", "thinking"]
}
```

Tetapi backend membuang field itu. Di
`backend/app/services/assistant.py:478-484`, dict yang dibentuk hanya berisi
`name`, `size_gb`, `parameter_size`, `quantization` — **`capabilities` tidak diambil**
(dan `capabilities` ada di level atas `m`, bukan di `details`).

## Perubahan yang diusulkan

### 1. Backend — teruskan `capabilities` (+ opsional `context_length`)
`backend/app/services/assistant.py` (loop di sekitar baris 479-484):

```python
out.append({
    "name": m.get("name", ""),
    "size_gb": round(m.get("size", 0) / 1e9, 1),
    "parameter_size": d.get("parameter_size", ""),
    "quantization": d.get("quantization_level", ""),
    "capabilities": m.get("capabilities", []) or [],          # <-- tambah
    "context_length": d.get("context_length"),                # <-- opsional
})
```

Endpoint `GET /assistant/models` (`backend/app/api/routers/assistant.py:45`) otomatis
ikut mengirim field baru (ia hanya meneruskan list dict).

### 2. Tipe frontend
`frontend/src/lib/types.ts:238-243` — tambah field opsional:

```ts
export interface AssistantModelInfo {
  name: string
  size_gb: number
  parameter_size: string
  quantization: string
  capabilities?: string[]       // <-- tambah
  context_length?: number       // <-- opsional
}
```

### 3. UI — menampilkan kemampuan

Komponen saat ini (`frontend/src/pages/Admin.tsx:253-281`, `ModelSelect`) memakai
`<select>`/`<option>` **HTML native**. Keterbatasan penting:
**`<option>` native hanya menerima teks polos — tidak bisa badge/warna/ikon HTML.**

Ada dua pendekatan:

**Opsi A — tag teks ringkas di dalam opsi (AMAN, minim perubahan).**
Tambahkan singkatan kemampuan pada label opsi, mis.:

```
qwen3.6:latest — 23.9 GB · 36.0B · 👁 tools 🧠
gpt-oss:latest — 13.8 GB · 20.9B · tools 🧠
bge-m3:latest — 1.2 GB · 566.70M · embed
```

Pemetaan singkat: `vision`→👁, `audio`→🔊, `tools`→🧰, `thinking`→🧠,
`embedding`→embed. `completion` boleh disembunyikan (hampir semua punya).
Perubahan hanya 1 baris di `Admin.tsx:273-275`.

**Opsi B — dropdown kustom dengan badge berwarna (lebih kaya, lebih berat).**
Ganti `<select>` native dengan komponen daftar kustom (div + tombol) sehingga tiap
baris model bisa menampilkan chip berwarna per kemampuan (hijau=tools, ungu=vision,
dst.) + tooltip context length. Konsekuensi: perlu menangani sendiri keyboard
navigation, aksesibilitas, dan penutupan saat klik luar.

**Rekomendasi:** mulai dengan **Opsi A** (cukup memenuhi kebutuhan, risiko kecil, tidak
menyentuh perilaku form). Naik ke Opsi B hanya bila admin ingin tampilan badge penuh.

## Kriteria selesai
- Dropdown model menampilkan kemampuan tiap model (vision/tools/thinking/audio/embedding).
- Tidak ada model yang hilang / berubah urutan (tetap urut berdasarkan ukuran).
- Model tanpa metadata kemampuan tetap tampil normal (tanpa tag), tidak error.

## Catatan
- Model cloud (`glm-4.6:cloud`) juga punya `capabilities` → ikut tertampil.
- Jika suatu saat server Ollama lama tidak mengirim `capabilities`, field kosong aman
  (default `[]`), UI cukup tidak menampilkan tag.
