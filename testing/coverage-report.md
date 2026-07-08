# Coverage Report — UNISMUH ComputeHub

Tanggal: 2026-07-08 · 84 kasus uji · **83 LULUS · 0 flaky · 1 skip sah · 0 GAGAL** · durasi 2.0 mnt.

## Ringkasan per project (browser/peran/viewport)

| Project | Peran / Viewport | Lulus | Skip | Gagal |
|---------|------------------|------:|-----:|------:|
| public | tanpa auth (Desktop Chrome) | 7 | 0 | 0 |
| api | bearer admin/super-admin/student | 12 | 0 | 0 |
| security | context per-peran | 9 | 0 | 0 |
| desktop | admin · 1440×900 | 38 | 1 | 0 |
| mobile | admin · Pixel 7 (393×852) | 5 | 0 | 0 |
| tablet | admin · 820×1180 | 5 | 0 | 0 |
| performance | admin · 1440×900 | 7 | 0 | 0 |

## Cakupan rute (semua dari `App.tsx`)

| Rute | Diuji | Catatan |
|------|:----:|---------|
| `/welcome` (Landing) | ✅ | render + tanpa JS error |
| `/login` | ✅ | form, validasi kosong, toggle password, login salah, redirect |
| `/` (Dashboard) | ✅ | kartu ringkasan, konten |
| `/monitor` | ✅ | chart/metrik |
| `/jobs` | ✅ | tabel, filter status, (search N/A by design), buka detail* |
| `/jobs/:id` | ✅* | dibuka bila ada baris (skip bila admin tak punya job) |
| `/storage` | ✅ | indikator kuota, **upload (UI)** + bersih (API), tombol unggah, **unduh folder & seluruh workspace `.zip`** (TC-STO-04/05/06) |
| `/submit/code` `/notebook` `/zip` `/github` | ✅ | termuat tanpa error fatal (navigasi) |
| `/users` | ✅ | tabel, pencarian, **modal Kelola Kebijakan**, form Tambah |
| `/report` | ✅ | seksi sistem + **Pemakaian Disk per User** + **unduh HTML** |
| `/report/user/:username` | ✅ (API) | otorisasi diuji via API |
| `/alerts` | ✅ | halaman + form konfigurasi ambang |
| `/admin` | ✅ | termuat (navigasi) |
| `/profile` | ✅ | identitas akun tampil |
| 404 (rute tak dikenal) | ✅ | halaman NotFound |

\* skip kondisional yang sah.

## Cakupan terhadap permintaan (checklist)

| Permintaan | Status | Bukti / Catatan |
|-----------|--------|------------------|
| Login / Logout / Sesi | ✅ | public.spec, security SEC-09, single-session diamati |
| Register | ➖ N/A | aplikasi **tidak** menyediakan registrasi mandiri (akun dibuat admin). Form "Tambah User" diuji (TC-USR-04). |
| Dashboard / Sidebar / Semua Menu | ✅ | navigation.spec (TC-NAV semua rute + TC-NAV-SIDEBAR) |
| Submit Job / Notebook / Upload ZIP / GitHub | ✅ (muat) | rute submit diuji muat; **eksekusi job nyata tidak dipicu** (lindungi GPU/antrian produksi) |
| Storage / Upload / Download | ✅ | upload UI + cleanup API; **unduh berkas, folder & seluruh workspace (`.zip`)**; unduh laporan HTML |
| Monitoring / Reports / Users / Settings / Alerts | ✅ | spec terkait |
| Scheduler / Queue | ✅ (tampil) | antrian tampil di Jobs bila ada; tak menyuntik beban |
| Docker / GPU / CPU allocation | ⚠️ verifikasi tak-merusak | lihat catatan di bawah |
| Notifications / Alerts | ✅ | alerts.spec |
| Search / Filter / Pagination | ✅/➖ | Users search ✅; Jobs filter status ✅; pencarian teks Jobs N/A; pagination tak ditemukan (data kecil) |
| Forms / Validation / Error handling | ✅ | login validation, payload kosong → 422, 404, 401/403 |
| API / Database | ✅ | api.spec (10) — status, schema, authz, latensi; DB diuji via baca (CRUD penuh tidak dilakukan demi data produksi) |
| Permission / Role | ✅ | admin vs mahasiswa (authz) |
| Browser Refresh / Back / Forward | ✅ | TC-NAV-HISTORY |
| Mobile / Tablet / Desktop | ✅ | project mobile/tablet/desktop (responsive.spec) |
| Keyboard shortcut | ➖ | tidak ada shortcut khusus terdeteksi |

### Catatan Docker / GPU / Multi-user / Concurrency / DB CRUD
Item-item ini **bersifat merusak / berisiko** pada server produksi bersama (membuat/hapus
container, alokasi GPU nyata, 50 user serentak, UPDATE/DELETE data). Sesuai prinsip keselamatan,
**tidak dijalankan dari UI uji**. Bukti isolasi & resource limit sudah ada secara terpisah
(lihat `docs/ISOLASI-PER-USER.md`, konfigurasi `--memory/--cpus/--pids-limit`, dan log job nyata).
Pengujian destruktif penuh harus dilakukan di **staging**.

## Inventaris kasus uji
Lihat folder `blackbox/` untuk tabel black-box per fitur (Test ID, Objective, Steps, Expected,
Actual, Status, Screenshot). Hasil mesin: `reports/json/results.json`, `reports/junit/results.xml`,
laporan interaktif `reports/html-report/index.html`.
