import { test, expect } from '@playwright/test'

import { SUPERADMIN_STATE } from '../utils/constants'
import { expectNoFatalError } from '../pages/pages'

const unlimited = { state: 'unlimited', value: null, local_value: null, source: null, inherited: false }

function snapshot(cpuCores = 1.5, writable = false) {
  return {
    available: true,
    reason: null,
    read_only: true,
    writable,
    source: 'cgroup_v2',
    collected_at: new Date().toISOString(),
    users: [
      {
        uid: 1015,
        username: 'linux-qa-utama',
        active: true,
        cgroup: '/user.slice/user-1015.slice',
        allowed_cpus: '0-7',
        managed: { by_computehub: false, external: [] },
        limits: {
          cpu_cores: { state: 'limited', value: cpuCores, local_value: 4, source: '/user.slice', inherited: true },
          memory_high_bytes: unlimited,
          memory_max_bytes: { state: 'limited', value: 8589934592, local_value: 8589934592, source: '/user.slice/user-1015.slice', inherited: false },
          tasks: { state: 'limited', value: 512, local_value: 512, source: '/user.slice/user-1015.slice', inherited: false },
        },
      },
      {
        uid: 1013,
        username: 'linux-qa-aturan-it',
        active: true,
        cgroup: '/user.slice/user-1013.slice',
        allowed_cpus: '0-7',
        managed: { by_computehub: false, external: ['50-MemoryMax.conf'] },
        limits: { cpu_cores: unlimited, memory_high_bytes: unlimited, memory_max_bytes: { state: 'limited', value: 137438953472, local_value: 137438953472, source: '/user.slice/user-1013.slice', inherited: false }, tasks: unlimited },
      },
      { uid: 1016, username: 'linux-qa-tidak-aktif', active: false, cgroup: '/user.slice/user-1016.slice', allowed_cpus: null, limits: null, managed: null },
    ],
  }
}

test.describe('Panel Akun Linux: mode tulis runtime (super admin)', () => {
  test('TC-LINUX-UI-03 admin biasa tidak melihat editor walau writable', async ({ page }) => {
    await page.route('**/api/v1/admin/linux-accounts/limits', (route) => route.fulfill({ json: snapshot(1.5, true) }))
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    const panel = page.getByRole('region', { name: 'Akun Linux', exact: true })
    await expect(panel.getByText('Baca saja', { exact: true })).toBeVisible()
    await panel.getByRole('button', { name: 'Rincian akun linux-qa-utama', exact: true }).click()
    await expect(panel.getByTestId('linux-editor-1015')).toHaveCount(0)
    await expect(panel.getByRole('button', { name: /Pasang batas runtime/ })).toHaveCount(0)
  })

  test('TC-LINUX-UI-04 super admin: konfirmasi wajib, aturan IT dilindungi, PUT/DELETE terkirim', async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: SUPERADMIN_STATE })
    const page = await ctx.newPage()
    const writes: { method: string; url: string; body: unknown }[] = []
    try {
      await page.route('**/api/v1/admin/linux-accounts/limits', (route) => route.fulfill({ json: snapshot(1.5, true) }))
      await page.route('**/api/v1/admin/linux-accounts/*/limits', (route) => {
        const req = route.request()
        writes.push({ method: req.method(), url: req.url(), body: req.postDataJSON() })
        return route.fulfill({ json: { unit: 'user-1015.slice', properties: { CPUQuota: '200%' }, dropins: ['50-CPUQuota.conf'], removed: req.method() === 'DELETE' ? ['50-CPUQuota.conf'] : [], note: null } })
      })
      await page.goto('/admin', { waitUntil: 'domcontentloaded' })
      const panel = page.getByRole('region', { name: 'Akun Linux', exact: true })
      const landedLogin = page.url().includes('/login')
      test.skip(landedLogin, 'Token super admin tak sah (sesi dirotasi) — dilewati sah.')
      await expect(panel.getByText(/Super admin: bisa pasang batas runtime/)).toBeVisible()

      // Akun dengan aturan IT: peringatan, TANPA form.
      await panel.getByRole('button', { name: 'Rincian akun linux-qa-aturan-it', exact: true }).click()
      await expect(panel.getByText(/aturan systemd dari luar ComputeHub \(50-MemoryMax\.conf\)/)).toBeVisible()
      await expect(panel.getByTestId('linux-editor-1013')).toHaveCount(0)
      await expect(panel.getByText('aturan IT', { exact: true })).toBeVisible()

      // Akun bebas: form ada, tombol terkunci sampai username diketik ulang persis.
      await panel.getByRole('button', { name: 'Rincian akun linux-qa-utama', exact: true }).click()
      const editor = panel.getByTestId('linux-editor-1015')
      const pasang = editor.getByRole('button', { name: 'Pasang batas runtime', exact: true })
      await expect(pasang).toBeDisabled()
      await editor.getByLabel('Kuota CPU (core)').fill('2')
      await editor.getByLabel('RAM maksimum (GiB)').fill('8')
      await editor.getByLabel(/Ketik ulang nama akun/).fill('salah')
      await expect(pasang).toBeDisabled()
      await editor.getByLabel(/Ketik ulang nama akun/).fill('linux-qa-utama')
      await expect(pasang).toBeEnabled()
      page.once('dialog', (d) => d.accept())
      await pasang.click()
      await expect(panel.getByRole('status')).toContainText(/dipasang.*Hilang saat server reboot/)
      expect(writes).toHaveLength(1)
      expect(writes[0].method).toBe('PUT')
      expect(writes[0].url).toMatch(/\/linux-accounts\/1015\/limits$/)
      expect(writes[0].body).toEqual({ cpu_cores: 2, memory_high_bytes: null, memory_max_bytes: 8 * 1024 ** 3, confirm_username: 'linux-qa-utama' })

      // Kembalikan hanya aktif bila ComputeHub yang memasang.
      await expect(editor.getByRole('button', { name: 'Kembalikan ke aturan sistem', exact: true })).toBeDisabled()
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })
})

