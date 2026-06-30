# Black-box — Pengguna, Laporan, Monitor & Peringatan

Pre-condition: sesi **admin**.

## Manajemen Pengguna (`e2e/users.spec.ts`)

| Test ID | Objective | Test Steps | Expected | Actual | Status |
|---------|-----------|-----------|----------|--------|--------|
| TC-USR-01 | Tabel pengguna | Buka `/users`, tunggu tabel | Tabel tampil (>0) | Sesuai | ✅ PASS |
| TC-USR-02 | Pencarian | Ketik query tanpa kecocokan | Baris menyusut/tetap, tanpa error | Sesuai | ✅ PASS |
| TC-USR-03 | Modal Kelola Kebijakan | Buka menu "Aksi" → "Kelola Kebijakan" → tutup tanpa simpan | Modal kebijakan terbuka, lalu tertutup | Sesuai (lihat BUG-001) | ✅ PASS* (retry; viewport dilebarkan) |
| TC-USR-04 | Form Tambah User | Klik "Tambah User" → form muncul → tutup | Form tampil; ditutup tanpa membuat user | Sesuai | ✅ PASS |

> **Tidak ada perubahan disimpan** pada user nyata (modal & form dibuka lalu dibatalkan).
> BUG-001: dropdown "Aksi" menutup sendiri saat tabel overflow horizontal (lihat bug-report.md).

## Laporan (`e2e/report.spec.ts`)

| Test ID | Objective | Expected | Actual | Status |
|---------|-----------|----------|--------|--------|
| TC-REP-01 | Seksi utama | Memuat "Informasi Sistem" & "Disk" | Sesuai | ✅ PASS |
| TC-REP-02 | Pemakaian Disk per User | Seksi `#disk` tampil (tabel/menghitung) | Sesuai | ✅ PASS |
| TC-REP-03 | Unduh laporan HTML | Klik "Unduh Laporan" → unduhan `laporan*.html` | Sesuai | ✅ PASS |

## Monitor & Peringatan (`e2e/monitor-alerts.spec.ts`)

| Test ID | Objective | Expected | Actual | Status |
|---------|-----------|----------|--------|--------|
| TC-MON-01 | Monitor metrik/chart | Ada canvas/svg atau metrik teks (CPU/RAM/GPU) | Sesuai | ✅ PASS |
| TC-ALERT-01 | Halaman peringatan | Memuat teks ambang/peringatan | Sesuai | ✅ PASS |
| TC-ALERT-02 | Input konfigurasi ambang | ≥1 input konfigurasi tampil | Sesuai | ✅ PASS |

Konfigurasi alert **tidak disimpan** (read-only).
