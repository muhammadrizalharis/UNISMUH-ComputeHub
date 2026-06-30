import { test, expect } from '@playwright/test'

import { shot, captureConsole, waitAppReady } from '../utils/helpers'
import { DashboardPage, expectNoFatalError } from '../pages/pages'

test.describe('Dashboard', () => {
  test('TC-DASH-01 Dashboard memuat kartu ringkasan', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const dash = new DashboardPage(page)
    await dash.open()
    await waitAppReady(page)
    await shot(page, 'dashboard', 'overview', testInfo)
    await expectNoFatalError(page)
    // Ada minimal beberapa kartu / angka ringkasan.
    const cards = page.locator('.card-pad, [class*="rounded-xl"]')
    expect(await cards.count(), 'jumlah kartu/elemen ringkasan').toBeGreaterThan(0)
    expect.soft(cap.pageErrors, cap.pageErrors.join(' | ')).toEqual([])
  })

  test('TC-DASH-02 Konten utama terlihat (tidak blank)', async ({ page }) => {
    const dash = new DashboardPage(page)
    await dash.open()
    await waitAppReady(page)
    const text = await page.locator('body').innerText()
    expect(text.trim().length, 'body tidak kosong').toBeGreaterThan(40)
  })
})
