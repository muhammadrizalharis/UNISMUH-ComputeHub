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

  test('TC-STO-04 API unduh SELURUH workspace sebagai .zip', async ({ request }) => {
    const token = tokenFromState(ADMIN_STATE)
    const res = await request.get(
      `${API_PREFIX}/interactive/workspace/download-folder?path=`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(res.status(), 'HTTP 200').toBe(200)
    expect(res.headers()['content-type'] || '', 'content-type zip').toMatch(/zip/i)
    expect(res.headers()['content-disposition'] || '', 'nama workspace.zip').toMatch(
      /workspace\.zip/i,
    )
    const body = await res.body()
    expect(body.length, 'zip tidak kosong').toBeGreaterThan(20)
    expect(body.subarray(0, 2).toString('latin1'), 'magic bytes PK (ZIP)').toBe('PK')
  })

  test('TC-STO-05 API unduh FOLDER tertentu sebagai .zip (buat → unduh → bersihkan)', async ({
    request,
  }) => {
    const token = tokenFromState(ADMIN_STATE)
    const auth = { Authorization: `Bearer ${token}` }
    const folder = `qa_dl_${Date.now()}`
    const filePath = `${folder}/marker.txt`
    const put = await request.put(`${API_PREFIX}/interactive/workspace/file`, {
      headers: { ...auth, 'Content-Type': 'application/json' },
      data: { path: filePath, content: 'QA folder-download marker\n' },
    })
    expect([200, 201], 'file di subfolder dibuat').toContain(put.status())
    try {
      const res = await request.get(
        `${API_PREFIX}/interactive/workspace/download-folder?path=${encodeURIComponent(folder)}`,
        { headers: auth },
      )
      expect(res.status(), 'HTTP 200').toBe(200)
      expect(res.headers()['content-type'] || '', 'content-type zip').toMatch(/zip/i)
      expect(res.headers()['content-disposition'] || '', 'nama <folder>.zip').toMatch(
        new RegExp(`${folder}\\.zip`, 'i'),
      )
      const body = await res.body()
      expect(body.subarray(0, 2).toString('latin1'), 'magic bytes PK (ZIP)').toBe('PK')
      expect(body.length, 'zip berisi data').toBeGreaterThan(20)
    } finally {
      const del = await request.delete(
        `${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(folder)}`,
        { headers: auth },
      )
      expect.soft([200, 204, 404]).toContain(del.status())
    }
  })

  test('TC-STO-06 UI tombol "Unduh semua" memicu unduhan .zip', async ({
    page,
    request,
  }, testInfo) => {
    const token = tokenFromState(ADMIN_STATE)
    const auth = { Authorization: `Bearer ${token}` }
    // Pastikan workspace tidak kosong agar tombol "Unduh semua" aktif (bukan disabled).
    const marker = `qa_dlui_${Date.now()}.txt`
    await request.put(`${API_PREFIX}/interactive/workspace/file`, {
      headers: { ...auth, 'Content-Type': 'application/json' },
      data: { path: marker, content: 'marker unduh-semua\n' },
    })
    try {
      const sto = new StoragePage(page)
      await sto.open()
      await waitAppReady(page)
      const btn = page.getByRole('button', { name: /Unduh semua/i }).first()
      await expect(btn, 'tombol Unduh semua tampil').toBeVisible()
      await expect(btn, 'tombol Unduh semua aktif').toBeEnabled()
      const dlPromise = page
        .waitForEvent('download', { timeout: 15_000 })
        .catch(() => null)
      await btn.click()
      const dl = await dlPromise
      await shot(page, 'storage', 'download-all', testInfo)
      await expectNoFatalError(page)
      expect(dl, 'event unduhan terpicu').not.toBeNull()
      if (dl) expect(dl.suggestedFilename(), 'berkas .zip').toMatch(/\.zip$/i)
    } finally {
      await request.delete(
        `${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(marker)}`,
        { headers: auth },
      )
    }
  })
})
