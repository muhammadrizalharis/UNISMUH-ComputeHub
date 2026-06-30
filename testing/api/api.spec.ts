import { test, expect, request as pwRequest } from '@playwright/test'

import { API_PREFIX, BASE_URL, ADMIN_STATE, STUDENT_STATE } from '../utils/constants'
import { readInfo, tokenFromState } from '../utils/helpers'

let adminTok = ''
let studentTok = ''

test.beforeAll(() => {
  adminTok = tokenFromState(ADMIN_STATE)
  studentTok = tokenFromState(STUDENT_STATE)
})

test.describe('API', () => {
  test('TC-API-01 GET /health → 200 {status:ok}', async ({ request }) => {
    const res = await request.get(`${BASE_URL}/health`)
    expect(res.status()).toBe(200)
    expect((await res.json()).status).toBe('ok')
  })

  test('TC-API-02 GET /auth/me tanpa token → 401', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/auth/me`)
    expect(res.status()).toBe(401)
  })

  test('TC-API-03 GET /auth/me dengan token admin → 200 + schema', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/auth/me`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    expect(res.status()).toBe(200)
    const me = await res.json()
    expect(me).toHaveProperty('id')
    expect(me).toHaveProperty('email')
    expect(me).toHaveProperty('role')
    expect(me.role).toBe('admin')
  })

  test('TC-API-04 Authorization: student DILARANG di endpoint admin → 403', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/admin/report`, {
      headers: { Authorization: `Bearer ${studentTok}` },
    })
    expect([401, 403]).toContain(res.status())
  })

  test('TC-API-05 Admin BOLEH di endpoint admin → 200', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/admin/report`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    expect(res.status()).toBe(200)
  })

  test('TC-API-06 /admin/report/disk admin → 200 + schema disk', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/admin/report/disk`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    expect(res.status()).toBe(200)
    const d = await res.json()
    expect(d).toHaveProperty('total_bytes')
    expect(d).toHaveProperty('users')
    expect(Array.isArray(d.users)).toBeTruthy()
  })

  test('TC-API-07 Payload kosong ke /auth/login → 422', async ({ request }) => {
    const res = await request.post(`${API_PREFIX}/auth/login`, { data: {} })
    expect(res.status()).toBe(422)
  })

  test('TC-API-08 Endpoint tak dikenal → 404', async ({ request }) => {
    const res = await request.get(`${API_PREFIX}/endpoint-ngawur-zzz`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    expect(res.status()).toBe(404)
  })

  test('TC-API-09 Latensi /health & /admin/report wajar', async () => {
    const ctx = await pwRequest.newContext()
    const t0 = Date.now()
    await ctx.get(`${BASE_URL}/health`)
    const health = Date.now() - t0
    const t1 = Date.now()
    await ctx.get(`${API_PREFIX}/admin/report`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    const report = Date.now() - t1
    await ctx.dispose()
    // eslint-disable-next-line no-console
    console.log(`[latency] health=${health}ms report=${report}ms`)
    expect.soft(health, 'health < 1500ms').toBeLessThan(1500)
    expect.soft(report, 'report < 8000ms').toBeLessThan(8000)
  })

  test('TC-API-10 /report/user student DILARANG → 401/403', async ({ request }) => {
    const info = readInfo()
    const target = info.admin.username ?? 'admin'
    const res = await request.get(
      `${API_PREFIX}/admin/report/user/${encodeURIComponent(target)}`,
      { headers: { Authorization: `Bearer ${studentTok}` } },
    )
    expect([401, 403]).toContain(res.status())
  })
})
