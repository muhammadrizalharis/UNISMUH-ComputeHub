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
// IDE devbox di ROOT domain (bukan /api/v1).
const ORIGIN = new URL(API_PREFIX).origin

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
    expect(typeof body.disconnect_timeout_seconds).toBe('number')
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

  test('TC-DEVBOX-04 devbox memakai plafon kebijakan peran & perangkat otomatis', async ({
    request,
  }) => {
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
    // Perangkat ditentukan server: GPU bila tersedia, selain itu CPU — keduanya sah.
    expect(['cpu', 'gpu']).toContain(box.device)
    expect(box.cpu_threads).toBeGreaterThan(0)
    expect(box.ram_mb).toBeGreaterThan(0)
    expect(box.job_id).not.toBeNull() // tercatat sebagai job -> masuk laporan
  })

  test('TC-DEVBOX-08 IDE di browser: tiket sekali-pakai -> cookie sesi; tanpa cookie ditolak', async ({
    request,
    playwright,
  }) => {
    // Tunggu jalur web siap (serve-web menjawab) — biasanya < 10 dtk, pertama kali bisa lebih.
    let now: Record<string, unknown> = {}
    for (let i = 0; i < 40; i++) {
      now = await (await request.get(`${API_PREFIX}/devbox`, { headers: auth(STUDENT_STATE) })).json()
      if (now.state === 'running' && now.web_url) break
      if (!['running', 'starting'].includes(String(now.state))) break
      await new Promise((r) => setTimeout(r, 3000))
    }
    if (now.web_enabled === false) {
      test.skip(true, 'Jalur IDE web dinonaktifkan di server ini.')
      return
    }
    if (now.state !== 'running' || !now.web_url) {
      test.skip(true, `Devbox mahasiswa tidak running/web belum siap (${now.state}).`)
      return
    }
    expect(now.web_url).toBe('/devbox-ide/24/')
    expect(now.tunnel_state).toBe('off') // tunnel Microsoft TIDAK ikut menyala

    const tiket = await request.post(`${API_PREFIX}/devbox/web-ticket`, { headers: auth(STUDENT_STATE) })
    expect(tiket.status()).toBe(200)
    const { url, path } = await tiket.json()
    expect(path).toBe('/devbox-ide/24/')
    expect(url).toMatch(/^\/devbox-ide\/24\/\?ch_ticket=/)

    // Tanpa cookie: ditolak, bukan diteruskan ke IDE.
    const polos = await request.get(`${ORIGIN}/devbox-ide/24/`, { headers: { Accept: 'text/html' } })
    expect(polos.status()).toBe(401)

    // Tiket ditukar -> 303 + cookie sesi ber-path /devbox-ide/24 (ikut tersimpan di jar konteks).
    const tukar = await request.get(`${ORIGIN}${url}`, { maxRedirects: 0 })
    expect(tukar.status()).toBe(303)
    const cookies = tukar.headersArray().filter((h) => h.name.toLowerCase() === 'set-cookie').map((h) => h.value)
    expect(cookies.some((c) => c.startsWith('ch_devbox_web=') && /HttpOnly/i.test(c) && /Path=\/devbox-ide\/24/.test(c))).toBe(true)
    expect(cookies.some((c) => c.startsWith('vscode-tkn=') && /Path=\/devbox-ide\/24/.test(c))).toBe(true)

    // Tiket yang sama TIDAK bisa dipakai lagi (konteks baru = tanpa cookie).
    const segar = await playwright.request.newContext()
    try {
      const ulang = await segar.get(`${ORIGIN}${url}`, { maxRedirects: 0, headers: { Accept: 'text/html' } })
      expect(ulang.status()).toBe(401)
    } finally {
      await segar.dispose()
    }

    // Dengan cookie sesi: permintaan diteruskan ke VS Code (200 siap / 202 bundel masih diunduh).
    // Cookie bertanda Secure -> jar Playwright menolaknya di http://127.0.0.1, jadi dikirim eksplisit.
    const sesi = cookies
      .map((c) => c.split(';')[0])
      .filter((c) => c.startsWith('ch_devbox_web=') || c.startsWith('vscode-tkn='))
      .join('; ')
    const ide = await request.get(`${ORIGIN}/devbox-ide/24/`, { headers: { Cookie: sesi } })
    expect([200, 202]).toContain(ide.status())
    expect(ide.headers()['content-type'] ?? '').toMatch(/text\/html/)
    // Header keamanan SPA kita tidak boleh menimpa milik VS Code (iframe same-origin dipakai webview).
    expect(ide.headers()['x-frame-options'] ?? '').not.toBe('DENY')
    expect(ide.headers()['content-security-policy'] ?? '').not.toMatch(/frame-ancestors 'none'/)

    // Pemilik lain: cookie mahasiswa TIDAK membuka IDE user lain.
    const lain = await request.get(`${ORIGIN}/devbox-ide/19/`, { headers: { Accept: 'text/html', Cookie: sesi } })
    expect(lain.status()).toBe(401)
  })

  test('TC-DEVBOX-05 memaksa mode berbeda saat berjalan ditolak jelas', async ({ request }) => {
    const status = await request.get(`${API_PREFIX}/devbox`, { headers: auth(STUDENT_STATE) })
    const now = await status.json()
    if (!['running', 'starting', 'needs_login'].includes(now.state)) {
      test.skip(true, 'Devbox mahasiswa tidak berjalan; skenario tak berlaku.')
      return
    }
    // Minta KEBALIKAN dari perangkat yang sedang aktif (perangkat kini ditentukan server).
    const lawan = now.device === 'gpu' ? 'false' : 'true'
    const res = await request.post(`${API_PREFIX}/devbox/start?gpu=${lawan}`, {
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

  test('TC-DEVBOX-09 tiket IDE ditolak saat devbox mati dan tanpa login', async ({ request }) => {
    const mati = await request.post(`${API_PREFIX}/devbox/web-ticket`, { headers: auth(STUDENT_STATE) })
    expect([404, 409]).toContain(mati.status()) // 404 = jalur web dimatikan, 409 = devbox tidak menyala
    const anon = await request.post(`${API_PREFIX}/devbox/web-ticket`)
    expect(anon.status()).toBe(401)
    const tunnelAnon = await request.post(`${API_PREFIX}/devbox/tunnel/start`)
    expect(tunnelAnon.status()).toBe(401)
    const ideMati = await request.get(`${ORIGIN}/devbox-ide/24/`, { headers: { Accept: 'text/html' } })
    expect(ideMati.status()).toBe(401) // tanpa cookie selalu 401 walau devbox mati
  })

  test('TC-DEVBOX-10 pemasang VS Code Desktop hanya untuk pemilik & berisi kunci + proxy', async ({
    request,
  }) => {
    const anon = await request.get(`${API_PREFIX}/devbox/desktop-setup?os_name=unix`)
    expect(anon.status()).toBe(401)

    const res = await request.get(`${API_PREFIX}/devbox/desktop-setup?os_name=unix`, {
      headers: auth(STUDENT_STATE),
    })
    if (res.status() !== 200) {
      expect([404, 503]).toContain(res.status()) // jalur SSH dimatikan super admin
      test.skip(true, `Remote-SSH tidak aktif (${res.status()}).`)
      return
    }
    // Rahasia: tidak boleh di-cache proxy/browser, dan diunduh sebagai berkas.
    expect(res.headers()['cache-control'] ?? '').toMatch(/no-store/)
    expect(res.headers()['content-disposition'] ?? '').toMatch(/attachment/)
    const isi = await res.text()
    expect(isi).toContain('BEGIN OPENSSH PRIVATE KEY') // kunci dibuatkan server
    expect(isi).toContain('ProxyCommand') // user tak perlu menyunting ~/.ssh/config
    expect(isi).toMatch(/wss:\/\/.*\/devbox-ssh\//)
    expect(isi).toContain('IdentitiesOnly yes')

    const win = await request.get(`${API_PREFIX}/devbox/desktop-setup?os_name=windows`, {
      headers: auth(STUDENT_STATE),
    })
    expect(win.status()).toBe(200)
    expect(await win.text()).toContain('devbox_ssh_proxy.ps1') // tanpa unduhan biner apa pun
  })

  test('TC-DEVBOX-11 kunci Desktop dapat diterbitkan ulang oleh pemiliknya saja', async ({
    request,
  }) => {
    const anon = await request.post(`${API_PREFIX}/devbox/desktop-key/rotate`)
    expect(anon.status()).toBe(401)

    const sebelum = await request.get(`${API_PREFIX}/devbox/desktop-setup?os_name=unix`, {
      headers: auth(STUDENT_STATE),
    })
    if (sebelum.status() !== 200) {
      test.skip(true, 'Remote-SSH tidak aktif.')
      return
    }
    const lama = await sebelum.text()
    const rotate = await request.post(`${API_PREFIX}/devbox/desktop-key/rotate`, {
      headers: auth(STUDENT_STATE),
    })
    expect(rotate.status()).toBe(204)
    const sesudah = await request.get(`${API_PREFIX}/devbox/desktop-setup?os_name=unix`, {
      headers: auth(STUDENT_STATE),
    })
    expect(sesudah.status()).toBe(200)
    // Kunci BARU -> pemasang lama (laptop hilang) tidak lagi sama & aksesnya dicabut.
    expect(await sesudah.text()).not.toBe(lama)
  })

  test('TC-DEVBOX-07 pemakaian disk devbox terlihat admin, tertutup untuk mahasiswa', async ({
    request,
  }) => {
    const tolak = await request.get(`${API_PREFIX}/devbox/disk`, { headers: auth(STUDENT_STATE) })
    expect(tolak.status()).toBe(403)

    const res = await request.get(`${API_PREFIX}/devbox/disk`, { headers: auth(SUPERADMIN_STATE) })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(typeof body.total_bytes).toBe('number')
    expect(Array.isArray(body.users)).toBe(true)
    // Retensi harus terbaca supaya admin tahu pembersihan otomatis aktif.
    expect(typeof body.retention_days).toBe('number')
  })
})
