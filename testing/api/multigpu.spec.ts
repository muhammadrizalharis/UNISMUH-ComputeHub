import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import {
  API_PREFIX,
  ADMIN_STATE,
  SUPERADMIN_STATE,
  STUDENT_STATE,
} from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * JOB 2 GPU (izin per-user, hanya administrator utama).
 *
 * Kebijakan:
 *  - PATCH policy allow_multi_gpu : HANYA super admin (admin biasa 403).
 *  - Submit multi_gpu=true        : butuh izin -> tanpa izin 403.
 *  - Dengan izin                  : 201, job.multi_gpu=true.
 *
 * Non-destruktif: job uji DIJADWALKAN +10 menit (tak pernah menyentuh GPU),
 * langsung dibatalkan; izin dicabut kembali di afterAll. Bila sesi super admin
 * tidak tersedia, uji yang bergantung dilewati secara sah (pola trash.spec).
 */

const STUDENT_ID = 24 // CHqastudent

let ctx: APIRequestContext
let studentTok = ''
let adminTok = ''
let superTok = ''
let superOk = false
let jobId = 0

const auth = (t: string) => ({ Authorization: `Bearer ${t}` })
const schedIso = () => new Date(Date.now() + 10 * 60_000).toISOString()

test.beforeAll(async () => {
  ctx = await pwRequest.newContext()
  studentTok = tokenFromState(STUDENT_STATE)
  adminTok = tokenFromState(ADMIN_STATE)
  superTok = tokenFromState(SUPERADMIN_STATE)
  const me = await ctx.get(`${API_PREFIX}/auth/me`, { headers: auth(superTok) })
  superOk = me.ok() && Boolean((await me.json()).is_superadmin)
})

test.afterAll(async () => {
  // Bersih-bersih idempoten: batalkan job uji + cabut izin.
  if (jobId) {
    await ctx.post(`${API_PREFIX}/jobs/${jobId}/cancel`, { headers: auth(studentTok) })
  }
  if (superOk) {
    await ctx.patch(`${API_PREFIX}/admin/users/${STUDENT_ID}/policy`, {
      headers: auth(superTok),
      data: { allow_multi_gpu: null },
    })
  }
  await ctx.dispose()
})

test.describe.serial('Job 2 GPU (izin super admin)', () => {
  test('TC-MG-01 tanpa izin: submit multi_gpu ditolak 403', async () => {
    const res = await ctx.post(`${API_PREFIX}/jobs`, {
      headers: auth(studentTok),
      data: {
        source_type: 'paste',
        code: "print('qa-multigpu')",
        multi_gpu: true,
        scheduled_at: schedIso(),
      },
    })
    expect(res.status()).toBe(403)
    expect(String((await res.json()).detail)).toContain('administrator utama')
  })

  test('TC-MG-02 admin biasa DILARANG mengatur izin 2 GPU (403)', async () => {
    const res = await ctx.patch(`${API_PREFIX}/admin/users/${STUDENT_ID}/policy`, {
      headers: auth(adminTok),
      data: { allow_multi_gpu: true },
    })
    expect(res.status()).toBe(403)
  })

  test('TC-MG-03 super admin memberi izin -> effective true', async () => {
    test.skip(!superOk, 'sesi super admin tidak tersedia')
    const res = await ctx.patch(`${API_PREFIX}/admin/users/${STUDENT_ID}/policy`, {
      headers: auth(superTok),
      data: { allow_multi_gpu: true },
    })
    expect(res.status()).toBe(200)
    expect((await res.json()).effective.allow_multi_gpu).toBe(true)
  })

  test('TC-MG-04 dengan izin: submit 2 GPU -> 201 lalu dibatalkan', async () => {
    test.skip(!superOk, 'sesi super admin tidak tersedia (izin tak bisa diberikan)')
    const res = await ctx.post(`${API_PREFIX}/jobs`, {
      headers: auth(studentTok),
      data: {
        source_type: 'paste',
        code: "print('qa-multigpu-ok')",
        name: `qa-multigpu-${Date.now()}`,
        multi_gpu: true,
        scheduled_at: schedIso(), // ditahan di antrian -> GPU tak pernah tersentuh
      },
    })
    expect(res.status()).toBe(201)
    const body = await res.json()
    jobId = body.id as number
    expect(body.multi_gpu).toBe(true)
    expect(body.status).toBe('queued')

    const cancel = await ctx.post(`${API_PREFIX}/jobs/${jobId}/cancel`, {
      headers: auth(studentTok),
    })
    expect([200, 204]).toContain(cancel.status())
    jobId = 0
  })
})
