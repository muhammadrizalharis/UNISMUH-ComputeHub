import { test, expect } from '@playwright/test'

import { STUDENT_STATE } from '../utils/constants'
import { shot } from '../utils/helpers'
import { expectNoFatalError } from '../pages/pages'

/**
 * UI DEVBOX — halaman "ngoding di VS Code sendiri, sumber daya server".
 *
 * NON-DESTRUKTIF: hanya membuka halaman & memeriksa tampilan awal (devbox TIDAK
 * dinyalakan di sini supaya suite tak menahan resource; alur nyala/mati diuji di
 * `api/devbox.spec.ts`). Memakai storageState mahasiswa = memastikan fitur ini
 * memang terlihat oleh mahasiswa, bukan hanya admin.
 */

test.describe('Devbox VS Code (UI)', () => {
  test('TC-DEVBOX-UI-01 menu Devbox tampil & halaman menjelaskan cara pakai', async ({
    browser,
  }, testInfo) => {
    const ctx = await browser.newContext({ storageState: STUDENT_STATE })
    const page = await ctx.newPage()
    try {
      await page.goto('/devbox', { waitUntil: 'domcontentloaded' })

      // Menu sidebar tersedia untuk mahasiswa.
      await expect(page.getByRole('link', { name: /Devbox/i }).first()).toBeVisible()

      // Judul & penjelasan inti (mengapa fitur ini ada) muncul.
      await expect(page.getByRole('heading', { level: 1 })).toContainText(/Devbox/i)
      await expect(page.getByText(/sumber daya|CPU, RAM, dan GPU/i).first()).toBeVisible()

      // Kontrol utama: tombol nyalakan saja — pilihan CPU/GPU sengaja DIHAPUS karena
      // perangkat kini ditentukan otomatis oleh server.
      const tombolNyala = page.getByRole('button', { name: /Nyalakan devbox/i })
      const sudahJalan = await page.getByText(/Menyala|Menyiapkan|Menunggu otorisasi/i).count()
      if (sudahJalan === 0) {
        await expect(tombolNyala).toBeVisible()
        await expect(page.getByRole('button', { name: /CPU saja/i })).toHaveCount(0)
        await expect(page.getByText(/GPU diberikan otomatis/i).first()).toBeVisible()
      }

      await shot(page, 'devbox', 'devbox-ui', testInfo)
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })

  test('TC-DEVBOX-UI-02 koneksi terputus dan tersambung ulang tampil di desktop dan mobile', async ({ browser }, testInfo) => {
    const ctx = await browser.newContext({ storageState: STUDENT_STATE })
    const page = await ctx.newPage()
    let connected = false
    await page.route('**/api/v1/devbox', (route) => route.fulfill({
      json: {
        user_id: 24,
        state: 'running',
        enabled: true,
        device: 'gpu',
        folder: 'CH-qastudent',
        tunnel_name: 'computehub-qa',
        client_connected: connected,
        disconnect_timeout_seconds: 120,
        disconnect_remaining_seconds: connected ? null : 65,
        idle_timeout_seconds: 1800,
        max_lifetime_seconds: 43200,
      },
    }))
    try {
      await page.goto('/devbox', { waitUntil: 'domcontentloaded' })
      for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
        await page.setViewportSize(viewport)
        await expect(page.getByText('Koneksi VS Code: Terputus', { exact: true })).toBeVisible()
        await expect(page.getByRole('status')).toContainText('65 detik')
        await expect(page.getByText(/semua koneksi VS Code terputus selama/)).toContainText('2 menit')
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
        await shot(page, 'devbox', `disconnect-${viewport.width}`, testInfo)
      }
      connected = true
      await page.getByRole('button', { name: 'Segarkan', exact: true }).click()
      await expect(page.getByText('Koneksi VS Code: Tersambung', { exact: true })).toBeVisible()
      await expect(page.getByRole('status')).toHaveCount(0)
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })
})
