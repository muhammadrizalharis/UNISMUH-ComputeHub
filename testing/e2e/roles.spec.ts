import { test, expect } from '@playwright/test'

import { STUDENT_STATE, DOSEN_STATE, SUPERADMIN_STATE } from '../utils/constants'
import { shot } from '../utils/helpers'
import { expectNoFatalError } from '../pages/pages'

/**
 * Pengujian PER-PERAN dari sisi MAHASISWA & DOSEN (bukan admin).
 *
 * Memakai storageState token masing-masing peran dalam context terpisah (non-destruktif).
 * Membuktikan: (1) render role-aware (identitas peran tampil di Dashboard) dan
 * (2) pemisahan akses UI (menu admin TIDAK tampil di sidebar mahasiswa/dosen, dan rute
 * admin tak membocorkan data). Penegakan otorisasi tingkat API diuji di `api/roles.spec.ts`.
 */

// Menu yang HANYA untuk admin — tidak boleh muncul di sidebar mahasiswa/dosen.
const ADMIN_ONLY_NAV = ['Monitor', 'Laporan', 'Peringatan', 'Pengguna', 'Pengaturan']
// Menu umum yang WAJIB ada untuk semua peran yang login.
const COMMON_NAV = ['Dashboard', 'Daftar Job', 'Penyimpanan', 'Bantuan']

const ROLES = [
  {
    role: 'mahasiswa',
    state: STUDENT_STATE,
    title: 'Ruang Belajar Mahasiswa',
    badge: 'Mahasiswa',
  },
  {
    role: 'dosen',
    state: DOSEN_STATE,
    title: 'Ruang Kerja Dosen',
    badge: 'Dosen',
  },
] as const

test.describe('Peran & Otorisasi UI (mahasiswa & dosen)', () => {
  for (const r of ROLES) {
    test(`TC-ROLE-${r.role.toUpperCase()}-01 Dashboard role-aware + sidebar tanpa menu admin`, async ({
      browser,
    }, testInfo) => {
      const ctx = await browser.newContext({ storageState: r.state })
      const page = await ctx.newPage()
      try {
        await page.goto('/', { waitUntil: 'domcontentloaded' })
        await page.waitForTimeout(1500)
        await shot(page, `roles-${r.role}`, 'dashboard', testInfo)
        await expectNoFatalError(page)

        // (1) Dashboard menampilkan identitas peran (bukti render role-aware).
        const body = (await page.locator('body').innerText().catch(() => '')) || ''
        expect(body, `judul peran "${r.title}" tampil`).toContain(r.title)
        expect(body, `badge peran "${r.badge}" tampil`).toContain(r.badge)

        // (2) Sidebar: TIDAK ada menu admin.
        const aside = (await page.locator('aside').first().innerText().catch(() => '')) || ''
        for (const item of ADMIN_ONLY_NAV) {
          expect(aside, `${r.role} TIDAK boleh melihat menu admin "${item}"`).not.toContain(
            item,
          )
        }
        // (3) Sidebar: menu umum tetap ada.
        for (const item of COMMON_NAV) {
          expect(aside, `${r.role} harus melihat menu "${item}"`).toContain(item)
        }
      } finally {
        await ctx.close()
      }
    })

    test(`TC-ROLE-${r.role.toUpperCase()}-02 Rute admin (/users) tidak membocorkan data pengguna`, async ({
      browser,
    }, testInfo) => {
      const ctx = await browser.newContext({ storageState: r.state })
      const page = await ctx.newPage()
      try {
        await page.goto('/users', { waitUntil: 'domcontentloaded' })
        await page.waitForTimeout(1500)
        await shot(page, `roles-${r.role}`, 'users-blocked', testInfo)
        await expectNoFatalError(page)
        // Untuk non-admin, query admin di-nonaktifkan → tabel pengguna tak berisi baris data.
        // (Penegakan sesungguhnya di API: lihat `api/roles.spec.ts` → 403.)
        const rows = await page.locator('table tbody tr').count()
        expect(rows, `${r.role} tak boleh melihat baris data pengguna`).toBe(0)
      } finally {
        await ctx.close()
      }
    })
  }

  test('TC-ROLE-SUPERADMIN-01 UI super admin: menu admin lengkap + badge (super admin) di Pengguna', async ({
    browser,
  }, testInfo) => {
    // Token super admin sah hanya bila akun punya sesi (self-healing mint menyiapkannya
    // bila kosong). Bila tetap 401 (mis. dirotasi login manusia di tengah uji) → skip sah.
    const ctx = await browser.newContext({ storageState: SUPERADMIN_STATE })
    const page = await ctx.newPage()
    try {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1500)
      const landedLogin = page.url().includes('/login')
      test.skip(landedLogin, 'Token super admin tak sah (sesi dirotasi) — dilewati sah.')

      await shot(page, 'roles-superadmin', 'dashboard', testInfo)
      await expectNoFatalError(page)

      // (1) Sidebar: SEMUA menu admin tampil.
      const aside = (await page.locator('aside').first().innerText().catch(() => '')) || ''
      for (const item of [...ADMIN_ONLY_NAV, ...COMMON_NAV]) {
        expect(aside, `super admin melihat menu "${item}"`).toContain(item)
      }

      // (2) Halaman Pengguna: baris data ADA + penanda "(super admin)" tampil.
      await page.goto('/users', { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(2000)
      await shot(page, 'roles-superadmin', 'users', testInfo)
      const rows = await page.locator('table tbody tr').count()
      expect(rows, 'super admin melihat data pengguna').toBeGreaterThan(0)
      const body = (await page.locator('body').innerText().catch(() => '')) || ''
      expect(body, 'penanda super admin tampil').toMatch(/super admin/i)

      // (3) Halaman Pengaturan (khusus admin) terbuka tanpa error fatal.
      await page.goto('/admin', { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1500)
      await shot(page, 'roles-superadmin', 'settings', testInfo)
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })
})
