import { test, expect } from '@playwright/test'

import { shot, captureConsole, waitAppReady } from '../utils/helpers'
import { MonitorPage, AlertsPage, expectNoFatalError } from '../pages/pages'

test.describe('Monitor & Peringatan (admin)', () => {
  test('TC-MON-01 Monitor menampilkan metrik/chart', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const mon = new MonitorPage(page)
    await mon.open()
    await waitAppReady(page)
    await page.waitForTimeout(1500)
    await shot(page, 'monitor', 'view', testInfo)
    await expectNoFatalError(page)
    const charts = page.locator('canvas, svg')
    const body = await page.locator('body').innerText()
    expect(
      (await charts.count()) > 0 || /CPU|RAM|GPU|%/i.test(body),
      'ada chart atau metrik tekstual',
    ).toBeTruthy()
    expect.soft(cap.pageErrors, cap.pageErrors.join(' | ')).toEqual([])
  })

  test('TC-ALERT-01 Halaman peringatan + form konfigurasi', async ({ page }, testInfo) => {
    const alerts = new AlertsPage(page)
    await alerts.open()
    await waitAppReady(page)
    await shot(page, 'alerts', 'view', testInfo)
    await expectNoFatalError(page)
    const body = await page.locator('body').innerText()
    expect(body).toMatch(/peringatan|ambang|threshold|CPU|RAM|disk/i)
  })

  test('TC-ALERT-02 Input konfigurasi ambang ada (tanpa simpan)', async ({ page }, testInfo) => {
    const alerts = new AlertsPage(page)
    await alerts.open()
    await waitAppReady(page)
    const inputs = page.locator('input[type=number], input[type=text], input[type=email]')
    // Form konfigurasi dimuat async -> tunggu minimal satu input.
    await expect(inputs.first(), 'input konfigurasi muncul').toBeVisible({ timeout: 15_000 })
    await shot(page, 'alerts', 'config-form', testInfo)
    expect.soft(await inputs.count(), 'ada input konfigurasi').toBeGreaterThan(0)
  })
})
