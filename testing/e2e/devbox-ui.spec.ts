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
})
