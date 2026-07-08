# Black-box — Jobs, Storage & Submit

Pre-condition: sesi **admin**.

## Daftar Job (`e2e/jobs.spec.ts`)

| Test ID | Objective | Test Steps | Expected | Actual | Status |
|---------|-----------|-----------|----------|--------|--------|
| TC-JOB-01 | Tabel/empty-state | Buka `/jobs`, tunggu render | Tabel job muncul (atau empty-state) | Sesuai | ✅ PASS |
| TC-JOB-02 | Pencarian job | Cari kotak pencarian | — | Tidak ada pencarian teks (by design) | ⏭️ SKIP (sah) |
| TC-JOB-03 | Filter status | Pilih opsi pada dropdown status | Daftar ter-filter tanpa error | Sesuai | ✅ PASS |
| TC-JOB-04 | Buka detail job | Klik baris (bila ada) | Navigasi ke `/jobs/:id` | Admin tak punya job sendiri | ⏭️ SKIP (sah) |

Catatan: **eksekusi job nyata tidak dipicu** untuk melindungi GPU/antrian produksi. `/jobs` punya
filter status + checkbox "Hanya job saya" (bukan pencarian teks). Antrian/ETA tampil bila ada job.

## Penyimpanan (`e2e/storage.spec.ts`)

| Test ID | Objective | Test Steps | Expected | Actual | Status |
|---------|-----------|-----------|----------|--------|--------|
| TC-STO-01 | Halaman + kuota | Buka `/storage` | Tampil indikator kuota/penyimpanan, tanpa JS error | Sesuai | ✅ PASS |
| TC-STO-02 | Upload lalu bersih | Upload `QA_TEST_*.txt` via UI → muncul → hapus via API | File tampil; cleanup 200/204/404 | Sesuai | ✅ PASS |
| TC-STO-03 | Tombol unggah | Cek tombol Unggah | Terlihat & dapat diklik | Sesuai | ✅ PASS |
| TC-STO-04 | Unduh SELURUH workspace `.zip` | GET `/interactive/workspace/download-folder?path=` (token admin) | HTTP 200, `content-type: application/zip`, nama `workspace.zip`, magic `PK` | Sesuai | ✅ PASS |
| TC-STO-05 | Unduh FOLDER tertentu `.zip` | Buat file di subfolder → GET download-folder `?path=<folder>` → hapus folder | HTTP 200, nama `<folder>.zip`, `PK`; cleanup 200/204/404 | Sesuai | ✅ PASS |
| TC-STO-06 | UI tombol "Unduh semua" | Buka `/storage`, klik **Unduh semua** | Event unduhan terpicu, berkas berakhiran `.zip` | Sesuai | ✅ PASS |

Catatan: file uji dibuat & dihapus pada `/persist` **milik akun uji sendiri** (terisolasi, reversibel).
Unduh folder mengemas isi folder menjadi `.zip` (folder cache internal `.local`/`.cache` dilewati;
berbatas 2 GB / 20.000 file).

## Submit (cakupan navigasi)
`/submit/code`, `/submit/notebook`, `/submit/zip`, `/submit/github` diuji **memuat tanpa error
fatal** (di `navigation.spec`). Pengiriman job aktual sengaja tidak dilakukan (produksi bersama).
