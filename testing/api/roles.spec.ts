import { test, expect } from '@playwright/test'

import {
  API_PREFIX,
  ADMIN_STATE,
  SUPERADMIN_STATE,
  STUDENT_STATE,
  DOSEN_STATE,
} from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * Matriks OTORISASI 4 PERAN (super admin, admin, dosen, mahasiswa) langsung ke API.
 *  - `/auth/me`            → peran benar (+ `is_superadmin` khusus super admin).
 *  - `/admin/report`       → HANYA admin & super admin (200); dosen & mahasiswa DITOLAK (403).
 *  - `/monitoring/overview`→ endpoint umum: SEMUA peran login boleh (200).
 *
 * Catatan super admin: token QA super admin hanya sah bila akun super admin sedang punya
 * sesi aktif (single-session). Bila tidak (user tak login sbg super admin) → `/auth/me` 401
 * → uji super admin DI-SKIP secara sah (bukan kegagalan; permukaan sengaja kecil & aman).
 */

interface RoleCase {
  label: string
  state: string
  meRole: string
  isSuper: boolean
  adminAllowed: boolean
}

const CASES: RoleCase[] = [
  { label: 'superadmin', state: SUPERADMIN_STATE, meRole: 'admin', isSuper: true, adminAllowed: true },
  { label: 'admin', state: ADMIN_STATE, meRole: 'admin', isSuper: false, adminAllowed: true },
  { label: 'dosen', state: DOSEN_STATE, meRole: 'dosen', isSuper: false, adminAllowed: false },
  { label: 'mahasiswa', state: STUDENT_STATE, meRole: 'mahasiswa', isSuper: false, adminAllowed: false },
]

test.describe('Matriks otorisasi 4 peran (API)', () => {
  for (const c of CASES) {
    test(`TC-ROLE-API-${c.label} identitas & akses sesuai peran`, async ({ request }) => {
      const tok = tokenFromState(c.state)
      const auth = { Authorization: `Bearer ${tok}` }

      const me = await request.get(`${API_PREFIX}/auth/me`, { headers: auth })
      // Super admin: token hanya sah bila ada sesi aktif; bila 401 → skip yang sah.
      test.skip(
        c.label === 'superadmin' && me.status() === 401,
        'Token super admin tak sah (tidak ada sesi aktif) — dilewati secara sah.',
      )
      expect(me.status(), `${c.label} /auth/me`).toBe(200)
      const body = await me.json()
      expect(body.role, `${c.label} peran benar`).toBe(c.meRole)
      if (c.isSuper) {
        expect(body.is_superadmin, 'flag super admin true').toBeTruthy()
      } else {
        expect(body.is_superadmin ?? false, `${c.label} bukan super admin`).toBeFalsy()
      }

      // Endpoint ADMIN (laporan platform).
      const adm = await request.get(`${API_PREFIX}/admin/report`, { headers: auth })
      if (c.adminAllowed) {
        expect(adm.status(), `${c.label} BOLEH /admin/report`).toBe(200)
      } else {
        expect([401, 403], `${c.label} DILARANG /admin/report`).toContain(adm.status())
      }

      // Endpoint umum (semua peran yang login boleh).
      const ov = await request.get(`${API_PREFIX}/monitoring/overview`, { headers: auth })
      expect(ov.status(), `${c.label} BOLEH /monitoring/overview`).toBe(200)
    })
  }
})
