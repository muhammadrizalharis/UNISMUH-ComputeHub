import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import { API_PREFIX, ADMIN_STATE, STUDENT_STATE } from '../utils/constants'
import { readInfo, tokenFromState } from '../utils/helpers'

/**
 * Enforcement KUOTA DISK /persist. Non-destruktif:
 *  - Kuota di-set SEMENTARA pada akun student UJI (oleh admin), lalu DIKEMBALIKAN ke
 *    nilai asal di afterAll (walau tes gagal).
 *  - Upload yang ditolak TIDAK meninggalkan berkas (rejeksi bersih di backend).
 *  - Kuota storage kini dapat diatur admin & super admin (bukan super admin saja).
 *
 * MODE LUNAK (SOFT_LIMIT_ENABLED, 2026-07-20): saat aktif, lewat kuota per-user TIDAK
 * ditolak (hanya peringatan email; disk fisik tetap dijaga headroom) → ekspektasi
 * uji bercabang sesuai mode nyata (dibaca dari backend/.env di mesin yang sama).
 */

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** Baca flag SOFT_LIMIT_ENABLED dari backend/.env (default False sesuai config.py). */
function softLimitEnabled(): boolean {
  try {
    const env = readFileSync(path.resolve(__dirname, '..', '..', 'backend', '.env'), 'utf-8')
    const m = env.match(/^\s*SOFT_LIMIT_ENABLED\s*=\s*(\S+)\s*$/m)
    return m ? /^(true|1|yes)$/i.test(m[1]) : false
  } catch {
    return false
  }
}
const SOFT = softLimitEnabled()

let adminTok = ''
let studentTok = ''
let studentId = 0
let origQuota: number | null = null
let baselineQuota: number | null = null
let ctx: APIRequestContext

const auth = (t: string) => ({ Authorization: `Bearer ${t}` })
const policyUrl = () => `${API_PREFIX}/admin/users/${studentId}/policy`

async function workspaceQuota(tok: string): Promise<number | null> {
  const r = await ctx.get(`${API_PREFIX}/interactive/workspace`, { headers: auth(tok) })
  return r.ok() ? ((await r.json()).quota_mb as number) : null
}

test.beforeAll(async () => {
  adminTok = tokenFromState(ADMIN_STATE)
  studentTok = tokenFromState(STUDENT_STATE)
  studentId = readInfo().student.id
  ctx = await pwRequest.newContext()
  const r = await ctx.get(policyUrl(), { headers: auth(adminTok) })
  if (r.status() === 200) origQuota = (((await r.json()).overrides?.max_storage_mb) ?? null) as number | null
  // Kuota efektif default (global) sblm override — utk verifikasi "clear -> balik default".
  baselineQuota = await workspaceQuota(studentTok)
})

test.afterAll(async () => {
  // Kembalikan kuota ke nilai asal (bersih; tak meninggalkan batas di akun student).
  try {
    await ctx.patch(policyUrl(), { headers: auth(adminTok), data: { max_storage_mb: origQuota } })
  } finally {
    await ctx.dispose()
  }
})

test.describe('Kuota disk /persist (enforcement)', () => {
  test('TC-QUOTA-01 Admin set kuota → upload melebihi: ditolak (hard) / diterima+alert (soft)', async () => {
    // 1) Baseline: admin dapat membaca policy student.
    const base = await ctx.get(policyUrl(), { headers: auth(adminTok) })
    expect(base.status(), 'admin baca policy student').toBe(200)

    // 2) Set kuota kecil 1 MB pada akun student uji.
    const set = await ctx.patch(policyUrl(), {
      headers: auth(adminTok),
      data: { max_storage_mb: 1 },
    })
    expect(set.status(), 'admin boleh set max_storage_mb').toBe(200)
    expect((await set.json()).overrides.max_storage_mb).toBe(1)

    // 3) Kuota efektif tampil di workspace student (jalur effective() hidup).
    expect(await workspaceQuota(studentTok), 'quota_mb di workspace student').toBe(1)

    // 4) Upload > 1 MB sebagai student.
    const bigName = 'qa_big.bin'
    const res = await ctx.post(`${API_PREFIX}/interactive/workspace/upload`, {
      headers: auth(studentTok),
      multipart: {
        file: {
          name: bigName,
          mimeType: 'application/octet-stream',
          buffer: Buffer.alloc(2 * 1024 * 1024),
        },
      },
    })
    if (SOFT) {
      // MODE LUNAK: tidak ditolak — upload diterima (kuota jadi peringatan email saja).
      expect([200, 201], 'soft mode: upload melebihi kuota TETAP diterima').toContain(res.status())
      // Bersihkan berkas uji.
      await ctx.delete(
        `${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(bigName)}`,
        { headers: auth(studentTok) },
      )
    } else {
      // MODE KERAS: DITOLAK 400 dengan pesan kuota.
      expect(res.status(), 'hard mode: upload melebihi kuota ditolak').toBe(400)
      expect(String((await res.json()).detail), 'pesan menyebut kuota').toMatch(/kuota/i)
      // Berkas yang ditolak TIDAK tertinggal di workspace (rejeksi bersih).
      const chk = await ctx.get(
        `${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(bigName)}`,
        { headers: auth(studentTok) },
      )
      expect([400, 404], 'berkas tak tersimpan').toContain(chk.status())
    }
  })

  test('TC-QUOTA-02 Kuota clear → upload kecil kembali diterima', async () => {
    // Clear kuota (override null → balik ke default global).
    const clr = await ctx.patch(policyUrl(), {
      headers: auth(adminTok),
      data: { max_storage_mb: null },
    })
    expect(clr.status()).toBe(200)
    expect(await workspaceQuota(studentTok), 'kuota kembali ke default global').toBe(baselineQuota)

    // Upload kecil (< batas file 256MB) diterima kembali; lalu dibersihkan.
    const name = `qa_small_${Date.now()}.txt`
    const up = await ctx.post(`${API_PREFIX}/interactive/workspace/upload`, {
      headers: auth(studentTok),
      multipart: {
        file: { name, mimeType: 'text/plain', buffer: Buffer.from('halo QA\n') },
      },
    })
    expect([200, 201], 'upload kecil diterima').toContain(up.status())
    // Bersihkan berkas uji.
    await ctx.delete(
      `${API_PREFIX}/interactive/workspace/file?path=${encodeURIComponent(name)}`,
      { headers: auth(studentTok) },
    )
  })
})
