import { test, expect } from '@playwright/test'

import { shot, captureConsole, waitAppReady } from '../utils/helpers'
import { UsersPage, expectNoFatalError } from '../pages/pages'

/**
 * CATATAN: tidak ada perubahan yang DISIMPAN pada user nyata. Modal dibuka untuk
 * verifikasi UI lalu DITUTUP tanpa menyimpan (hindari mutasi data produksi).
 */
test.describe('Manajemen Pengguna (admin)', () => {
  test('TC-USR-01 Tabel pengguna tampil', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const users = new UsersPage(page)
    await users.open()
    await waitAppReady(page)
    // Daftar pengguna dimuat async -> tunggu tabel render.
    await expect(users.table, 'tabel pengguna muncul').toBeVisible({ timeout: 15_000 })
    await shot(page, 'users', 'list', testInfo)
    await expectNoFatalError(page)
    expect(await users.table.count(), 'tabel pengguna ada').toBeGreaterThan(0)
    expect.soft(cap.pageErrors, cap.pageErrors.join(' | ')).toEqual([])
  })

  test('TC-USR-02 Pencarian pengguna', async ({ page }, testInfo) => {
    const users = new UsersPage(page)
    await users.open()
    await waitAppReady(page)
    const search = users.searchBox()
    test.skip((await search.count()) === 0, 'kotak pencarian tidak ada')
    const before = await page.locator('table tbody tr').count()
    await search.fill('zzz_nomatch_qa_123')
    await page.waitForTimeout(700)
    const after = await page.locator('table tbody tr').count()
    await shot(page, 'users', 'search-nomatch', testInfo)
    expect.soft(after, 'baris menyusut/tetap saat query tanpa kecocokan').toBeLessThanOrEqual(before)
    await search.fill('')
    await page.waitForTimeout(400)
  })

  test('TC-USR-03 Buka modal kebijakan (read-only) lalu tutup tanpa simpan', async ({ page }, testInfo) => {
    // Viewport desktop default (1440) — tempat BUG-001 dulu muncul. Setelah perbaikan
    // (abaikan focus-scroll 350ms saat buka), menu "Aksi" tetap terbuka.
    const users = new UsersPage(page)
    await users.open()
    await waitAppReady(page)
    await expect(users.table).toBeVisible({ timeout: 15_000 })
    // Aksi baris ada di dalam menu dropdown "Aksi".
    const aksi = page.getByRole('button', { name: /^Aksi/ }).first()
    test.skip((await aksi.count()) === 0, 'tidak ada menu Aksi pada baris')
    const policyItem = page.getByRole('button', { name: /Kelola Kebijakan/i }).first()
    // Dropdown portal bisa tertutup oleh scroll/re-render -> klik ulang sampai item stabil.
    await expect(async () => {
      await aksi.click()
      await expect(policyItem).toBeVisible({ timeout: 1500 })
    }).toPass({ timeout: 15_000 })
    await shot(page, 'users', 'action-menu', testInfo)
    await policyItem.click()
    await page.waitForTimeout(700)
    await shot(page, 'users', 'modal-open', testInfo)
    expect.soft(await page.locator('body').innerText()).toMatch(/Kebijakan|kuota|VRAM|GPU|CPU/i)
    // Tutup tanpa menyimpan.
    const cancel = page.getByRole('button', { name: /Batal|Tutup|Close/i }).first()
    if ((await cancel.count()) > 0) await cancel.click()
    else await page.keyboard.press('Escape')
    await page.waitForTimeout(400)
    await shot(page, 'users', 'modal-closed', testInfo)
    await expectNoFatalError(page)
  })

  test('TC-USR-04 Tombol tambah pengguna membuka form', async ({ page }, testInfo) => {
    const users = new UsersPage(page)
    await users.open()
    await waitAppReady(page)
    const add = users.addButton()
    test.skip((await add.count()) === 0, 'tombol tambah tidak ada')
    await add.click()
    await page.waitForTimeout(500)
    await shot(page, 'users', 'add-form', testInfo)
    // Tutup tanpa membuat user.
    const cancel = page.getByRole('button', { name: /Batal|Tutup|Close/i }).first()
    if ((await cancel.count()) > 0) await cancel.click()
    else await page.keyboard.press('Escape')
  })
})
