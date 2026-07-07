# Performance Report — UNISMUH ComputeHub

Tanggal: 2026-07-07 · Alat: Playwright (Navigation Timing API + pengukuran latensi request).
Lingkungan: server bersama (headless), Chromium (Playwright bundle), workers=2, slowMo=200ms (rekaman).
Basis data: **PostgreSQL lokal** (server kampus).

> Catatan: pengujian **beban berat (20/50 user)** SENGAJA tidak dilakukan karena ini server
> produksi bersama — risiko DoS bagi pengguna nyata. Diganti **sampling konkurensi ringan (5 paralel)**.

## 1. Waktu muat halaman (Navigation Timing)

| Rute | Wall (goto→ready) | DOMContentLoaded | Load event | Transfer dok |
|------|------------------:|-----------------:|-----------:|-------------:|
| `/` (Dashboard) | 1141 ms | 59 ms | 59 ms | 1.0 KB |
| `/jobs` | 1159 ms | 73 ms | 73 ms | 1.0 KB |
| `/storage` | 1134 ms | 65 ms | 65 ms | 1.0 KB |
| `/report` | 1184 ms | 109 ms | 109 ms | 1.0 KB |
| `/monitor` | 1117 ms | 58 ms | 58 ms | 1.0 KB |

**Interpretasi.** Shell SPA sangat ringan: dokumen HTML hanya ~1 KB dan `DOMContentLoaded`
~58–109 ms (aset di-hash & ter-cache). Angka "wall" ~1.1–1.2s mencakup `waitAppReady` (jeda
buatan di harness) + fetch `/auth/me`. Rendering & paint cepat; tidak ada bottleneck front-end.

## 2. Latensi API

| Endpoint | Latensi | Catatan |
|----------|--------:|---------|
| `GET /health` | 16 ms | Tanpa DB. |
| `GET /auth/me` | **70 ms** | Query DB lokal — turun dari ~1.1s (era Supabase remote). |
| `GET /admin/report` | **30 ms** | Agregasi multi-query — turun dari ~2.1s (era Supabase). |
| `GET /admin/report/disk` | 16 ms | Di-cache server-side. |

**Interpretasi.** Setelah **migrasi DB ke PostgreSQL lokal**, latensi endpoint ber-DB anjlok:
`/auth/me` 1.1s→**70ms**, `/admin/report` 2.1s→**30ms** (≈30–70× lebih cepat). Latensi kini
didominasi komputasi lokal ringan, bukan round-trip jaringan.

## 3. Konkurensi (sampling ringan)

| Skenario | Hasil |
|----------|-------|
| 5× `GET /health` paralel | total **20 ms**, semua 200 OK |

Tidak ada degradasi pada konkurensi rendah. Pengujian beban tinggi tidak dijalankan (lihat catatan).

## 4. Rekomendasi performa

1. ✅ **TERATASI** — round-trip DB dipangkas dengan **migrasi ke PostgreSQL lokal**
   (`/auth/me` 1.1s→70ms, `/admin/report` 2.1s→30ms; ≈30–70× lebih cepat).
2. Pertimbangkan menaikkan `pool_size`/`max_overflow` asyncpg untuk konkurensi pengguna lebih tinggi.
3. Front-end sudah optimal (code-split per halaman, aset ter-cache) — tak perlu tindakan.
4. Untuk audit beban sebenarnya, jalankan load test di **lingkungan staging** (bukan produksi bersama).

## Lampiran
Metrik mentah: `reports/perf/*.json`. Rekaman per-test: `reports/html-report/` (video + trace).
