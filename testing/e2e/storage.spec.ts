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
    uploads: [] as { path: string; first: boolean; reset: boolean; size: number; text: string | null }[],
    directories: [] as string[],
    stored: new Map<string, 'dir' | 'file'>(),
    failUploadOnce: false,
    uploadGate: null as Promise<void> | null,
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
    localStorage.removeItem('unismuh_token')
    localStorage.removeItem('unismuh_refresh')
    sessionStorage.clear()
    sessionStorage.setItem('unismuh_token', 'qa-directory-only')
  })
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const endpoint = url.pathname.replace('/api/v1', '')
    let payload: unknown = {}
    if (endpoint === '/auth/me') {
      payload = { id: 999942, name: 'QA Workspace', username: 'qa-workspace', email: 'qa@example.invalid', role: 'dosen', is_active: true, is_superadmin: false }
    } else if (endpoint === '/interactive/workspace/folder/chunk') {
      const name = url.searchParams.get('path') ?? ''
      const body = route.request().postDataBuffer() ?? Buffer.alloc(0)
      state.uploads.push({ path: name, first: url.searchParams.get('first') === '1', reset: url.searchParams.get('reset') === '1', size: body.length, text: body.length < 1024 ? body.toString('utf8') : null })
      if (state.uploadGate) await state.uploadGate
      if (state.failUploadOnce) {
        state.failUploadOnce = false
        await route.fulfill({ status: 503, json: { detail: 'Gagal unggah uji.' } })
        return
      }
      state.stored.set(name, 'file')
      payload = { ok: true, path: name }
    } else if (endpoint === '/interactive/workspace/mkdir') {
      const name = route.request().postDataJSON().path as string
      state.directories.push(name)
      state.stored.set(name, 'dir')
      payload = { path: name }
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
      const prefix = folder ? `${folder}/` : ''
      for (const [storedPath, kind] of state.stored) {
        if (!storedPath.startsWith(prefix)) continue
        const relative = storedPath.slice(prefix.length)
        if (!relative) continue
        const name = relative.split('/')[0]
        if (!items.some((item) => item.name === name))
          items.push(relative.includes('/') || kind === 'dir' ? directory(name, folder) : file(name, folder))
      }
      if (state.stored.size)
        items.sort((left, right) => Number(left.type === 'file') - Number(right.type === 'file') || left.name.localeCompare(right.name))
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

type DropFixture = {
  name: string
  content?: string
  bytes?: number
  reportedSize?: number
  entries?: DropFixture[]
  unreadable?: boolean
}

async function dispatchWorkspaceDrop(page: Page, selector: string, fixtures: DropFixture[], eventType = 'drop') {
  await page.locator(selector).evaluate((element, data) => {
    const transfer = new DataTransfer()
    const makeFile = (fixture: DropFixture) => {
      const contents = fixture.bytes ? new Uint8Array(fixture.bytes) : fixture.content ?? ''
      const file = new File([contents], fixture.name)
      if (fixture.reportedSize) Object.defineProperty(file, 'size', { value: fixture.reportedSize })
      return file
    }
    const makeEntry = (fixture: DropFixture): object => ({
      name: fixture.name,
      isFile: fixture.entries === undefined,
      isDirectory: fixture.entries !== undefined,
      file: (resolve: (file: File) => void, reject: (error: Error) => void) => {
        if (fixture.unreadable) reject(new Error('Berkas tidak dapat dibaca.'))
        else resolve(makeFile(fixture))
      },
      createReader: () => {
        let offset = 0
        return {
          readEntries: (resolve: (entries: object[]) => void) => {
            const batch = (fixture.entries ?? []).slice(offset, offset + 100)
            offset += 100
            resolve(batch.map(makeEntry))
          },
        }
      },
    })
    transfer.items.add(new File([''], 'drop-placeholder'))
    Object.defineProperty(transfer, 'items', {
      value: data.fixtures.map((fixture) => ({
        kind: 'file',
        getAsFile: () => fixture.entries === undefined ? makeFile(fixture) : null,
        webkitGetAsEntry: () => makeEntry(fixture),
      })),
    })
    element.dispatchEvent(new DragEvent(data.eventType, { bubbles: true, cancelable: true, dataTransfer: transfer }))
  }, { fixtures, eventType })
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

test.describe('Penyimpanan drag-and-drop dan panel fleksibel', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('TC-STO-10 drop campuran folder multi-batch, subfolder, dan file ke folder tujuan', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    const state = await mockWorkspaceDirectory(page)
    await page.goto(storageTestUrl('/storage'))
    await expect(page.getByTitle('phd_project', { exact: true })).toBeVisible()
    const fixtures: DropFixture[] = [
      { name: 'notes.txt', content: 'catatan' },
      { name: 'bundle', entries: [
        ...Array.from({ length: 101 }, (_, index) => ({ name: `item-${index}.txt`, content: `${index}` })),
        { name: 'code', entries: [{ name: 'main.py', content: 'print(42)' }] },
        { name: 'empty', entries: [] },
        { name: 'empty.txt', content: '' },
      ] },
    ]
    await dispatchWorkspaceDrop(page, 'button[title="phd_project"]', fixtures, 'dragover')
    await expect(page.getByRole('status')).toContainText('Unggah ke phd_project')
    await shot(page, 'storage', 'drop-target-folder', testInfo)
    await dispatchWorkspaceDrop(page, 'button[title="phd_project"]', fixtures)
    await expect.poll(() => state.uploads.length).toBe(104)
    await expect(page.getByRole('progressbar', { name: 'Progres unggahan' })).toHaveCount(0)
    expect(state.directories).toEqual(['phd_project/bundle/empty'])
    expect(state.uploads.find((item) => item.path.endsWith('/code/main.py'))?.text).toBe('print(42)')
    expect(state.uploads.find((item) => item.path.endsWith('/empty.txt'))?.size).toBe(0)
    expect(state.uploads.filter((item) => item.reset)).toHaveLength(1)
    expect(state.uploads.every((item) => item.path.startsWith('phd_project/'))).toBe(true)
    await page.getByTitle('phd_project/bundle', { exact: true }).click()
    await expect(page.getByTitle('phd_project/bundle/empty', { exact: true })).toBeVisible()
    await page.getByTitle('phd_project/bundle/code', { exact: true }).click()
    await expect(page.getByTitle('phd_project/bundle/code/main.py', { exact: true })).toBeVisible()
    await shot(page, 'storage', 'dropped-folder-complete', testInfo)
    expect(cap.pageErrors).toEqual([])
  })

  test('TC-STO-11 drop file besar memakai potongan dan menolak unggahan bersamaan', async ({ page }) => {
    const state = await mockWorkspaceDirectory(page)
    let releaseUpload = () => {}
    state.uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve })
    await page.goto(storageTestUrl('/storage'))
    await expect(page.getByTitle('phd_project', { exact: true })).toBeVisible()
    try {
      await dispatchWorkspaceDrop(page, '[data-testid="storage-dropzone"]', [{ name: 'large.bin', bytes: 25 * 1024 * 1024 + 3 }])
      await expect.poll(() => state.uploads.length).toBe(1)
      await expect(page.getByRole('button', { name: 'Unggah Folder', exact: true })).toBeDisabled()
      await expect(page.getByRole('progressbar', { name: 'Progres unggahan' })).toBeVisible()
      await dispatchWorkspaceDrop(page, '[data-testid="storage-dropzone"]', [{ name: 'duplicate.txt', content: 'tidak boleh terkirim' }])
      expect(state.uploads).toHaveLength(1)
    } finally {
      releaseUpload()
    }
    await expect.poll(() => state.uploads.length).toBe(2)
    await expect(page.getByRole('progressbar', { name: 'Progres unggahan' })).toHaveCount(0)
    expect(state.uploads.map(({ path: name, first, reset, size }) => ({ name, first, reset, size }))).toEqual([
      { name: 'large.bin', first: true, reset: true, size: 24 * 1024 * 1024 },
      { name: 'large.bin', first: false, reset: false, size: 1024 * 1024 + 3 },
    ])
  })

  test('TC-STO-12 galat baca, batas file, dan kegagalan unggah tidak mengunci halaman', async ({ page }) => {
    const cap = captureConsole(page)
    const state = await mockWorkspaceDirectory(page)
    await page.goto(storageTestUrl('/storage'))
    await expect(page.getByTitle('phd_project', { exact: true })).toBeVisible()
    await dispatchWorkspaceDrop(page, '[data-testid="storage-dropzone"]', [{ name: 'denied.txt', unreadable: true }])
    await expect(page.getByRole('alert')).toContainText('Berkas tidak dapat dibaca.')
    expect(state.uploads).toHaveLength(0)
    await dispatchWorkspaceDrop(page, '[data-testid="storage-dropzone"]', [{ name: 'oversized.bin', reportedSize: 256 * 1024 * 1024 + 1 }])
    await expect(page.getByRole('alert')).toContainText('melebihi batas 256 MB')
    expect(state.uploads).toHaveLength(0)
    state.failUploadOnce = true
    await dispatchWorkspaceDrop(page, '[data-testid="storage-dropzone"]', [{ name: 'retry.txt', content: 'coba' }])
    await expect(page.getByRole('alert')).toContainText('Gagal unggah uji.')
    await expect(page.getByRole('button', { name: 'Unggah Folder', exact: true })).toBeEnabled()
    await dispatchWorkspaceDrop(page, '[data-testid="storage-dropzone"]', [{ name: 'retry.txt', content: 'berhasil' }])
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect.poll(() => state.uploads.at(-1)?.text).toBe('berhasil')
    await expect(page.getByRole('progressbar', { name: 'Progres unggahan' })).toHaveCount(0)
    expect(cap.pageErrors).toEqual([])
  })

  test('TC-STO-13 panel bisa dilebarkan, diperkecil, diingat, dan aman di mobile', async ({ page }, testInfo) => {
    const cap = captureConsole(page)
    await mockWorkspaceDirectory(page)
    await page.goto(storageTestUrl('/storage'))
    const separator = page.getByRole('separator', { name: 'Lebar panel folder' })
    await expect(separator).toBeVisible()
    const start = await separator.boundingBox()
    expect(start).not.toBeNull()
    const oldWidth = Number(await separator.getAttribute('aria-valuenow'))
    await page.mouse.move(start!.x + start!.width / 2, start!.y + start!.height / 2)
    await page.mouse.down()
    await page.mouse.move(start!.x + start!.width / 2 + 150, start!.y + start!.height / 2, { steps: 5 })
    await page.mouse.up()
    await expect(separator).toHaveAttribute('aria-valuenow', String(oldWidth + 150))
    await separator.focus()
    await separator.press('ArrowLeft')
    await expect(separator).toHaveAttribute('aria-valuenow', String(oldWidth + 130))
    await page.reload()
    await expect(separator).toHaveAttribute('aria-valuenow', String(oldWidth + 130))
    await separator.press('End')
    expect((await page.locator('#storage-preview').boundingBox())!.width).toBeGreaterThanOrEqual(339)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await shot(page, 'storage', 'resized-desktop', testInfo)
    await separator.press('Home')
    await expect(separator).toHaveAttribute('aria-valuenow', '220')
    await separator.dblclick()
    await expect(separator).toHaveAttribute('aria-valuenow', '300')
    await page.evaluate(() => document.documentElement.classList.add('dark'))
    for (const width of [390, 820]) {
      await page.setViewportSize({ width, height: 844 })
      await expect(separator).toBeHidden()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
      await expect(page.getByTitle('phd_project', { exact: true })).toBeVisible()
      await shot(page, 'storage', `drop-resize-${width}`, testInfo)
    }
    expect(cap.pageErrors).toEqual([])
  })
})

