import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

import { shot, captureConsole, waitAppReady, tokenFromState } from '../utils/helpers'
import { ADMIN_STATE, API_PREFIX } from '../utils/constants'
import { ReportPage, expectNoFatalError } from '../pages/pages'
import type { ReportRunningJob, ResourceSample } from '../../frontend/src/lib/types'

async function showDevboxMetrics(page: Page, request: APIRequestContext, rows: ReportRunningJob[]) {
  const token = tokenFromState(ADMIN_STATE)
  const response = await request.get(`${API_PREFIX}/admin/report`, { headers: { Authorization: `Bearer ${token}` } })
  expect(response.status()).toBe(200)
  const report = await response.json()
  await page.addInitScript((accessToken) => {
    sessionStorage.setItem('unismuh_token', accessToken)
  }, token)
  await page.route('**/api/v1/admin/report', (route) => route.fulfill({ json: { ...report, running_jobs: rows } }))
  const url = process.env.REPORT_UI_URL ? new URL('/report', process.env.REPORT_UI_URL).href : '/report'
  await page.goto(url)
  await expect(page.getByTestId('running-job-metrics')).toBeAttached({ timeout: 30000 })
}

function devboxRow(id: number, overrides: Partial<ReportRunningJob> = {}): ReportRunningJob {
  return {
    id, name: 'Devbox VS Code', owner_name: `QA ${id}`, owner_email: 'qa@example.invalid',
    role: 'dosen', gpu_index: 0, pid: null, source_type: 'paste', runtime_seconds: 3600,
    peak_ram_mb: 8192, peak_vram_mb: 4096, peak_cpu_percent: 100, avg_gpu_util_percent: 88,
    started_at: null, is_devbox: true, ...overrides,
  }
}

function devboxSample(overrides: Partial<ResourceSample> = {}): ResourceSample {
  return {
    id: 1, ts: new Date().toISOString(), job_id: 98001, cpu_percent: 0,
    memory_used_mb: 672, gpu_index: 0, gpu_util_percent: 0, gpu_mem_used_mb: 0,
    gpu_mem_total_mb: null, gpu_temperature_c: null, gpu_power_w: null, ...overrides,
  }
}

test.describe('Laporan (admin)', () => {
  test('TC-REP-01 Laporan menampilkan seksi-seksi utama', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const rep = new ReportPage(page)
    await rep.open()
    await waitAppReady(page)
    // Laporan memindai proses+disk host (bisa >1,5 dtk saat server sibuk) -> tunggu
    // seksi pertama benar-benar muncul, bukan jeda tetap.
    await expect(page.getByText(/Informasi Sistem/i).first()).toBeVisible({ timeout: 30_000 })
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

  test('TC-REP-03 Unduh laporan PDF', async ({ page }, testInfo) => {
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
      expect(download.suggestedFilename()).toMatch(/laporan.*\.pdf$/i)
      // Isi harus PDF sungguhan, bukan HTML yang sekadar dinamai .pdf.
      const jalur = await download.path()
      if (jalur) {
        const fs = await import('node:fs/promises')
        const kepala = (await fs.readFile(jalur)).subarray(0, 5).toString('latin1')
        expect(kepala, 'berkas diawali penanda PDF').toBe('%PDF-')
      }
    } else {
      expect.soft(false, 'event download tidak terpicu (cek manual)').toBeTruthy()
    }
    await shot(page, 'report', 'after-download', testInfo)
  })
})

test.describe('Metrik Devbox terukur', () => {
  test('TC-REP-04 nol, tidak tersedia, belum diukur, dan data lama dibedakan', async ({ page, request }, testInfo) => {
    const cap = captureConsole(page)
    await showDevboxMetrics(page, request, [
      devboxRow(98001, { resource_sample: devboxSample() }),
      devboxRow(98002, { resource_sample: devboxSample({ cpu_percent: 121.5, memory_used_mb: 849, gpu_mem_used_mb: 128, gpu_util_percent: null }) }),
      devboxRow(98003, { is_devbox: undefined }),
      devboxRow(98004, { resource_sample: devboxSample({ ts: '2020-01-01T00:00:00Z', memory_used_mb: 999 }), metrics_stale: true }),
      devboxRow(98005, { name: 'QA batch', is_devbox: false }),
    ])
    const table = page.getByTestId('running-job-metrics')
    await table.scrollIntoViewIfNeeded()
    const zero = table.locator('[data-job-id="98001"] td')
    await expect(zero.nth(4)).toHaveText('0.0%')
    await expect(zero.nth(5)).toHaveText('672 MB')
    await expect(zero.nth(6)).toHaveText('0 MB')
    await expect(zero.nth(7)).toHaveText('0%')
    const partial = table.locator('[data-job-id="98002"] td')
    await expect(partial.nth(4)).toHaveText('121.5%')
    await expect(partial.nth(6)).toHaveText('128 MB')
    await expect(partial.nth(7)).toHaveText('Tidak tersedia')
    await expect(table.locator('[data-job-id="98003"] td').nth(5)).toHaveText('Belum diukur')
    await expect(table.locator('[data-job-id="98004"] td').nth(5)).toHaveText('Data lama')
    await expect(table.locator('[data-job-id="98005"] td').nth(5)).toHaveText('8.0 GB')
    await expect(table.getByRole('columnheader', { name: 'Alokasi GPU' })).toBeVisible()
    await shot(page, 'report', 'devbox-metrics-states', testInfo)
    expect(cap.pageErrors).toEqual([])
  })

  test('TC-REP-05 Devbox CPU dan tabel mobile tidak menampilkan GPU palsu', async ({ page, request }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const cap = captureConsole(page)
    await showDevboxMetrics(page, request, [devboxRow(98006, {
      gpu_index: null, resource_sample: devboxSample({ gpu_index: null, memory_used_mb: 256, gpu_mem_used_mb: null, gpu_util_percent: null }),
    })])
    const table = page.getByTestId('running-job-metrics')
    await table.scrollIntoViewIfNeeded()
    const cells = table.locator('[data-job-id="98006"] td')
    await expect(cells.nth(2)).toHaveText('CPU')
    await expect(cells.nth(5)).toHaveText('256 MB')
    await expect(cells.nth(6)).toHaveText('Tidak berlaku')
    await expect(cells.nth(7)).toHaveText('Tidak berlaku')
    const dimensions = await table.evaluate((element) => ({ left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right, width: window.innerWidth }))
    expect(dimensions.left).toBeGreaterThanOrEqual(0)
    expect(dimensions.right).toBeLessThanOrEqual(dimensions.width + 1)
    await shot(page, 'report', 'devbox-metrics-mobile', testInfo)
    expect(cap.pageErrors).toEqual([])
  })
})
