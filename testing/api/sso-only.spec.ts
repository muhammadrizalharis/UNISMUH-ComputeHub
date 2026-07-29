import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import { API_PREFIX, SUPERADMIN_STATE } from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * MODE SATU PINTU SSO (SSO_ONLY_LOGIN): mahasiswa/dosen hanya lewat SSO;
 * login lokal tersisa untuk admin + kunci pintu URL (dicek backend).
 *
 * Spec ini SADAR MODE: membaca /auth/sso/status lebih dulu — bila mode mati
 * (mis. lingkungan dev), uji yang bergantung mode dilewati secara sah.
 * Tidak ada kredensial dalam berkas ini; kunci pintu TIDAK pernah ditulis di uji.
 */

let ctx: APIRequestContext
let ssoOnly = false
let superTok = ''

test.beforeAll(async () => {
  ctx = await pwRequest.newContext()
  superTok = tokenFromState(SUPERADMIN_STATE)
  const res = await ctx.get(`${API_PREFIX}/auth/sso/status`)
  if (res.ok()) {
    const body = await res.json()
    ssoOnly = Boolean(body.sso_only)
  }
})

test.afterAll(async () => {
  await ctx.dispose()
})

test.describe('Mode satu pintu SSO', () => {
  test('TC-SSOONLY-01 /auth/sso/status memuat field sso_only', async () => {
    const res = await ctx.get(`${API_PREFIX}/auth/sso/status`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(typeof body.enabled).toBe('boolean')
    expect(typeof body.sso_only).toBe('boolean')
  })

  test('TC-SSOONLY-02 buat akun mahasiswa manual DIBLOKIR saat mode aktif', async () => {
    test.skip(!ssoOnly, 'SSO_ONLY_LOGIN nonaktif di lingkungan ini')
    const res = await ctx.post(`${API_PREFIX}/users`, {
      headers: { Authorization: `Bearer ${superTok}` },
      data: {
        name: 'Uji SSO Only',
        email: `uji-ssoonly-${Date.now()}@student.unismuh.ac.id`,
        role: 'mahasiswa',
      },
    })
    expect(res.status()).toBe(403)
    const body = await res.json()
    expect(String(body.detail)).toContain('SSO')
  })

  test('TC-SSOONLY-03 login tanpa kunci pintu TIDAK membocorkan keberadaan pintu', async () => {
    // Password sengaja salah: jawaban harus 401 generik yang SAMA seperti dulu,
    // tanpa menyinggung kunci/pintu/SSO (anti-enumerasi).
    const res = await ctx.post(`${API_PREFIX}/auth/login`, {
      form: { username: 'CHSuperAdmin', password: `salah-${Date.now()}` },
    })
    expect(res.status()).toBe(401)
    const body = await res.json()
    expect(String(body.detail)).toBe('Username/email atau password salah.')
  })
})
