# Bug Report — UNISMUH ComputeHub

Tanggal uji: 2026-07-08 · Tester: QA Automation (Playwright) · Build: `main` @ commit terbaru
Lingkungan: server produksi bersama (headless), `http://127.0.0.1:8088`, Chromium (Playwright bundle).

> Ringkasan: dari **84 kasus uji**, **0 kegagalan fungsional** (83 lulus · 1 skip sah · 0 flaky).
> BUG-001 & BUG-002 (UX minor) sudah **diperbaiki**; sisanya **observasi** (bukan cacat). Tidak ada
> error fatal JS, tidak ada kebocoran data, tidak ada celah otorisasi yang ditemukan.

---

## BUG-001 — Dropdown "Aksi" pada tabel Pengguna menutup sendiri saat tabel overflow horizontal

| Field | Nilai |
|------|------|
| **Judul** | Menu "Aksi" (Kelola Kebijakan/Reset/Hapus) langsung tertutup ketika tabel Pengguna meng-overflow horizontal |
| **Severity** | Low–Medium (UX; fungsi tetap dapat diakses pada layar lebar) |
| **Priority** | Medium |
| **Komponen** | `frontend/src/pages/Users.tsx` → `RowActions` |
| **Halaman** | `/users` |

**Deskripsi.** `RowActions` membuka menu via `createPortal` dengan posisi `fixed`, dan
memasang listener `window.addEventListener('scroll', close, true)` (menutup menu pada
setiap scroll). Saat tabel lebih lebar dari viewport (`overflow-x-auto`), mengklik tombol
"Aksi" di tepi kanan membuat browser melakukan **focus-scroll** pada kontainer tabel →
memicu event `scroll` → menu **langsung tertutup** sebelum sempat dipakai.

**Langkah reproduksi.**
1. Login sebagai admin, buka `/users`.
2. Perkecil lebar jendela hingga tabel memunculkan scrollbar horizontal (± < 1600px area konten).
3. Klik tombol **Aksi** pada salah satu baris.
4. **Aktual:** menu berkedip lalu tertutup seketika; item "Kelola Kebijakan" tak bisa diklik.
5. **Ekspektasi:** menu tetap terbuka sampai pengguna memilih item atau klik di luar.

**Bukti.** `screenshots/users/*action-menu*.png` (menu tidak tampil setelah klik pada viewport sempit);
pada viewport lebar (1920px) menu terbuka normal (test TC-USR-03 lulus setelah viewport dilebarkan).

**Rekomendasi.**
- Jangan menutup menu pada scroll yang dipicu fokus; atau abaikan event scroll dalam ±300ms pertama setelah buka.
- Lebih baik: pakai pustaka positioning (anchored popover) yang mengikuti tombol alih-alih `fixed` + close-on-scroll.
- Alternatif cepat: bungkus kolom aksi agar selalu terlihat (sticky) sehingga tak perlu focus-scroll.

**✅ STATUS: DIPERBAIKI.** Listener `scroll`/`resize` kini baru "aktif" 350ms setelah menu
terbuka (mengabaikan focus-scroll saat klik). Diverifikasi: TC-USR-03 LULUS **3/3** pada
viewport 1440 (tempat bug semula muncul), tanpa flaky.

---

## BUG-002 — Header Penyimpanan overflow horizontal di mobile setelah tombol "Unduh semua"

| Field | Nilai |
|------|------|
| **Judul** | Baris tombol header `/storage` (chip kuota + "Unduh semua" + "Unggah" + "Segarkan") melebihi lebar layar mobile |
| **Severity** | Low (kosmetik; muncul scrollbar horizontal di layar sempit) |
| **Priority** | Medium (ditemukan & ditutup di sesi yang sama) |
| **Komponen** | `frontend/src/pages/Storage.tsx` → header |
| **Halaman** | `/storage` |
| **Ditemukan oleh** | `TC-RESP /storage` (project **mobile**, 412×839) saat menambah fitur unduh folder |

**Deskripsi.** Penambahan tombol **"Unduh semua"** membuat baris aksi header (`flex items-center
gap-3`, tanpa wrap) menjadi lebih lebar dari viewport mobile → **overflow horizontal 64px**
(ambang uji < 40px).

**Langkah reproduksi.**
1. Buka `/storage` pada viewport ± 412px (mobile).
2. **Aktual (sebelum fix):** `scrollWidth − clientWidth = 64px` → scrollbar horizontal.
3. **Ekspektasi:** tanpa overflow horizontal (baris tombol membungkus ke bawah).

**✅ STATUS: DIPERBAIKI.** Baris tombol header diubah menjadi
`flex flex-wrap items-center justify-end gap-2 sm:gap-3` → tombol membungkus di layar sempit.
Diverifikasi: `TC-RESP /storage` **LULUS** pada **mobile 412×839** dan **tablet 820×1180**.

---

## Observasi (bukan cacat fungsional)

| ID | Tipe | Catatan | Tindak lanjut |
|----|------|---------|----------------|
| OBS-1 | Performa | Endpoint ber-DB dulu lambat (era Supabase remote): `/auth/me` ≈ 1.1s, `/admin/report` ≈ 2.1s. | ✅ **TERATASI** — migrasi ke **PostgreSQL lokal**: `/auth/me` **70ms**, `/admin/report` **30ms**, `/health` 16ms. |
| OBS-2 | Desain | Halaman `/jobs` hanya punya filter status (dropdown) + checkbox "Hanya job saya", **tidak** ada pencarian teks bebas. | By design; TC-JOB-02 di-skip secara sah. |
| OBS-3 | Lingkungan | Mode **headed** tidak tersedia (server headless, `DISPLAY` kosong). Visual diverifikasi via video+trace+screenshot. | Tidak ada. |
| OBS-4 | Keamanan | Token disimpan di `localStorage` (bukan cookie HttpOnly). Wajar untuk SPA + bearer; dimitigasi CSP + escaping React. + **HSTS kini dipasang**, rate-limit kini per-IP-asli. | Pertimbangkan refresh-cookie HttpOnly bila ingin perkuat. |
| OBS-5 | Ketahanan | Editor **Monaco dimuat dari CDN jsdelivr** (`script-src … cdn.jsdelivr.net`, `worker-src blob:`). Bila jaringan tersendat, muat editor bisa lambat & sesekali memancarkan `Event` benign (bukan error aplikasi). | Bundel Monaco **same-origin** agar tahan jaringan lambat/offline kampus. |

---

## Tidak ditemukan

XSS tereksekusi · SQL injection sukses · directory traversal · privilege escalation ·
broken authentication/authorization · kebocoran stack trace/path internal · error boundary/crash ·
CORS memantulkan origin jahat · token di URL/cookie.
