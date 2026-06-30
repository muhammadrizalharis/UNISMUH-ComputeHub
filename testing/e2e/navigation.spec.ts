import { test, expect } from '@playwright/test'

import { ROUTES } from '../utils/constants'
import { shot, captureConsole, waitAppReady, waitForShell } from '../utils/helpers'
import { expectNoFatalError, NavBar } from '../pages/pages'

/** Navigasi menyeluruh: setiap rute terproteksi + sidebar + back/forward/refresh. */
test.describe('Navigasi & Rute', () => {
  for (const route of ROUTES.protected) {
    test(`TC-NAV rute ${route} memuat tanpa error fatal`, async ({ page }, testInfo) => {
      const cap = captureConsole(page)
      const resp = await page.goto(route, { waitUntil: 'domcontentloaded' })
      await waitAppReady(page)
      const group = 'nav' + (route === '/' ? '/root' : route)
      await shot(page, group, 'view', testInfo)

      // Tidak ada error boundary / crash.
      await expectNoFatalError(page)
      // SPA selalu balas 200 untuk dokumen (index.html).
      expect(resp?.status(), `status dokumen ${route}`).toBeLessThan(400)
      // URL tetap di rute (tidak dilempar ke /welcome → berarti auth OK).
      expect(page.url()).toContain(route === '/' ? '/' : route)

      // Catat error console/JS sebagai info (soft).
      expect
        .soft(cap.pageErrors, `JS pageerror di ${route}: ${cap.pageErrors.join(' | ')}`)
        .toEqual([])
    })
  }

  test('TC-NAV-SIDEBAR klik tiap menu sidebar berpindah halaman', async ({ page }, testInfo) => {
    const nav = new NavBar(page)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await waitForShell(page)
    const items: { label: string; route: string }[] = [
      { label: 'Dashboard', route: '/' },
      { label: 'Monitor', route: '/monitor' },
      { label: 'Daftar Job', route: '/jobs' },
      { label: 'Penyimpanan', route: '/storage' },
      { label: 'Laporan', route: '/report' },
      { label: 'Peringatan', route: '/alerts' },
      { label: 'Pengguna', route: '/users' },
      { label: 'Pengaturan', route: '/admin' },
    ]
    for (const { label, route } of items) {
      const link = nav.link(label)
      await expect(link, `menu "${label}" ada di sidebar`).toBeVisible({ timeout: 10_000 })
      await link.click()
      await page.waitForURL(`**${route}`, { timeout: 10_000 }).catch(() => {})
      await page.waitForTimeout(400)
      await shot(page, 'nav/sidebar', label, testInfo)
      await expectNoFatalError(page)
      expect(page.url(), `URL setelah klik "${label}"`).toContain(route === '/' ? '/' : route)
    }
  })

  test('TC-NAV-HISTORY refresh, back, forward konsisten', async ({ page }, testInfo) => {
    await page.goto('/jobs', { waitUntil: 'domcontentloaded' })
    await waitAppReady(page)
    await page.goto('/storage', { waitUntil: 'domcontentloaded' })
    await waitAppReady(page)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitAppReady(page)
    await shot(page, 'nav/history', 'after-refresh', testInfo)
    expect(page.url()).toContain('/storage')

    await page.goBack({ waitUntil: 'domcontentloaded' })
    await waitAppReady(page)
    await shot(page, 'nav/history', 'after-back', testInfo)
    expect(page.url()).toContain('/jobs')

    await page.goForward({ waitUntil: 'domcontentloaded' })
    await waitAppReady(page)
    await shot(page, 'nav/history', 'after-forward', testInfo)
    expect(page.url()).toContain('/storage')
  })
})