test('TC-STO-14 unggah seret-lepas melalui API nyata pada folder QA sendiri', async ({ page, request }, testInfo) => {
  const token = tokenFromState(ADMIN_STATE)
  const headers = { Authorization: `Bearer ${token}` }
  const folder = `000_QA_DROP_${Date.now()}`
  const created = await request.post(`${API_PREFIX}/interactive/workspace/mkdir`, { headers, data: { path: folder } })
  expect(created.status()).toBe(200)
  try {
    await page.addInitScript((accessToken) => {
      sessionStorage.setItem('unismuh_token', accessToken)
    }, token)
    await page.goto(storageTestUrl('/storage'))
    await expect(page.getByTitle(folder, { exact: true })).toBeVisible()
    await page.getByTitle(folder, { exact: true }).evaluate((element) => {
      const transfer = new DataTransfer()
      transfer.items.add(new File(['unggahan seret-lepas QA\n'], 'note.txt', { type: 'text/plain' }))
      element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }))
    })
    await expect(page.getByTitle(`${folder}/note.txt`, { exact: true })).toBeVisible()
    await dispatchWorkspaceDrop(page, `button[title="${folder}"]`, [{
      name: 'nested', entries: [
        { name: 'data', entries: [{ name: 'sample.txt', content: 'QA nested' }] },
        { name: 'empty', entries: [] },
      ],
    }])
    await expect(page.getByRole('progressbar', { name: 'Progres unggahan' })).toHaveCount(0)
    for (const [relative, content] of [['note.txt', 'unggahan seret-lepas QA\n'], ['nested/data/sample.txt', 'QA nested']]) {
      const read = await request.get(`${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(`${folder}/${relative}`)}`, { headers })
      expect(read.status()).toBe(200)
      expect((await read.json()).content).toBe(content)
    }
    const empty = await request.get(`${API_PREFIX}/interactive/workspace/directory?path=${encodeURIComponent(`${folder}/nested/empty`)}`, { headers })
    expect(empty.status()).toBe(200)
    expect((await empty.json()).children).toEqual([])
    await shot(page, 'storage', 'live-drop-qa', testInfo)
  } finally {
    const removed = await request.delete(`${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(folder)}`, { headers })
    expect([204, 404]).toContain(removed.status())
  }
})
