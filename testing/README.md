# QA E2E — UNISMUH ComputeHub (Playwright)

Suite pengujian **end-to-end, API, keamanan, performa & responsif** untuk UNISMUH ComputeHub.
Dijalankan ulang **2026-07-08** terhadap build `main` (DB Postgres lokal).

## 🔢 Hasil akhir

| Metrik | Nilai |
|--------|-------|
| Total kasus uji | **92** |
| ✅ Lulus | **90** |
| ⏭️ Skip (kondisional sah) | **2** |
| ❌ Gagal | **0** |
| Flaky | **0** |
| Durasi | ~2.1 menit |
| Bug | BUG-001 & BUG-002 **sudah diperbaiki** (regresi ditutup TC-USR-03 & TC-RESP) |
| Artefak | screenshot · video · trace tiap langkah · HTML/JUnit/JSON report |

> **0 kegagalan fungsional. 0 celah otorisasi/injeksi. 0 error fatal JS.**
> Privilege-escalation (student → endpoint admin) DIBUKTIKAN ditolak **403**.

### 🔄 Pembaruan 2026-07-08
- **Fitur baru diuji — Unduh FOLDER & seluruh workspace sebagai `.zip`** (halaman Penyimpanan):
  - `TC-STO-04` (API): unduh **seluruh workspace** → `workspace.zip` (HTTP 200, magic bytes `PK`).
  - `TC-STO-05` (API): unduh **folder tertentu** (buat file di subfolder → unduh `<folder>.zip` → bersihkan).
  - `TC-STO-06` (UI): tombol **"Unduh semua"** memicu unduhan berkas `.zip`.
  - Ketiganya **LULUS**. Folder cache internal (`.local`/`.cache`) dilewati; berbatas 2 GB / 20k file.
- **Regresi ditemukan & LANGSUNG diperbaiki (BUG-002):** tombol "Unduh semua" baru membuat header
  `/storage` **overflow horizontal di mobile** (412px). Diperbaiki (baris tombol `flex-wrap`);
  dikunci `TC-RESP /storage` (mobile 412×839 & tablet 820×1180) → kini **LULUS**.
- **Robustness suite:** error `Event` DOM benign (gagal muat worker editor **Monaco dari CDN
  jsdelivr** — jaringan eksternal) kini diklasifikasikan **terpisah** dari error JS aplikasi
  (yang tetap menggagalkan); tenggang muat Monaco pada uji auto-save 20s→45s. Menghapus flaky
  akibat jaringan CDN.
- Hasil run: **84 kasus · 83 lulus · 1 skip · 0 gagal · 0 flaky · 2.0 menit.**
- **Cakupan PER-PERAN dilengkapi (super admin · admin · dosen · mahasiswa):**
  - Dibuat akun QA dosen khusus (`CHqadosen`) → token dosen di-mint (sebelumnya **belum ada akun dosen**).
  - `api/roles.spec.ts` — **matriks otorisasi 4 peran**: `/auth/me` peran benar (+ `is_superadmin`);
    `/admin/report` hanya admin & super admin (200), dosen & mahasiswa **ditolak 403**;
    `/monitoring/overview` semua peran 200.
  - `e2e/roles.spec.ts` — **UI dari sisi mahasiswa & dosen**: Dashboard menampilkan identitas peran
    ("Ruang Belajar Mahasiswa" / "Ruang Kerja Dosen"); sidebar **tanpa** menu admin
    (Monitor/Laporan/Peringatan/Pengguna/Pengaturan); rute admin tak membocorkan data.
  - Super admin diuji saat ada sesi aktif; bila akun super admin tak login → **skip sah**
    (single-session; sengaja tak mengganggu akun super admin yang dipakai user di browser).
- Hasil run akhir: **92 kasus · 90 lulus · 2 skip sah · 0 gagal · 0 flaky · 2.1 menit.**

### 🔄 Pembaruan 2026-07-07
- **Uji kuota disk** kini memakai token **admin** (kuota storage dapat diatur admin & super admin,
  bukan super admin saja) + verifikasi kuota kembali ke **default global (30 GB)** setelah di-clear.
- Hasil run: **81 kasus · 80 lulus · 1 skip · 0 gagal · 0 flaky · 2.0 menit**.

### 🔄 Pembaruan 2026-07-05
- **Fixture 3-token (anti-flaky & non-destruktif)**:
  - `student` = akun QA khusus (non-admin) → test kuota/workspace tak menyentuh mahasiswa nyata.
  - `admin` = akun admin sekunder khusus uji untuk desktop/API/security → sesi-tunggal tidak
    tergganggu saat user login sbg super admin.
  - `superadmin` = akun super admin HANYA untuk uji yang butuh hak super (set kuota/policy) — permukaan kecil.
- **OBS-1 TERATASI**: migrasi ke Postgres lokal → latensi endpoint ber-DB turun drastis.
- **Baris job kini clickable** seluruhnya (bukan hanya nama) — TC-JOB-04 memvalidasi ini.
- **Catatan**: `GET /users` akan 500 bila ADA user dengan email tak lolos `EmailStr` (mis. TLD `.test`).
  Normalnya tak terjadi (pembuatan user via API sudah memvalidasi email). Akun QA memakai domain valid.

