import { test, expect } from '@playwright/test'

import { API_PREFIX, BASE_URL, ADMIN_STATE, STUDENT_STATE } from '../utils/constants'
import { tokenFromState, shot } from '../utils/helpers'

let adminTok = ''
let studentTok = ''

test.beforeAll(() => {
  adminTok = tokenFromState(ADMIN_STATE)
  studentTok = tokenFromState(STUDENT_STATE)
})

test.describe('Keamanan (probe non-destruktif)', () => {
  test('SEC-01 Header keamanan & anti-clickjacking', async ({ request }) => {
    const res = await request.get(`${BASE_URL}/`)
    const h = res.headers()
    // eslint-disable-next-line no-console
    console.log('[sec headers]', JSON.stringify(h))
    expect(h['x-frame-options'] ?? '', 'X-Frame-Options (anti-clickjacking)').toMatch(/DENY|SAMEORIGIN/i)
    expect(h['content-security-policy'] ?? '', 'CSP terpasang').not.toEqual('')
    expect(h['strict-transport-security'] ?? '', 'HSTS terpasang').toMatch(/max-age=\d+/)
    expect(h['x-content-type-options'] ?? '', 'nosniff').toMatch(/nosniff/i)
  })

  test('SEC-02 Endpoint terproteksi menolak tanpa token (401)', async ({ request }) => {
    for (const ep of ['/auth/me', '/admin/report', '/admin/report/disk']) {
      const res = await request.get(`${API_PREFIX}${ep}`)
      expect(res.status(), `${ep} tanpa token`).toBe(401)
    }
  })

  test('SEC-03 Privilege escalation: student → endpoint admin ditolak', async ({ request }) => {
    for (const ep of ['/admin/report', '/admin/report/disk', '/admin/usage']) {
      const res = await request.get(`${API_PREFIX}${ep}`, {
        headers: { Authorization: `Bearer ${studentTok}` },
      })
      expect([401, 403], `${ep} sbg student`).toContain(res.status())
    }
  })

  test('SEC-04 Directory traversal pada workspace ditolak', async ({ request }) => {
    const payload = encodeURIComponent('../../../../etc/passwd')
    const res = await request.get(
      `${API_PREFIX}/interactive/workspace/file?path=${payload}`,
      { headers: { Authorization: `Bearer ${studentTok}` } },
    )
    expect([400, 403, 404], 'traversal harus ditolak').toContain(res.status())
    const body = await res.text().catch(() => '')
    expect(body, 'tidak membocorkan /etc/passwd').not.toMatch(/root:.*:0:0:/)
  })

  test('SEC-05 SQL injection pada login ditolak (1 percobaan)', async ({ request }) => {
    const res = await request.post(`${API_PREFIX}/auth/login`, {
      data: { email: "admin' OR '1'='1", password: "' OR '1'='1" },
    })
    // Harus gagal otentikasi (bukan 200, bukan 500).
    expect([400, 401, 422], 'SQLi login tidak boleh sukses').toContain(res.status())
  })

  test('SEC-06 CORS tidak memantulkan origin jahat', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/auth/me`, {
      headers: { Authorization: `Bearer ${adminTok}`, Origin: 'http://evil.example.com' },
    })
    const acao = res.headers()['access-control-allow-origin'] ?? ''
    expect(acao, 'ACAO tidak memantulkan evil origin').not.toBe('http://evil.example.com')
  })

  test('SEC-07 Tidak ada kebocoran error sensitif (stack trace) pada 404', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/endpoint-ngawur-zzz`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    const body = await res.text()
    expect(body, 'tidak ada traceback Python').not.toMatch(/Traceback \(most recent call last\)/)
    expect(body, 'tidak menyebut path internal').not.toMatch(/\/home\/[a-z]+\/DATA_ICAL/)
  })

  test('SEC-08 XSS tersimpan/terpantul tidak tereksekusi di kolom cari', async ({ browser }, testInfo) => {
    const ctx = await browser.newContext({ storageState: ADMIN_STATE })
    const page = await ctx.newPage()
    let dialog = false
    page.on('dialog', async (d) => {
      dialog = true
      await d.dismiss()
    })
    await page.goto('/users', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1000)
    const search = page.getByPlaceholder(/cari|search/i).first()
    if ((await search.count()) > 0) {
      await search.fill('<img src=x onerror=alert(1)>')
      await page.waitForTimeout(800)
      await shot(page, 'security', 'xss-probe', testInfo)
    }
    expect(dialog, 'tidak ada dialog alert (XSS tidak tereksekusi)').toBeFalsy()
    await ctx.close()
  })

  test('SEC-09 Token tidak bocor ke cookie/URL', async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: ADMIN_STATE })
    const page = await ctx.newPage()
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(800)
    const cookies = await ctx.cookies()
    const jwtInCookie = cookies.some((c) => /eyJ[\w-]+\./.test(c.value))
    expect(jwtInCookie, 'JWT tidak boleh ada di cookie').toBeFalsy()
    expect(page.url(), 'token tidak ada di URL').not.toMatch(/eyJ[\w-]+\./)
    await ctx.close()
  })
})
