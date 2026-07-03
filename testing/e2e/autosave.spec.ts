import { test, expect } from '@playwright/test'

import { API_PREFIX, ADMIN_STATE } from '../utils/constants'
import { tokenFromState, shot, waitForShell } from '../utils/helpers'
import { expectNoFatalError } from '../pages/pages'

/**
 * AUTO-SAVE notebook (#5) ke /persist (fitur baru). Debounce 8 dtk -> _autosave/paste.ipynb.
 * Non-destruktif: isi autosave yang sudah ada DI-BACKUP lalu DIKEMBALIKAN (atau dihapus bila
 * tadinya tak ada) di akhir — tidak merusak scratchpad nyata pemilik akun.
 */

const AUTOSAVE_PATH = '_autosave/paste.ipynb'

test.describe('Auto-save notebook (/persist)', () => {
  test('TC-AUTOSAVE-01 Ketik di Tempel Kode → tersimpan otomatis ke _autosave/paste.ipynb', async ({
    page,
    request,
  }, testInfo) => {
    test.setTimeout(120_000) // debounce 8 dtk + polling + slowMo

    const tok = tokenFromState(ADMIN_STATE)
    const auth = { Authorization: `Bearer ${tok}` }
    const fileUrl = `${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(AUTOSAVE_PATH)}`

    // Backup isi autosave yang mungkin sudah ada (jangan rusak kerja nyata pemilik akun).
    const before = await request.get(fileUrl, { headers: auth })
    const hadPrev = before.status() === 200
    const prevContent = hadPrev ? ((await before.json()).content as string) : null

    try {
      await page.goto('/submit/code', { waitUntil: 'domcontentloaded' })
      await waitForShell(page)

      // Editor Monaco siap (loader dari CDN bisa perlu waktu).
      const editor = page.locator('.monaco-editor').first()
      await editor.waitFor({ state: 'visible', timeout: 20_000 })
      await editor.click()

      const marker = `QA_AUTOSAVE_${Date.now()}`
      await page.keyboard.type(`# ${marker}\n`)
      await shot(page, 'autosave', 'typed', testInfo)

      // Indikator "✓ tersimpan <jam>" muncul setelah debounce (soft: bukti utama = file).
      await expect
        .soft(page.getByText(/tersimpan/i).first(), 'indikator tersimpan tampil')
        .toBeVisible({ timeout: 20_000 })
      await shot(page, 'autosave', 'saved-indicator', testInfo)

      // Bukti utama: file _autosave/paste.ipynb berisi marker yang diketik (via API).
      await expect
        .poll(
          async () => {
            const r = await request.get(fileUrl, { headers: auth })
            if (r.status() !== 200) return ''
            return (await r.json()).content as string
          },
          { timeout: 20_000, message: 'file autosave berisi marker' },
        )
        .toContain(marker)

      await expectNoFatalError(page)
    } finally {
      // Kembalikan isi semula (atau hapus bila tadinya tak ada) → non-destruktif.
      if (hadPrev && prevContent !== null) {
        await request.put(`${API_PREFIX}/interactive/workspace/file`, {
          headers: auth,
          data: { path: AUTOSAVE_PATH, content: prevContent },
        })
      } else {
        await request.delete(fileUrl, { headers: auth })
      }
    }
  })
})