## ⚠️ Konteks penting (server PRODUKSI bersama)
Pengujian dijalankan pada server yang dipakai pengguna nyata. Karena itu suite ini **non-destruktif**:
- Autentikasi via **injeksi token** (reuse `session_token` akun yang ada) → tak mengganggu sesi user.
- Operasi destruktif (hapus file) hanya pada `/persist` **akun uji sendiri** (terisolasi, reversibel).
- **Tanpa** load test 20/50 user (risiko DoS) dan **tanpa** exhaust rate-limit login (risiko mengunci user di balik tunnel berbagi-IP).
- Keamanan diuji dengan memverifikasi aplikasi **menolak** serangan (bukan mengeksploitasi/merusak).
- **Headed mode tidak tersedia** (server headless, `DISPLAY` kosong) → headless + **video + trace + screenshot** memberi peninjauan visual setara.

## 📁 Struktur
```
testing/
├── playwright.config.ts      # 7 project: public, api, security, desktop, mobile, tablet, performance
├── global-setup.ts           # health-check + mint token (admin & student) -> .auth/*.json
├── scripts/mint_tokens.py     # buat storageState (non-destruktif)
├── pages/pages.ts             # Page Object Models
├── fixtures/ utils/           # helper screenshot, console-capture, token
├── auth/public.spec.ts        # Login, Landing, validasi, 404, redirect
├── e2e/                       # dashboard, navigation, jobs, storage, report, users, monitor-alerts, profile, responsive
├── api/api.spec.ts            # 10 uji API (status, schema, authz, latensi)
├── security/security.spec.ts  # SEC-01..09 (headers, authz, traversal, SQLi, XSS, CORS, token)
├── performance/performance.spec.ts
├── blackbox/*.md              # tabel black-box per fitur
├── reports/                   # html-report/ · junit/ · json/ · perf/
├── screenshots/ videos/ traces/  (digenerate; tidak di-commit — lihat .gitignore)
├── bug-report.md · security-report.md · performance-report.md · coverage-report.md
└── README.md
```

## ▶️ Cara menjalankan
```bash
cd testing
npm install
npx playwright install chromium
npx playwright test                 # semua project
npx playwright test --project=api   # satu project
npm run report                      # buka HTML report
```
Prasyarat: backend hidup di `http://127.0.0.1:8088`, venv di `../backend/.venv` (untuk mint token).

## 🐞 Temuan utama
1. **BUG-001 (UX) — SUDAH DIPERBAIKI:** dropdown "Aksi" di tabel Pengguna dulu menutup sendiri saat tabel
   overflow horizontal (focus-scroll). Kini menu di-render via portal + `position: fixed` + mengabaikan
   scroll 350ms pertama saat buka. Regresi dikunci oleh `TC-USR-03`. → `bug-report.md`.
2. **BUG-002 (UX responsif) — SUDAH DIPERBAIKI (2026-07-08):** tombol baru "Unduh semua" membuat header
   `/storage` overflow horizontal di mobile (412px). Baris tombol dibuat `flex-wrap`. Regresi dikunci
   `TC-RESP /storage` (mobile 412×839 & tablet 820×1180). → `bug-report.md`.
3. **OBS-1 (Performa) — TERATASI:** dulu endpoint ber-DB lambat (`/auth/me` ~1.1s, `/admin/report` ~2.1s)
   karena Supabase remote. Setelah pindah ke **Postgres lokal**: `/auth/me` ~70ms, `/admin/report` ~30ms.
   → `performance-report.md`.
4. **OBS-2:** `/jobs` tak punya pencarian teks (by design) — filter status saja.
5. **OBS-4 (Keamanan):** token di `localStorage` (wajar untuk SPA bearer; dimitigasi CSP). → `security-report.md`.
6. **OBS-5 (Ketahanan):** editor **Monaco dimuat dari CDN jsdelivr** — bila jaringan kampus tersendat,
   muat editor bisa lambat (uji auto-save diberi tenggang 45s) & sesekali memancarkan `Event` benign.
   Saran hardening: bundel Monaco **same-origin** agar tahan jaringan lambat/offline. → `bug-report.md`.

## 📊 Laporan
- **Word (lengkap + screenshot):** `Laporan-Pengujian-UNISMUH-ComputeHub.docx` (siap dikirim/cetak).
  Regenerasi: `../backend/.venv/bin/python scripts/build_report_docx.py` (memilih screenshot terbaru otomatis).
- Interaktif (langkah + video + trace): `reports/html-report/index.html` → `npm run report`
- CI: `reports/junit/results.xml`, `reports/json/results.json`
- Dokumen: `bug-report.md`, `security-report.md`, `performance-report.md`, `coverage-report.md`, `blackbox/*.md`

## 🔐 Catatan keamanan artefak
`.auth/` berisi **token bearer hidup** dan **tidak di-commit** (`.gitignore`). Video/trace/screenshot
berat juga di-ignore agar repo ramping; semuanya tetap ada di disk untuk ditinjau.
