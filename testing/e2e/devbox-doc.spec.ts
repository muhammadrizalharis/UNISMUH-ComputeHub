import { test, expect } from '@playwright/test'

import { ADMIN_STATE, BASE_URL, STUDENT_STATE } from '../utils/constants'
import { shot } from '../utils/helpers'

/**
 * Dokumentasi & pemantauan Devbox (Fase 3):
 *  - Bagian Devbox tampil di halaman Bantuan untuk mahasiswa.
 *  - Panel "Devbox VS Code Aktif" tampil di halaman Admin.
 * Hanya membaca UI — tidak menyalakan devbox, jadi tidak memakai GPU.
 */

test.describe('Dokumentasi & panel Devbox', () => {
  test('TC-DEVBOXDOC-01 bagian Devbox ada di halaman Bantuan', async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: STUDENT_STATE })
    const page = await ctx.newPage()
    await page.goto(`${BASE_URL}/bantuan`, { waitUntil: 'domcontentloaded' })

    const judul = page.getByText(/Devbox — ngoding di VS Code sendiri/i).first()
    await expect(judul).toBeVisible({ timeout: 15000 })
    await judul.scrollIntoViewIfNeeded()

    // Poin penting yang tidak boleh hilang: lintas OS, login sekali, dan aturan mati otomatis.
    await expect(page.getByText(/vscode\.dev/i).first()).toBeVisible()
    await expect(page.getByText(/mati otomatis/i).first()).toBeVisible()
    await expect(page.getByText(/memotong kuota GPU harian/i).first()).toBeVisible()

    await shot(page, 'devbox', 'bantuan')
    await ctx.close()
  })

  test('TC-DEVBOXDOC-02 panel devbox tampil di halaman Admin', async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: ADMIN_STATE })
    const page = await ctx.newPage()
    await page.goto(`${BASE_URL}/admin`, { waitUntil: 'domcontentloaded' })

    const judul = page.getByRole('heading', { name: /Devbox VS Code Aktif/i })
    await expect(judul).toBeVisible({ timeout: 20000 })
    await judul.scrollIntoViewIfNeeded()

    // Tanpa devbox menyala, panel menjelaskan keadaan kosong (bukan tabel kosong membingungkan).
    await expect(
      page.getByText(/Tidak ada devbox yang menyala|devbox menyala/i).first(),
    ).toBeVisible()

    await shot(page, 'devbox', 'admin-panel')
    await ctx.close()
  })
})
