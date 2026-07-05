# QA E2E — UNISMUH ComputeHub (Playwright)

Suite pengujian **end-to-end, API, keamanan, performa & responsif** untuk UNISMUH ComputeHub.
Dijalankan ulang **2026-07-05** terhadap build `main` (DB kini Postgres lokal).

## 🔢 Hasil akhir

| Metrik | Nilai |
|--------|-------|
| Total kasus uji | **81** |
| ✅ Lulus | **80** |
| ⏭️ Skip (kondisional sah) | **1** |
| ❌ Gagal | **0** |
| Durasi | ~2.0 menit |
| Bug | BUG-001 **sudah diperbaiki** (regresi ditutup TC-USR-03) |
| Artefak | screenshot · video · trace tiap langkah · HTML/JUnit/JSON report |

> **0 kegagalan fungsional. 0 celah otorisasi/injeksi. 0 error fatal JS.**
> Privilege-escalation (student → endpoint admin) DIBUKTIKAN ditolak **403**.

### 🔄 Pembaruan 2026-07-05
- **Fixture 3-token (anti-flaky & non-destruktif)**:
  - `student` = akun QA khusus **`CHqastudent`** (non-admin) → test kuota/workspace tak menyentuh mahasiswa nyata.
  - `admin` = akun sekunder stabil **`CHunismuhcomputehub`** untuk desktop/API/security → sesi-tunggal tidak
    tergganggu saat user login sbg super admin.
  - `superadmin` = **`CHSuperAdmin`** HANYA untuk uji yang butuh hak super (set kuota/policy) — permukaan kecil.
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
2. **OBS-1 (Performa) — TERATASI:** dulu endpoint ber-DB lambat (`/auth/me` ~1.1s, `/admin/report` ~2.1s)
   karena Supabase remote. Setelah pindah ke **Postgres lokal**: `/auth/me` ~12ms, `/admin/report` ~26ms.
   → `performance-report.md`.
3. **OBS-2:** `/jobs` tak punya pencarian teks (by design) — filter status saja.
4. **OBS-4 (Keamanan):** token di `localStorage` (wajar untuk SPA bearer; dimitigasi CSP). → `security-report.md`.

## 📊 Laporan
- Interaktif (langkah + video + trace): `reports/html-report/index.html` → `npm run report`
- CI: `reports/junit/results.xml`, `reports/json/results.json`
- Dokumen: `bug-report.md`, `security-report.md`, `performance-report.md`, `coverage-report.md`, `blackbox/*.md`

## 🔐 Catatan keamanan artefak
`.auth/` berisi **token bearer hidup** dan **tidak di-commit** (`.gitignore`). Video/trace/screenshot
berat juga di-ignore agar repo ramping; semuanya tetap ada di disk untuk ditinjau.
