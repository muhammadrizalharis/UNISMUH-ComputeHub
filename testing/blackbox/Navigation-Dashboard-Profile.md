# Black-box — Navigasi, Dashboard & Profil

Pre-condition: sesi **admin** (token diinjeksi via storageState).

## Navigasi & Rute (`e2e/navigation.spec.ts`)

| Test ID | Objective | Test Steps | Expected | Actual | Status |
|---------|-----------|-----------|----------|--------|--------|
| TC-NAV (×13) | Tiap rute terproteksi memuat | Buka tiap rute (`/`,`/monitor`,`/jobs`,`/storage`,`/submit/*`,`/users`,`/report`,`/alerts`,`/admin`,`/profile`) | Memuat, tanpa error fatal, URL benar, tanpa JS pageerror | Sesuai | ✅ PASS |
| TC-NAV-SIDEBAR | Klik tiap menu sidebar | Klik Dashboard, Monitor, Daftar Job, Penyimpanan, Laporan, Peringatan, Pengguna, Pengaturan | Tiap klik berpindah ke URL yang benar | Sesuai | ✅ PASS |
| TC-NAV-HISTORY | Refresh/Back/Forward | `/jobs`→`/storage`, reload, back, forward | State URL konsisten (storage→jobs→storage) | Sesuai | ✅ PASS |

Screenshot: `screenshots/nav/**`.

## Dashboard (`e2e/dashboard.spec.ts`)

| Test ID | Objective | Expected | Actual | Status |
|---------|-----------|----------|--------|--------|
| TC-DASH-01 | Kartu ringkasan tampil | ≥1 kartu/elemen ringkasan, tanpa JS error | Sesuai | ✅ PASS |
| TC-DASH-02 | Konten tidak blank | body berisi teks bermakna | Sesuai | ✅ PASS |

## Profil (`e2e/profile.spec.ts`)

| Test ID | Objective | Expected | Actual | Status |
|---------|-----------|----------|--------|--------|
| TC-PROF-01 | Identitas akun tampil | Email akun admin muncul di halaman profil | Sesuai | ✅ PASS |
