import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test, expect } from '@playwright/test'

import { API_PREFIX, ADMIN_STATE } from '../utils/constants'
import { shot, captureConsole, waitAppReady, tokenFromState } from '../utils/helpers'
import { StoragePage, expectNoFatalError } from '../pages/pages'

const QA_NAME = `QA_TEST_${Date.now()}.txt`

test.describe('Penyimpanan (file /persist)', () => {
  test('TC-STO-01 Halaman penyimpanan tampil + indikator kuota', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const sto = new StoragePage(page)
    await sto.open()
    await waitAppReady(page)
    await shot(page, 'storage', 'view', testInfo)
    await expectNoFatalError(page)
    const body = await page.locator('body').innerText()
    expect(body, 'menyebut kuota/penyimpanan').toMatch(/kuota|penyimpanan|MB|GB|byte/i)
    expect.soft(cap.pageErrors, cap.pageErrors.join(' | ')).toEqual([])
  })

  test('TC-STO-02 Upload file (UI) lalu bersihkan (API)', async ({ page, request }, testInfo) => {
    const sto = new StoragePage(page)
    await sto.open()
    await waitAppReady(page)

    // Siapkan file kecil sementara.
    const tmpDir = path.join(os.tmpdir(), 'qa-uploads')
    if (!existsSync(tmpDir)) mkdirSync(tmpDir, { recursive: true })
    const tmpFile = path.join(tmpDir, QA_NAME)
    writeFileSync(tmpFile, 'halo dari QA Playwright\n', 'utf-8')

    const input = sto.fileInput()
    test.skip((await input.count()) === 0, 'input file tidak tersedia di halaman ini')

    await shot(page, 'storage', 'before-upload', testInfo)
    await input.first().setInputFiles(tmpFile)
    // Tunggu daftar berkas memuat nama file QA.
    await page.waitForTimeout(2500)
    await shot(page, 'storage', 'after-upload', testInfo)

    const appeared = await page.getByText(QA_NAME, { exact: false }).count()
    expect.soft(appeared, `berkas ${QA_NAME} tampil setelah upload`).toBeGreaterThan(0)

    // Bersihkan via API (idempoten, di /persist milik akun uji sendiri).
    const token = tokenFromState(ADMIN_STATE)
    const del = await request.delete(
      `${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(QA_NAME)}`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect.soft([200, 204, 404]).toContain(del.status())
  })

  test('TC-STO-03 Tombol unggah ada & dapat diklik', async ({ page }, testInfo) => {
    const sto = new StoragePage(page)
    await sto.open()
    await waitAppReady(page)
    const btn = sto.uploadButton()
    test.skip((await btn.count()) === 0, 'tombol unggah tidak ada')
    await expect(btn).toBeVisible()
    await shot(page, 'storage', 'upload-button', testInfo)
  })
})
