import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import { API_PREFIX, ADMIN_STATE, STUDENT_STATE } from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * MENU SARAN (feedback): kirim → lihat milik sendiri → RBAC → tinjau admin → hapus.
 *
 * Kebijakan backend (feedback.py):
 *  - POST /feedback        : semua peran (rate limit 10/24 jam per user).
 *  - GET  /feedback/mine   : hanya kiriman milik sendiri.
 *  - GET  /feedback        : admin & super admin saja (mahasiswa 403).
 *  - PATCH/DELETE /{id}    : admin & super admin saja.
 *
 * Non-destruktif: pesan berprefix "[UJI QA]" TIDAK memicu notifikasi email/Telegram
 * (dilewati feedback_notify), dan baris uji DIHAPUS admin pada afterAll — sehingga
 * rate limit tidak menumpuk antar-run.
 */

let ctx: APIRequestContext
let studentTok = ''
let adminTok = ''
let fbId = 0

const auth = (t: string) => ({ Authorization: `Bearer ${t}` })

test.beforeAll(async () => {
  ctx = await pwRequest.newContext()
  studentTok = tokenFromState(STUDENT_STATE)
  adminTok = tokenFromState(ADMIN_STATE)
})

test.afterAll(async () => {
  // Bersihkan baris uji (idempoten — 404 bila sudah terhapus oleh TC-FB-06).
  if (fbId) {
    await ctx.delete(`${API_PREFIX}/feedback/${fbId}`, { headers: auth(adminTok) })
  }
  await ctx.dispose()
})

test.describe.serial('Menu Saran (feedback)', () => {
  test('TC-FB-01 mahasiswa mengirim saran (201) + validasi pesan pendek (422)', async () => {
    const bad = await ctx.post(`${API_PREFIX}/feedback`, {
      headers: auth(studentTok),
      data: { category: 'saran', message: 'ab' },
    })
    expect(bad.status(), 'pesan <5 karakter ditolak').toBe(422)

    const res = await ctx.post(`${API_PREFIX}/feedback`, {
      headers: auth(studentTok),
      data: {
        category: 'masalah',
        message: `[UJI QA] feedback spec ${Date.now()} — dibersihkan otomatis.`,
      },
    })
    expect(res.status()).toBe(201)
    const body = await res.json()
    fbId = body.id as number
    expect(body.status).toBe('baru')
    expect(body.user_id).toBeGreaterThan(0)
  })

  test('TC-FB-02 mahasiswa melihat kiriman miliknya di /feedback/mine', async () => {
    const res = await ctx.get(`${API_PREFIX}/feedback/mine`, { headers: auth(studentTok) })
    expect(res.status()).toBe(200)
    const items = (await res.json()) as Array<{ id: number }>
    expect(items.some((f) => f.id === fbId), 'kiriman baru ada di daftar sendiri').toBe(true)
  })

  test('TC-FB-03 mahasiswa DILARANG melihat semua saran (403)', async () => {
    const res = await ctx.get(`${API_PREFIX}/feedback`, { headers: auth(studentTok) })
    expect(res.status()).toBe(403)
  })

  test('TC-FB-04 mahasiswa DILARANG mengubah status / menghapus (403)', async () => {
    const patch = await ctx.patch(`${API_PREFIX}/feedback/${fbId}`, {
      headers: auth(studentTok),
      data: { status: 'selesai' },
    })
    expect(patch.status()).toBe(403)
    const del = await ctx.delete(`${API_PREFIX}/feedback/${fbId}`, {
      headers: auth(studentTok),
    })
    expect(del.status()).toBe(403)
  })

  test('TC-FB-05 admin melihat semua & mengubah status', async () => {
    const res = await ctx.get(`${API_PREFIX}/feedback`, { headers: auth(adminTok) })
    expect(res.status()).toBe(200)
    const items = (await res.json()) as Array<{ id: number; user_name: string }>
    expect(items.some((f) => f.id === fbId), 'kiriman mahasiswa terlihat admin').toBe(true)

    const patch = await ctx.patch(`${API_PREFIX}/feedback/${fbId}`, {
      headers: auth(adminTok),
      data: { status: 'ditinjau' },
    })
    expect(patch.status()).toBe(200)
    expect((await patch.json()).status).toBe('ditinjau')
  })

  test('TC-FB-06 admin menghapus saran (204) dan hilang dari daftar', async () => {
    const del = await ctx.delete(`${API_PREFIX}/feedback/${fbId}`, { headers: auth(adminTok) })
    expect(del.status()).toBe(204)
    const res = await ctx.get(`${API_PREFIX}/feedback`, { headers: auth(adminTok) })
    const items = (await res.json()) as Array<{ id: number }>
    expect(items.some((f) => f.id === fbId)).toBe(false)
    fbId = 0
  })
})
