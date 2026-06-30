import { test, expect } from '@playwright/test'

import { shot, captureConsole, waitAppReady } from '../utils/helpers'
import { ReportPage, expectNoFatalError } from '../pages/pages'

test.describe('Laporan (admin)', () => {
  test('TC-REP-01 Laporan menampilkan seksi-seksi utama', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const rep = new ReportPage(page)
    await rep.open()
    await waitAppReady(page)
    await page.waitForTimeout(1500)
    await shot(page, 'report', 'overview', testInfo)
    await expectNoFatalError(page)
    const body = await page.locator('body').innerText()
    expect(body).toMatch(/Informasi Sistem/i)
    expect(body).toMatch(/Disk/i)
    expect.soft(cap.pageErrors, cap.pageErrors.join(' | ')).toEqual([])
  })

  test('TC-REP-02 Seksi Pemakaian Disk per User hadir', async ({ page }, testInfo) => {
    const rep = new ReportPage(page)
    await rep.open()
    await waitAppReady(page)
    const disk = rep.diskSection()
    await expect(disk).toBeVisible({ timeout: 15_000 })
    await disk.scrollIntoViewIfNeeded()
    // Tunggu hingga tabel terisi atau status "menghitung".
    await page.waitForTimeout(2000)
    await shot(page, 'report', 'disk-section', testInfo)
    const text = await disk.innerText()
    expect(text).toMatch(/User|menghitung|Total disk|GB|TB|byte/i)
  })

  test('TC-REP-03 Unduh laporan HTML', async ({ page }, testInfo) => {
    const rep = new ReportPage(page)
    await rep.open()
    await waitAppReady(page)
    const btn = rep.downloadButton()
    await expect(btn, 'tombol unduh laporan tampil').toBeVisible({ timeout: 15_000 })
    await shot(page, 'report', 'before-download', testInfo)
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 20_000 }).catch(() => null),
      btn.click(),
    ])
    if (download) {
      expect(download.suggestedFilename()).toMatch(/laporan.*\.html/i)
    } else {
      expect.soft(false, 'event download tidak terpicu (cek manual)').toBeTruthy()
    }
    await shot(page, 'report', 'after-download', testInfo)
  })
})
