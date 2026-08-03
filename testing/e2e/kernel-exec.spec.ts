import { test, expect } from '@playwright/test'

import { API_PREFIX, STUDENT_STATE } from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * NOTEBOOK INTERAKTIF END-TO-END (kernel Jupyter di container GPU).
 *
 * Menutup celah nyata: seluruh suite lain menguji REST, sedangkan eksekusi sel
 * notebook memakai WebSocket. Akibatnya kerusakan kernel pernah lolos tanpa
 * terdeteksi (mis. berkas koneksi kernel tak terlihat container setelah backend
 * dipindah ke Docker -> "Kernel didn't respond in 90 seconds").
 *
 * Alur: buat sesi (REST) -> jalankan kode lewat WebSocket dari dalam browser
 * (same-origin) -> pastikan kode benar-benar dieksekusi DI GPU -> hapus sesi.
 * Sesi selalu dibersihkan di afterAll walau uji gagal.
 */

let sessionId = ''
let token = ''

test.describe.serial('Notebook interaktif (kernel GPU)', () => {
  test.beforeAll(async ({ playwright }) => {
    token = tokenFromState(STUDENT_STATE)
    const ctx = await playwright.request.newContext()
    const res = await ctx.post(`${API_PREFIX}/interactive/sessions?source=paste`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 120_000,
    })
    // 200 = sesi baru/reuse; 202 = masuk antrian (GPU penuh) -> dilewati.
    expect([200, 201, 202], 'permintaan sesi diterima').toContain(res.status())
    const body = await res.json()
    sessionId = body.session_id ?? ''
    await ctx.dispose()
  })

  test.afterAll(async ({ playwright }) => {
    if (!sessionId) return
    const ctx = await playwright.request.newContext()
    await ctx.delete(`${API_PREFIX}/interactive/sessions/${sessionId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    await ctx.dispose()
  })

  test('TC-KERNEL-01 sel dieksekusi kernel & GPU CUDA terlihat', async ({ page }) => {
    test.skip(!sessionId, 'GPU penuh — permintaan sesi masuk antrian')
    test.setTimeout(180_000)
    await page.goto('/login', { waitUntil: 'domcontentloaded' })

    const keluaran = await page.evaluate(
      async ({ sid, tok, prefix }) => {
        const url = `${prefix.replace(/^http/, 'ws')}/interactive/ws/${sid}?token=${tok}`
        return await new Promise<string>((resolve, reject) => {
          const ws = new WebSocket(url)
          let out = ''
          const batas = setTimeout(() => {
            ws.close()
            reject(new Error(`timeout; keluaran sejauh ini: "${out}"`))
          }, 120_000)
          ws.onopen = () =>
            ws.send(
              JSON.stringify({
                type: 'execute',
                cell_id: 'uji-1',
                code:
                  "import torch\nprint('CUDA:', torch.cuda.is_available())\n" +
                  "print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')",
              }),
            )
          ws.onmessage = (ev) => {
            const m = JSON.parse(String(ev.data))
            if (m.type === 'stream') out += m.text ?? ''
            if (m.type === 'error') {
              clearTimeout(batas)
              ws.close()
              reject(new Error(`kernel error: ${m.ename ?? ''} ${m.evalue ?? ''}`))
            }
            if (m.type === 'execute_reply') {
              clearTimeout(batas)
              ws.close()
              resolve(out)
            }
          }
          ws.onerror = () => {
            clearTimeout(batas)
            reject(new Error('WebSocket gagal tersambung'))
          }
        })
      },
      { sid: sessionId, tok: token, prefix: API_PREFIX },
    )

    expect(keluaran, 'kernel mengeksekusi kode').toContain('CUDA:')
    expect(keluaran, 'kernel melihat GPU CUDA').toContain('CUDA: True')
    expect(keluaran, 'nama GPU terbaca').toMatch(/GPU:\s*NVIDIA/i)
  })
})
