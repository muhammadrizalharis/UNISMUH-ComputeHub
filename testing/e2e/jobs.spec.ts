import { test, expect } from '@playwright/test'

import { shot, captureConsole, waitAppReady } from '../utils/helpers'
import { JobsPage, expectNoFatalError } from '../pages/pages'

test.describe('Daftar Job', () => {
  test('TC-JOB-01 Tabel/empty-state job tampil', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const jobs = new JobsPage(page)
    await jobs.open()
    await waitAppReady(page)
    // Job dimuat async (TanStack Query) -> tunggu tabel render.
    await expect(jobs.table, 'tabel job muncul').toBeVisible({ timeout: 15_000 })
    await shot(page, 'jobs', 'list', testInfo)
    await expectNoFatalError(page)
    const hasTable = (await jobs.table.count()) > 0
    const bodyText = await page.locator('body').innerText()
    expect(hasTable || /belum ada|tidak ada|kosong/i.test(bodyText), 'tabel atau empty-state').toBeTruthy()
    expect.soft(cap.pageErrors, cap.pageErrors.join(' | ')).toEqual([])
  })

  test('TC-JOB-02 Pencarian job (jika tersedia)', async ({ page }, testInfo) => {
    const jobs = new JobsPage(page)
    await jobs.open()
    await waitAppReady(page)
    const search = jobs.searchBox()
    test.skip((await search.count()) === 0, 'kotak pencarian tidak ada di halaman ini')
    await search.fill('zzz_tidak_mungkin_ada_123')
    await page.waitForTimeout(700)
    await shot(page, 'jobs', 'search-empty', testInfo)
    await search.fill('')
    await page.waitForTimeout(400)
  })

  test('TC-JOB-03 Filter status (jika tersedia)', async ({ page }, testInfo) => {
    const jobs = new JobsPage(page)
    await jobs.open()
    await waitAppReady(page)
    const select = jobs.statusFilter()
    test.skip((await select.count()) === 0, 'filter status tidak ada')
    const options = await select.locator('option').count()
    if (options > 1) {
      await select.selectOption({ index: 1 })
      await page.waitForTimeout(600)
      await shot(page, 'jobs', 'filter-applied', testInfo)
    }
  })

  test('TC-JOB-04 Buka detail job (jika ada baris)', async ({ page }, testInfo) => {
    const jobs = new JobsPage(page)
    await jobs.open()
    await waitAppReady(page)
    const count = await jobs.rows.count()
    test.skip(count === 0, 'tidak ada job untuk dibuka')
    await jobs.rows.first().click()
    await page.waitForTimeout(800)
    await shot(page, 'jobs', 'detail', testInfo)
    await expectNoFatalError(page)
    expect(page.url()).toMatch(/\/jobs\/\d+/)
  })
})
