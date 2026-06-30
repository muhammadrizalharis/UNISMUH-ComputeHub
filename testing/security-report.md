# Security Report — UNISMUH ComputeHub

Tanggal: 2026-06-30 · Metode: probe **non-destruktif** dari perspektif pengguna (black-box) +
inspeksi header/response. Tidak ada eksploitasi nyata atau perusakan data.

> Catatan etika & keselamatan: server ini **produksi bersama** dengan user nyata. Maka:
> tidak ada load/DoS, tidak ada penghapusan data orang lain, dan **rate-limit login tidak
> di-exhaust** (di balik tunnel banyak user dapat berbagi IP → bisa mengunci login mereka).

## Ringkasan hasil

| Kode | Area | Uji | Hasil |
|------|------|-----|-------|
| SEC-01 | HTTP Security Headers / Clickjacking | `X-Frame-Options` & `Content-Security-Policy` ada pada respons | ✅ LULUS |
| SEC-02 | Missing Authentication | `/auth/me`, `/admin/report`, `/admin/report/disk` tanpa token → 401 | ✅ LULUS |
| SEC-03 | Broken Authorization / Privilege Escalation | token **mahasiswa** ke endpoint admin → 401/403 | ✅ LULUS |
| SEC-04 | Directory Traversal | `workspace/file?path=../../../../etc/passwd` → ditolak, tidak bocor | ✅ LULUS |
| SEC-05 | SQL Injection | payload `' OR '1'='1` ke login → 400/401/422 (tidak sukses, tidak 500) | ✅ LULUS |
| SEC-06 | CORS | `Origin: evil.example.com` tidak dipantulkan di `Access-Control-Allow-Origin` | ✅ LULUS |
| SEC-07 | Information Disclosure | 404 tidak menampilkan traceback Python / path internal | ✅ LULUS |
| SEC-08 | XSS (reflected/stored di kolom cari) | `<img src=x onerror=alert(1)>` tidak mengeksekusi dialog | ✅ LULUS |
| SEC-09 | Token Leakage / Cookie Security | JWT tidak ada di cookie maupun URL | ✅ LULUS |
| SEC-RL | Rate Limiting (anti brute-force) | ada (`SlidingWindowRateLimiter`, 10 gagal/5 mnt → blok 10 mnt) | ✅ ADA (exhaust di-skip demi keamanan user) |

## Rincian & temuan pendukung (white-box ringan)

- **Header keamanan** dipasang global di `backend/app/main.py` (middleware): `X-Frame-Options: DENY`,
  `Content-Security-Policy`, dll. → mitigasi **clickjacking** & injeksi sumber.
- **Otorisasi** ditegakkan via dependency `require_admin`; uji menunjukkan akun mahasiswa
  konsisten ditolak (401/403) pada semua endpoint admin yang diuji. Tidak ada **IDOR/privilege escalation**.
- **Directory traversal** dicegah di `workspace._safe` (basename + anti `..`); uji membaca
  `/etc/passwd` gagal & tidak ada konten sensitif yang bocor.
- **CSRF**: API memakai **Bearer token** (bukan cookie sesi), sehingga permukaan CSRF minim
  (tidak ada auto-credential). CORS dibatasi (`settings.cors_origins`).
- **Session Management**: single-session via klaim `sid` = `users.session_token`; login di
  perangkat lain menggugurkan sesi lama (diamati saat menyiapkan token uji).
- **Token storage**: `localStorage` (`unismuh_token`). Bukan cacat, tapi bila ingin diperkuat,
  pertimbangkan refresh token sebagai cookie `HttpOnly`+`SameSite`.

## Rekomendasi keamanan

1. (Opsional) Tambahkan `Strict-Transport-Security` (HSTS) di edge/tunnel untuk paksa HTTPS.
2. (Opsional) Pertimbangkan refresh-cookie `HttpOnly` agar token utama tak terekspos JS (anti-XSS-exfil).
3. Pertahankan rate-limit; bila di belakang tunnel, gunakan header `X-Forwarded-For` tepercaya agar
   kunci rate-limit = IP asli (bukan IP tunnel) supaya tidak salah-blokir antar user.
4. Lanjutkan rotasi `SECRET_KEY` berkala (sudah dilakukan) + rotasi kredensial eksternal.

## Cakupan yang TIDAK dilakukan (disengaja, alasan keselamatan)

- Exhaust rate-limit login (risiko mengunci user nyata di balik tunnel berbagi-IP).
- Pengujian beban 20/50 pengguna serentak (risiko DoS user nyata) — diganti sampling ringan.
- Fuzzing destruktif / penghapusan data milik user lain.