test.describe('Panel Akun Linux baca-saja', () => {
  test('TC-LINUX-UI-01 pewarisan, pencarian, pembaruan, desktop dan mobile', async ({ page }, testInfo) => {
    let cpuCores = 1.5
    let reads = 0
    await page.clock.install()
    await page.route('**/api/v1/admin/linux-accounts/limits', async (route) => {
      expect(route.request().method()).toBe('GET')
      reads += 1
      await route.fulfill({ json: snapshot(cpuCores) })
    })
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    const panel = page.getByRole('region', { name: 'Akun Linux', exact: true })
    await expect(panel.getByText('Baca saja', { exact: true })).toBeVisible()
    await expect(panel.getByText('1,5 core', { exact: true })).toBeVisible()
    await expect(panel.getByText('Dibatasi induk', { exact: true })).toBeVisible()
    await expect(panel.locator('input[type="number"]')).toHaveCount(0)
    await expect(panel.getByRole('button', { name: /simpan|hapus|terapkan/i })).toHaveCount(0)
    await panel.getByRole('button', { name: 'Rincian akun linux-qa-utama', exact: true }).click()
    await expect(panel.locator('dl > div').filter({ hasText: 'Sumber Kuota CPU' })).toContainText('/user.slice')
    await expect(panel.getByText('Nilai lokal: 4 core', { exact: true })).toBeVisible()
    const search = panel.getByRole('searchbox', { name: 'Akun / UID', exact: true })

    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport)
      await page.evaluate((dark) => document.documentElement.classList.toggle('dark', dark), viewport.width < 500)
      await panel.scrollIntoViewIfNeeded()
      await expect(panel.getByRole('heading', { name: 'Akun Linux', exact: true })).toBeVisible()
      expect((await search.boundingBox())?.width).toBeGreaterThan(200)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      const imagePath = testInfo.outputPath(`linux-${viewport.width}.png`)
      await panel.screenshot({ path: imagePath })
      await testInfo.attach(`linux-${viewport.width}`, { path: imagePath, contentType: 'image/png' })
    }

    await page.setViewportSize({ width: 1440, height: 900 })
    await search.fill('1016')
    await expect(panel.getByRole('button', { name: 'Rincian akun linux-qa-utama', exact: true })).toHaveCount(0)
    await expect(panel.getByText('Belum terbaca', { exact: true })).toHaveCount(4)
    await search.fill('')
    await panel.getByRole('combobox', { name: 'Status slice', exact: true }).selectOption('active')
    await expect(panel.getByRole('button', { name: 'Rincian akun linux-qa-tidak-aktif', exact: true })).toHaveCount(0)

    cpuCores = 3
    await panel.getByRole('button', { name: 'Segarkan batas Linux', exact: true }).click()
    await expect(panel.getByText('3 core', { exact: true })).toBeVisible()
    const beforePolling = reads
    cpuCores = 2
    await page.clock.fastForward(31_000)
    await expect(panel.getByText('2 core', { exact: true })).toBeVisible()
    expect(reads).toBeGreaterThan(beforePolling)
    await expectNoFatalError(page)
  })

  test('TC-LINUX-UI-02 pembaca gagal tidak menghasilkan batas palsu', async ({ page }) => {
    await page.route('**/api/v1/admin/linux-accounts/limits', (route) => route.fulfill({
      json: { ...snapshot(), available: false, reason: 'reader_unavailable', users: [] },
    }))
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    const panel = page.getByRole('region', { name: 'Akun Linux', exact: true })
    await expect(panel.getByRole('status')).toContainText('Pembaca batas Linux belum tersedia')
    await expect(panel.getByRole('table')).toHaveCount(0)
    await expect(panel.getByText('Tanpa batas', { exact: true })).toHaveCount(0)
  })
})