import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test, expect, type Page } from '@playwright/test'

import { API_PREFIX, ADMIN_STATE } from '../utils/constants'
import { shot, captureConsole, waitAppReady, tokenFromState } from '../utils/helpers'
import { StoragePage, expectNoFatalError } from '../pages/pages'

const QA_NAME = `QA_TEST_${Date.now()}.txt`

async function mockWorkspaceDirectory(page: Page) {
  const state = {
    failProjectOnce: false,
    extraRoot: false,
    requests: [] as { path: string; offset: number }[],
  }
  const directory = (name: string, parent = '') => ({
    name, path: parent ? `${parent}/${name}` : name, type: 'dir', children: [],
  })
  const file = (name: string, parent = '') => ({
    name, path: parent ? `${parent}/${name}` : name, type: 'file', size: 12,
  })
  const root = () => [
    ...(state.extraRoot ? [directory('added_after_refresh')] : []),
    directory('final_goal'), directory('phd_project'),
    ...Array.from({ length: 205 }, (_, index) => file(`root-${String(index).padStart(5, '0')}.txt`)),
  ]
  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
    sessionStorage.setItem('unismuh_token', 'qa-directory-only')
  })
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const endpoint = url.pathname.replace('/api/v1', '')
    let payload: unknown = {}
    if (endpoint === '/auth/me') {
      payload = { id: 999942, name: 'QA Workspace', username: 'qa-workspace', email: 'qa@example.invalid', role: 'dosen', is_active: true, is_superadmin: false }
    } else if (endpoint === '/interactive/workspace/directory') {
      const folder = url.searchParams.get('path') ?? ''
      const offset = Number(url.searchParams.get('offset') ?? 0)
      state.requests.push({ path: folder, offset })
      if (folder === 'phd_project' && state.failProjectOnce) {
        state.failProjectOnce = false
        await route.fulfill({ status: 503, json: { detail: 'Folder sementara tidak dapat dibaca.' } })
        return
      }
      const items = folder === '' ? root()
        : folder === 'final_goal' ? Array.from({ length: 4005 }, (_, index) => file(`sample-${String(index).padStart(5, '0')}.txt`, folder))
          : folder === 'phd_project' ? [directory('code', folder)]
            : folder === 'phd_project/code' ? [file('analysis.py', folder)] : []
      const next = offset + 200
      payload = { name: folder.split('/').pop() || 'workspace', path: folder, type: 'dir', children: items.slice(offset, next), next_offset: next < items.length ? next : null }
    } else if (endpoint === '/interactive/workspace') {
      payload = { tree: { name: 'workspace', path: '', type: 'dir', children: root().slice(0, 200), next_offset: 200 }, usage: { bytes: 1024, files: 4211 }, quota_mb: 51200 }
    } else if (endpoint === '/interactive/workspace/trash') {
      payload = { items: [], retention_days: 7 }
    } else if (endpoint === '/interactive/workspace/file') {
      payload = { path: url.searchParams.get('path'), content: 'print("workspace visible")', language: 'python', truncated: false }
    } else if (endpoint === '/system/capabilities') {
      payload = { python_versions: ['3.10'], python_default: '3.10', policy: {} }
    } else if (endpoint === '/system/announcement') {
      payload = { text: '', level: 'info', maintenance: false }
    } else if (endpoint.startsWith('/notifications')) {
      payload = []
    }
    await route.fulfill({ json: payload })
  })
  return state
}

function storageTestUrl(route: string) {
  return process.env.STORAGE_UI_URL ? new URL(route, process.env.STORAGE_UI_URL).href : route
}

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

test.describe('Penyimpanan tanpa batas total item', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('TC-STO-07 semua 4005 berkas dan folder saudara dapat dijangkau', async ({ page }, testInfo) => {
    test.setTimeout(120000)
    const cap = captureConsole(page)
    const state = await mockWorkspaceDirectory(page)
    await page.goto(storageTestUrl('/storage'))
    await expect(page.getByTitle('phd_project', { exact: true })).toBeVisible()
    expect(state.requests.every((request) => request.path === '')).toBe(true)

    await page.getByTitle('phd_project', { exact: true }).click()
    await page.getByTitle('phd_project/code', { exact: true }).click()
    const read = page.waitForResponse((response) => response.url().includes('/workspace/file?path='))
    await page.getByTitle('phd_project/code/analysis.py', { exact: true }).click()
    expect((await read).status()).toBe(200)
    await page.getByTitle('phd_project', { exact: true }).click()

    await page.getByTitle('final_goal', { exact: true }).click()
    for (let offset = 200; offset <= 4000; offset += 200) {
      const lastName = `final_goal/sample-${String(offset - 1).padStart(5, '0')}.txt`
      await page.getByTitle(lastName, { exact: true }).scrollIntoViewIfNeeded()
      await expect.poll(() => state.requests.some((request) => request.path === 'final_goal' && request.offset === offset)).toBe(true)
    }
    await page.getByTitle('final_goal/sample-04004.txt', { exact: true }).scrollIntoViewIfNeeded()
    await expect(page.getByTitle('final_goal/sample-04004.txt', { exact: true })).toBeVisible()
    await expect(page.locator('[data-workspace-directory="final_goal"] button[title^="final_goal/sample-"]')).toHaveCount(4005)
    await shot(page, 'storage', 'all-items-last-page', testInfo)
    await page.getByTitle('final_goal', { exact: true }).click()
    await page.getByRole('button', { name: 'Muat berikutnya', exact: true }).scrollIntoViewIfNeeded()
    await expect.poll(() => state.requests.some((request) => request.path === '' && request.offset === 200)).toBe(true)
    await expect(page.getByTitle('root-00204.txt', { exact: true })).toBeAttached()
    expect(cap.pageErrors).toEqual([])
  })

  test('TC-STO-08 gagal muat dapat dicoba ulang dan refresh menampilkan item baru', async ({ page }, testInfo) => {
    const state = await mockWorkspaceDirectory(page)
    state.failProjectOnce = true
    await page.goto(storageTestUrl('/storage'))
    await page.getByTitle('phd_project', { exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Folder sementara tidak dapat dibaca.')
    await page.getByRole('button', { name: 'Coba lagi', exact: true }).click()
    await expect(page.getByTitle('phd_project/code', { exact: true })).toBeVisible()
    state.extraRoot = true
    await page.getByRole('button', { name: 'Segarkan', exact: true }).click()
    await expect(page.getByTitle('added_after_refresh', { exact: true })).toBeVisible()
    await shot(page, 'storage', 'directory-retry-refresh', testInfo)
  })

  test('TC-STO-09 folder besar tersedia pada mobile dan explorer notebook', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    await page.setViewportSize({ width: 390, height: 844 })
    await mockWorkspaceDirectory(page)
    await page.goto(storageTestUrl('/storage'))
    await page.getByTitle('phd_project', { exact: true }).click()
    await expect(page.getByTitle('phd_project/code', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await shot(page, 'storage', 'directory-mobile', testInfo)

    await page.goto(storageTestUrl('/submit/notebook'))
    await page.getByTitle('phd_project', { exact: true }).click()
    await page.getByTitle('phd_project/code', { exact: true }).click()
    await expect(page.getByTitle('phd_project/code/analysis.py', { exact: true })).toBeVisible()
    await shot(page, 'storage', 'notebook-directory-mobile', testInfo)
    expect(cap.pageErrors).toEqual([])
  })
})
