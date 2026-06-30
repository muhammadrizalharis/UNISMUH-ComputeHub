# Black-box — Login & Autentikasi (`auth/public.spec.ts`)

Pre-condition umum: aplikasi hidup di `http://127.0.0.1:8088`, tanpa sesi (storageState kosong).

| Test ID | Objective | Test Steps | Expected | Actual | Status | Screenshot |
|---------|-----------|-----------|----------|--------|--------|-----------|
| TC-AUTH-01 | Landing tampil | Buka `/welcome` | Halaman memuat, memuat teks "ComputeHub", tanpa JS pageerror | Sesuai | ✅ PASS | `screenshots/login/*landing*` |
| TC-AUTH-02 | Form login lengkap | Buka `/login` | Field email, password, tombol submit terlihat | Sesuai | ✅ PASS | `*login-form*` |
| TC-AUTH-03 | Toggle password | Isi password, klik ikon mata | `type` berubah `password`→`text` | Sesuai | ✅ PASS | `*password-shown*` |
| TC-AUTH-04 | Validasi form kosong | Submit form kosong | Tetap di `/login`; email `:invalid` (required) | Sesuai | ✅ PASS | `*empty-validation*` |
| TC-AUTH-05 | Login salah | Login email/pass salah (1×) | Pesan error merah tampil; tetap `/login` | Sesuai | ✅ PASS | `*after-invalid-login*` |
| TC-AUTH-06 | Proteksi rute | Buka `/` tanpa login | Diarahkan ke `/welcome` atau `/login` | Sesuai | ✅ PASS | `*protected-redirect*` |
| TC-AUTH-07 | 404 | Buka rute ngawur | Halaman NotFound (404/"tidak ditemukan") | Sesuai | ✅ PASS | `*not-found*` |

Catatan: percobaan login gagal dibatasi (≤1) agar tidak memicu rate-limiter (di balik tunnel
banyak user bisa berbagi IP). **Logout** & **single-session** diverifikasi lewat SEC-09 + penyiapan token.
