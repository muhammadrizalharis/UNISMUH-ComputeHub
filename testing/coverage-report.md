# Coverage Report — UNISMUH ComputeHub

## Verifikasi Drag-and-Drop 24 September 2026

- Penyimpanan v1.15.0: `TC-STO-10` sampai `TC-STO-13` lulus tanpa retry dengan API
	tiruan. Cakupan: direktori lebih dari 100 entri per batch browser, subfolder,
	folder/file kosong, tujuan unggah, potongan 24 MB, pencegahan unggahan bersamaan,
	kegagalan baca/server, batas 256 MB per file, pointer/keyboard resize, penyimpanan
	lebar, reset ukuran, serta layout desktop/mobile/tablet tanpa overflow horizontal.
- `TC-STO-14` lulus menggunakan API nyata dan folder QA sementara; isi file serta
	direktori kosong diverifikasi, lalu hanya folder QA tersebut dipindahkan ke sampah.
- Setelah penerapan frontend, `TC-STO-02`, `TC-STO-07`, `TC-STO-13`, dan `TC-STO-14`
	lulus pada build produksi. `07` dan `13` tetap memakai API tiruan; `02` dan `14`
	memakai API nyata. Tombol unggah lama dan daftar 4.005 item tetap berfungsi.
- TypeScript dan build Vite lulus; PDF panduan diperbarui. Frontend diterapkan tanpa
	restart backend (PID sebelum/sesudah tetap sama). Teks sumber helpbot diperbarui,
	tetapi pemuatan ulang backend sengaja ditunda sampai restart berikutnya yang aman.
- Uji terarah saja; bukan klaim menjalankan ulang seluruh suite historis di bawah.

## Verifikasi Terarah 24 September 2026

- Penyimpanan v1.14.0: 6 uji backend `tests.test_workspace` lulus pada direktori sementara.
- `TC-STO-07` sampai `TC-STO-09`: 3 uji browser lulus tanpa retry pada pratinjau lokal
	dengan API tiruan, tanpa perubahan data pengguna.
- Setelah penerapan: `TC-STO-01`, `TC-STO-02`, dan `TC-STO-06` lulus pada layanan
	produksi dengan akun QA (halaman, unggah, unduh); hanya berkas uji sendiri dibersihkan.
- API directory terverifikasi HTTP 200 melalui localhost dan domain kampus, dengan
	metadata halaman; tanpa login ditolak HTTP 401. Pembacaan metadata workspace terdampak
	memastikan `phd_project`, subfolder `code`, dan berkas kode kembali terdaftar.
- Cakupan: semua 4.005 berkas dapat dijangkau; folder saudara tidak tersembunyi;
	paginasi root dan subfolder; baca file; coba ulang setelah galat; penyegaran;
	Penyimpanan dan explorer notebook pada desktop/mobile; isolasi path antar-pengguna.
- Batas total 4.000 item dihapus. Respons dibagi per folder/halaman, bukan memotong
	keseluruhan workspace. Kuota, batas unggahan, cache tersembunyi, dan symlink guard tetap.
- Ini hasil pengujian terarah, bukan klaim menjalankan ulang seluruh suite di bawah.

## Riwayat Pengujian

Tanggal: 2026-07-21 · 106 kasus uji · **105 LULUS · 0 flaky · 1 skip sah · 0 GAGAL** · durasi 2.5 mnt.

> Pembaruan 2026-07-21: +14 kasus baru — siklus **Sampah job** (soft-delete/restore/purge, RBAC
> 4 peran; `api/trash.spec.ts`), **upload folder chunked** end-to-end + explorer file job +
> endpoint **/raw** (PNG inline, SVG dipaksa octet-stream, anti-traversal; `api/folderjob.spec.ts`),
> **klasifikasi laporan** akun sistem/container (`api/report-classify.spec.ts`), **UI super admin**
> (`e2e/roles.spec.ts`), dan `api/quota.spec.ts` kini **sadar MODE LUNAK** (SOFT_LIMIT_ENABLED:
> over-kuota diterima+alert, bukan ditolak). Token super admin kini SAH via self-healing sesi di
> `mint_tokens.py` (provisikan sid HANYA bila kosong — tak menendang siapa pun) → uji super admin
> yang dulu selalu skip kini benar-benar berjalan.

## Ringkasan per project (browser/peran/viewport)

| Project | Peran / Viewport | Lulus | Skip | Gagal |
|---------|------------------|------:|-----:|------:|
| public | tanpa auth (Desktop Chrome) | 7 | 0 | 0 |
| api | bearer admin/super-admin/student/**dosen** (+trash, folder, report-classify) | 29 | 0 | 0 |
| security | context per-peran | 9 | 0 | 0 |
| desktop | admin + **mahasiswa/dosen/super admin** · 1440×900 | 43 | 1 | 0 |
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
| Permission / Role | ✅ | **matriks 4 peran** (super admin·admin·dosen·mahasiswa): `/auth/me` + `/admin/report` 403 utk dosen/mhs (`api/roles.spec`); **UI role-aware** sidebar & dashboard (`e2e/roles.spec`) |
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
