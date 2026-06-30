# Performance Report — UNISMUH ComputeHub

Tanggal: 2026-06-30 · Alat: Playwright (Navigation Timing API + pengukuran latensi request).
Lingkungan: server bersama (headless), Chromium 149, workers=2, slowMo=200ms (rekaman).

> Catatan: pengujian **beban berat (20/50 user)** SENGAJA tidak dilakukan karena ini server
> produksi bersama — risiko DoS bagi pengguna nyata. Diganti **sampling konkurensi ringan (5 paralel)**.

## 1. Waktu muat halaman (Navigation Timing)

| Rute | Wall (goto→ready) | DOMContentLoaded | Load event | Transfer dok |
|------|------------------:|-----------------:|-----------:|-------------:|
| `/` (Dashboard) | 1137 ms | 55 ms | 57 ms | 1.0 KB |
| `/jobs` | 1099 ms | 42 ms | 42 ms | 1.0 KB |
| `/storage` | 1108 ms | 60 ms | 60 ms | 1.0 KB |
| `/report` | 1111 ms | 60 ms | 60 ms | 1.0 KB |
| `/monitor` | 1091 ms | 51 ms | 52 ms | 1.0 KB |

**Interpretasi.** Shell SPA sangat ringan: dokumen HTML hanya ~1 KB dan `DOMContentLoaded`
~40–60 ms (aset di-hash & ter-cache). Angka "wall" ~1.1s mencakup `waitAppReady` (800ms buatan)
+ fetch `/auth/me`. Rendering & paint cepat; tidak ada bottleneck di sisi front-end.

## 2. Latensi API

| Endpoint | Latensi | Catatan |
|----------|--------:|---------|
| `GET /health` | 16 ms | Sangat cepat (tanpa DB). |
| `GET /auth/me` | ~1109 ms | Round-trip ke Postgres **Supabase remote**. |
| `GET /admin/report` | ~2100 ms | Agregasi + beberapa query DB remote. |
| `GET /admin/report/disk` | ~1107 ms | Di-cache server-side; nilai cache → cepat-stabil. |

**Interpretasi.** Latensi didominasi **round-trip database remote** (Supabase), bukan CPU server.
`/health` (tanpa DB) 16 ms membuktikan app & jaringan lokal sehat. `/admin/report` ~2.1s karena
beberapa query agregasi berurutan ke DB jauh.

## 3. Konkurensi (sampling ringan)

| Skenario | Hasil |
|----------|-------|
| 5× `GET /health` paralel | total **21 ms**, semua 200 OK |

Tidak ada degradasi pada konkurensi rendah. Pengujian beban tinggi tidak dijalankan (lihat catatan).

## 4. Rekomendasi performa

1. **Kurangi round-trip DB** pada endpoint berat (`/auth/me`, `/admin/report`): connection pooling
   yang hangat, gabungkan query, atau cache ringan bert-TTL (pola yang sudah dipakai `/report/disk`).
2. Pertimbangkan menaikkan `pool_size`/`max_overflow` asyncpg untuk konkurensi pengguna lebih tinggi.
3. Front-end sudah optimal (code-split per halaman, aset ter-cache) — tak perlu tindakan.
4. Untuk audit beban sebenarnya, jalankan load test di **lingkungan staging** (bukan produksi bersama).

## Lampiran
Metrik mentah: `reports/perf/*.json`. Rekaman per-test: `reports/html-report/` (video + trace).
