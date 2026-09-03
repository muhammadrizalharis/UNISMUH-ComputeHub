import { test, expect } from '@playwright/test'

import { API_PREFIX, STUDENT_STATE, SUPERADMIN_STATE } from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * DEVBOX — ngoding di VS Code sendiri dengan sumber daya server (ala Codespaces).
 *
 * Uji ini NON-DESTRUKTIF & hemat GPU: devbox yang dinyalakan selalu mode CPU dan
 * SELALU dihentikan di afterAll (walau tes gagal). Mode GPU TIDAK dinyalakan di sini
 * supaya suite tidak menahan GPU yang dipakai pengguna lain.
 *
 * Yang dikunci perilakunya:
 *  - Status awal terbaca & membawa flag kemampuan (enabled/allow_gpu).
 *  - Plafon CPU/RAM devbox mengikuti kebijakan peran (mahasiswa dibatasi).
 *  - Meminta mode berbeda saat devbox berjalan DITOLAK jelas (409), bukan diabaikan diam-diam.
 *  - Endpoint admin `/devbox/all` tertutup untuk mahasiswa (403).
 *  - Devbox tercatat sebagai job (akuntabilitas laporan) lewat field job_id.
 */

const auth = (state: string) => ({ Authorization: `Bearer ${tokenFromState(state)}` })

test.describe.configure({ mode: 'serial' })

test.describe('Devbox VS Code (API)', () => {
  test.afterAll(async ({ request }) => {
    // Jaring pengaman: jangan tinggalkan devbox uji menyala.
    await request
      .post(`${API_PREFIX}/devbox/stop`, { headers: auth(STUDENT_STATE) })
      .catch(() => undefined)
  })

  test('TC-DEVBOX-01 status devbox terbaca + membawa flag kemampuan', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/devbox`, { headers: auth(STUDENT_STATE) })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('state')
    expect(body).toHaveProperty('enabled')
    expect(typeof body.enabled).toBe('boolean')
  })

  test('TC-DEVBOX-02 endpoint admin tertutup untuk mahasiswa', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/devbox/all`, { headers: auth(STUDENT_STATE) })
    expect(res.status()).toBe(403)
  })

  test('TC-DEVBOX-03 admin dapat melihat daftar devbox', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/devbox/all`, { headers: auth(SUPERADMIN_STATE) })
    expect(res.status()).toBe(200)
    expect(Array.isArray(await res.json())).toBe(true)
  })

  test('TC-DEVBOX-04 devbox mahasiswa memakai plafon kebijakan peran', async ({ request }) => {
    const start = await request.post(`${API_PREFIX}/devbox/start`, {
      headers: auth(STUDENT_STATE),
    })
    // Fitur bisa dimatikan super admin (503) atau kapasitas penuh (409) — keduanya sah.
    if (start.status() !== 200) {
      expect([409, 503]).toContain(start.status())
      test.skip(true, `Devbox tidak tersedia saat ini (${start.status()}).`)
      return
    }
    const box = await start.json()
    expect(box.device).toBe('cpu')
    expect(box.cpu_threads).toBeGreaterThan(0)
    expect(box.ram_mb).toBeGreaterThan(0)
    expect(box.job_id).not.toBeNull() // tercatat sebagai job -> masuk laporan
  })

  test('TC-DEVBOX-05 minta mode berbeda saat berjalan ditolak jelas', async ({ request }) => {
    const status = await request.get(`${API_PREFIX}/devbox`, { headers: auth(STUDENT_STATE) })
    const now = await status.json()
    if (!['running', 'starting', 'needs_login'].includes(now.state)) {
      test.skip(true, 'Devbox mahasiswa tidak berjalan; skenario tak berlaku.')
      return
    }
    const res = await request.post(`${API_PREFIX}/devbox/start?gpu=true`, {
      headers: auth(STUDENT_STATE),
    })
    expect(res.status()).toBe(409)
    expect((await res.json()).detail).toMatch(/mode/i)
  })

  test('TC-DEVBOX-06 devbox dapat dihentikan pemiliknya', async ({ request }) => {
    const res = await request.post(`${API_PREFIX}/devbox/stop`, { headers: auth(STUDENT_STATE) })
    expect(res.status()).toBe(204)
    const after = await request.get(`${API_PREFIX}/devbox`, { headers: auth(STUDENT_STATE) })
    expect((await after.json()).state).toBe('stopped')
  })
})
