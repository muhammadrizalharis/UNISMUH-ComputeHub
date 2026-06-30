# Black-box — API, Keamanan, Performa & Responsif

## API (`api/api.spec.ts`)

| Test ID | Objective | Expected | Actual | Status |
|---------|-----------|----------|--------|--------|
| TC-API-01 | Health | `GET /health` → 200 `{status:ok}` | Sesuai | ✅ PASS |
| TC-API-02 | Auth wajib | `GET /auth/me` tanpa token → 401 | Sesuai | ✅ PASS |
| TC-API-03 | Me + schema | admin → 200, ada `id/email/role`, role=admin | Sesuai | ✅ PASS |
| TC-API-04 | Authz | student → `/admin/report` → 401/403 | Sesuai | ✅ PASS |
| TC-API-05 | Admin boleh | admin → `/admin/report` → 200 | Sesuai | ✅ PASS |
| TC-API-06 | Disk schema | `/admin/report/disk` → 200, ada `total_bytes`,`users[]` | Sesuai | ✅ PASS |
| TC-API-07 | Payload kosong | `POST /auth/login {}` → 422 | Sesuai | ✅ PASS |
| TC-API-08 | 404 | endpoint ngawur → 404 | Sesuai | ✅ PASS |
| TC-API-09 | Latensi | health<1500ms, report<8000ms | health 16ms, report ~2.1s | ✅ PASS |
| TC-API-10 | Authz report/user | student → `/admin/report/user/*` → 401/403 | Sesuai | ✅ PASS |

## Keamanan (`security/security.spec.ts`)
Lihat **security-report.md** untuk detail. Ringkas: SEC-01..SEC-09 semua ✅ PASS
(headers/clickjacking, auth wajib, privilege escalation, directory traversal, SQLi, CORS,
info disclosure, XSS, token leakage).

## Performa (`performance/performance.spec.ts`)
Lihat **performance-report.md**. PERF-PAGE (×5) ✅, PERF-API ✅, PERF-CONCURRENCY (ringan) ✅.

## Responsif (`e2e/responsive.spec.ts`) — project mobile (Pixel 7) & tablet (820×1180)

| Test ID | Objective | Expected | Actual | Status |
|---------|-----------|----------|--------|--------|
| TC-RESP (×4) | Layout responsif `/`,`/jobs`,`/storage`,`/report` | Memuat, overflow horizontal < 40px | Sesuai | ✅ PASS |
| TC-RESP-NAV | Navigasi di viewport kecil | ≥1 link navigasi (sidebar/bottom-nav) terlihat | Sesuai | ✅ PASS |

Screenshot: `screenshots/responsive/<viewport>/**`.
