import { test, expect } from '@playwright/test'

import { shot, waitAppReady } from '../utils/helpers'
import { expectNoFatalError } from '../pages/pages'

/**
 * Berjalan di project "mobile" (Pixel 7) dan "tablet" (820x1180), keduanya
 * memakai storageState admin. Memverifikasi layout responsif & navigasi.
 */
const PAGES = ['/', '/jobs', '/storage', '/report']

test.describe('Responsif', () => {
  for (const route of PAGES) {
    test(`TC-RESP ${route} layout responsif`, async ({ page }, testInfo) => {
      await page.goto(route, { waitUntil: 'domcontentloaded' })
      await waitAppReady(page)
      const vp = page.viewportSize()
      const tag = `${vp?.width}x${vp?.height}`
      await shot(page, `responsive/${tag}`, route === '/' ? 'root' : route.replace(/\//g, '_'), testInfo)
      await expectNoFatalError(page)
      // Tidak ada overflow horizontal yang parah (scrollWidth ~ clientWidth).
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect.soft(overflow, `overflow horizontal di ${route} (${tag})`).toBeLessThan(40)
    })
  }

  test('TC-RESP-NAV navigasi tersedia di viewport kecil', async ({ page }, testInfo) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await waitAppReady(page)
    await shot(page, 'responsive/nav', 'home', testInfo)
    // Minimal salah satu link navigasi terlihat (sidebar atau bottom-nav).
    const navLinks = page.getByRole('link', { name: /Dashboard|Daftar Job|Penyimpanan|Profil/i })
    expect(await navLinks.count(), 'ada link navigasi').toBeGreaterThan(0)
  })
})
