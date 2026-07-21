import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import {
  API_PREFIX,
  ADMIN_STATE,
  SUPERADMIN_STATE,
  STUDENT_STATE,
  DOSEN_STATE,
} from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * SIKLUS "SAMPAH" JOB (soft-delete → restore → purge) + matriks RBAC 4 peran.
 *
 * Kebijakan backend (jobs.py):
 *  - Soft-delete : super admin SEMUA job; owner NON-admin job miliknya; admin biasa DILARANG.
 *  - Restore     : super admin SEMUA; owner NON-admin miliknya; admin biasa boleh MENOLONG
 *                  (job milik mahasiswa/dosen saja).
 *  - Purge       : HANYA super admin (permanen, file ikut terhapus).
 *
 * Non-destruktif: job uji dibuat khusus (device=cpu, kode print singkat) lalu di-PURGE
 * oleh super admin pada akhir suite. Bila token super admin tidak sah (tak ada sesi),
 * job ditinggalkan di Sampah (dibersihkan otomatis oleh retensi 7 hari) — dicatat sah.
 */

let ctx: APIRequestContext
let studentTok = ''
let dosenTok = ''
let adminTok = ''
let superTok = ''
let superOk = false
let jobId = 0

const auth = (t: string) => ({ Authorization: `Bearer ${t}` })

test.beforeAll(async () => {
  ctx = await pwRequest.newContext()
  studentTok = tokenFromState(STUDENT_STATE)
  dosenTok = tokenFromState(DOSEN_STATE)
  adminTok = tokenFromState(ADMIN_STATE)
  superTok = tokenFromState(SUPERADMIN_STATE)
  const me = await ctx.get(`${API_PREFIX}/auth/me`, { headers: auth(superTok) })
  superOk = me.ok() && Boolean((await me.json()).is_superadmin)

  // Job uji milik MAHASISWA: device=cpu (tak menyentuh GPU/kuota GPU), kode singkat.
  const res = await ctx.post(`${API_PREFIX}/jobs`, {
    headers: auth(studentTok),
    data: {
      name: `qa-trash-${Date.now()}`,
      source_type: 'paste',
      code: "print('qa-trash-ok')",
      device: 'cpu',
    },
  })
  expect(res.status(), 'job uji dibuat (201)').toBe(201)
  jobId = (await res.json()).id as number
})

test.afterAll(async () => {
  // Pembersihan terbaik: purge oleh super admin (permanen). Fallback: biarkan di
  // Sampah (retensi otomatis menghapus dalam 7 hari).
  try {
    if (jobId) {
      await ctx.delete(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(studentTok) })
      if (superOk) await ctx.delete(`${API_PREFIX}/jobs/${jobId}/purge`, { headers: auth(superTok) })
    }
  } finally {
    await ctx.dispose()
  }
})

test.describe('Sampah job: soft-delete / restore / purge (RBAC 4 peran)', () => {
  test('TC-TRASH-01 Dosen & admin biasa DILARANG menghapus job mahasiswa', async () => {
    const asDosen = await ctx.delete(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(dosenTok) })
    expect(asDosen.status(), 'dosen hapus job orang lain → 403').toBe(403)
    const asAdmin = await ctx.delete(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(adminTok) })
    expect(asAdmin.status(), 'admin biasa DILARANG soft-delete (kebijakan)').toBe(403)
  })

  test('TC-TRASH-02 Mahasiswa hapus job sendiri → masuk Sampah (tak tampil di daftar aktif)', async () => {
    const del = await ctx.delete(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(studentTok) })
    expect(del.status(), 'soft-delete owner → 204').toBe(204)

    const active = await ctx.get(`${API_PREFIX}/jobs?limit=200`, { headers: auth(studentTok) })
    expect(active.status()).toBe(200)
    const activeIds = ((await active.json()) as { id: number }[]).map((j) => j.id)
    expect(activeIds, 'job HILANG dari daftar aktif').not.toContain(jobId)

    const trash = await ctx.get(`${API_PREFIX}/jobs?deleted=true&limit=200`, {
      headers: auth(studentTok),
    })
    expect(trash.status()).toBe(200)
    const item = ((await trash.json()) as { id: number; deleted_at: string | null }[]).find(
      (j) => j.id === jobId,
    )
    expect(item, 'job ADA di Sampah').toBeTruthy()
    expect(item?.deleted_at, 'deleted_at terisi').toBeTruthy()
  })

  test('TC-TRASH-03 Idempoten: hapus job yang sudah di Sampah tetap 204', async () => {
    const again = await ctx.delete(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(studentTok) })
    expect(again.status()).toBe(204)
  })

  test('TC-TRASH-04 Dosen DILARANG restore job mahasiswa; admin biasa BOLEH menolong', async () => {
    const asDosen = await ctx.post(`${API_PREFIX}/jobs/${jobId}/restore`, { headers: auth(dosenTok) })
    expect(asDosen.status(), 'dosen restore job orang lain → 403').toBe(403)

    const asAdmin = await ctx.post(`${API_PREFIX}/jobs/${jobId}/restore`, { headers: auth(adminTok) })
    expect(asAdmin.status(), 'admin biasa boleh MENOLONG restore job mahasiswa').toBe(200)
    expect((await asAdmin.json()).deleted_at, 'deleted_at kosong lagi').toBeNull()
  })

  test('TC-TRASH-05 Owner restore sendiri juga bisa (bolak-balik konsisten)', async () => {
    // Hapus lagi lalu restore oleh owner sendiri.
    await ctx.delete(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(studentTok) })
    const res = await ctx.post(`${API_PREFIX}/jobs/${jobId}/restore`, { headers: auth(studentTok) })
    expect(res.status(), 'owner restore miliknya → 200').toBe(200)
  })

  test('TC-TRASH-06 Purge: admin biasa & owner DILARANG; super admin BOLEH (permanen)', async () => {
    const asAdmin = await ctx.delete(`${API_PREFIX}/jobs/${jobId}/purge`, { headers: auth(adminTok) })
    expect(asAdmin.status(), 'admin biasa purge → 403').toBe(403)
    const asOwner = await ctx.delete(`${API_PREFIX}/jobs/${jobId}/purge`, { headers: auth(studentTok) })
    expect(asOwner.status(), 'owner (mahasiswa) purge → 403').toBe(403)

    test.skip(!superOk, 'Token super admin tak sah (tak ada sesi aktif) — purge dilewati sah.')
    const purge = await ctx.delete(`${API_PREFIX}/jobs/${jobId}/purge`, { headers: auth(superTok) })
    expect(purge.status(), 'super admin purge → 204').toBe(204)
    const gone = await ctx.get(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(studentTok) })
    expect(gone.status(), 'job hilang permanen → 404').toBe(404)
    jobId = 0 // sudah bersih — afterAll tak perlu apa-apa
  })
})
