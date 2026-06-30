# Bug Report — UNISMUH ComputeHub

Tanggal uji: 2026-06-30 · Tester: QA Automation (Playwright) · Build: `main` @ commit terbaru
Lingkungan: server produksi bersama (headless), `http://127.0.0.1:8088`, Chromium 149.

> Ringkasan: dari 78 kasus uji, **0 kegagalan fungsional**. Ditemukan **1 isu UX
> minor** (BUG-001) dan beberapa **observasi** (bukan cacat). Tidak ada error fatal
> JS, tidak ada kebocoran data, tidak ada celah otorisasi yang ditemukan.

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

**Status uji otomatis:** TC-USR-03 kini LULUS (viewport dilebarkan + retry buka menu). Isu UX tetap valid pada layar sempit.

---

## Observasi (bukan cacat fungsional)

| ID | Tipe | Catatan | Tindak lanjut |
|----|------|---------|----------------|
| OBS-1 | Performa | Endpoint ber-DB lambat: `GET /auth/me` ≈ 1.1s, `GET /admin/report` ≈ 2.1s (round-trip Supabase remote). `/health` 16ms. | Lihat performance-report.md; pertimbangkan caching/pooling. |
| OBS-2 | Desain | Halaman `/jobs` hanya punya filter status (dropdown) + checkbox "Hanya job saya", **tidak** ada pencarian teks bebas. | By design; TC-JOB-02 di-skip secara sah. |
| OBS-3 | Lingkungan | Mode **headed** tidak tersedia (server headless, `DISPLAY` kosong). Visual diverifikasi via video+trace+screenshot. | Tidak ada. |
| OBS-4 | Keamanan | Token disimpan di `localStorage` (bukan cookie HttpOnly). Wajar untuk SPA + bearer; dimitigasi CSP + escaping React. | Pertimbangkan refresh-cookie HttpOnly bila ingin perkuat. |

---

## Tidak ditemukan

XSS tereksekusi · SQL injection sukses · directory traversal · privilege escalation ·
broken authentication/authorization · kebocoran stack trace/path internal · error boundary/crash ·
CORS memantulkan origin jahat · token di URL/cookie.
