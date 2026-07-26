import { test, expect } from '@playwright/test'

import {
  API_PREFIX,
  ADMIN_STATE,
  SUPERADMIN_STATE,
  STUDENT_STATE,
  DOSEN_STATE,
} from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * MODE PEMELIHARAAN — menahan pekerjaan BARU tanpa mengganggu yang berjalan.
 *
 * Yang diuji:
 *  - Hanya administrator utama yang boleh menyalakan/mematikan (dosen & mahasiswa 403).
 *  - Saat aktif: submit job & sesi interaktif BARU ditolak 503 untuk non-admin,
 *    sedangkan admin TETAP boleh (agar bisa uji coba setelah pemeliharaan).
 *  - Endpoint BACA (daftar job) tetap normal — pemeliharaan tidak boleh
 *    membuat platform tampak rusak.
 *  - `/system/announcement` menyiarkan alasannya supaya banner muncul.
 *  - Kondisi selalu dikembalikan ke NORMAL di akhir, apa pun hasil ujinya.
 *
 * Uji ini memakai API saja (bukan UI) supaya cepat dan tidak menyentuh GPU:
 * job ditolak di gerbang pemeliharaan SEBELUM sempat dijadwalkan.
 */

const PESAN_UJI = 'Uji otomatis mode pemeliharaan — abaikan.'

const auth = (state: string) => ({ Authorization: `Bearer ${tokenFromState(state)}` })

test.describe.configure({ mode: 'serial' })

test.describe('Mode pemeliharaan (API)', () => {
  test.afterAll(async ({ request }) => {
    // Jaring pengaman: platform TIDAK boleh ditinggalkan dalam mode pemeliharaan.
    await request
      .put(`${API_PREFIX}/admin/maintenance-mode`, {
        headers: auth(SUPERADMIN_STATE),
        data: { active: false },
      })
      .catch(() => undefined)
  })

  test('TC-MAINT-01 hanya administrator utama boleh mengubah', async ({ request }) => {
    for (const state of [STUDENT_STATE, DOSEN_STATE]) {
      const res = await request.put(`${API_PREFIX}/admin/maintenance-mode`, {
        headers: auth(state),
        data: { active: true },
      })
      expect([401, 403], 'non-admin DILARANG mengubah').toContain(res.status())
    }
    const baca = await request.get(`${API_PREFIX}/admin/maintenance-mode`, {
      headers: auth(STUDENT_STATE),
    })
    expect([401, 403], 'mahasiswa DILARANG membaca').toContain(baca.status())
  })

  test('TC-MAINT-02 aktif → pekerjaan baru ditahan, admin tetap bisa', async ({
    request,
  }) => {
    const nyala = await request.put(`${API_PREFIX}/admin/maintenance-mode`, {
      headers: auth(SUPERADMIN_STATE),
      data: { active: true, message: PESAN_UJI },
    })
    test.skip(
      nyala.status() === 401,
      'Token super admin tak sah (tidak ada sesi aktif) — dilewati secara sah.',
    )
    expect(nyala.status(), 'super admin boleh menyalakan').toBe(200)
    expect((await nyala.json()).active, 'status aktif').toBeTruthy()

    // Mahasiswa: submit job BARU ditolak 503 dengan alasan yang bisa dibaca.
    const job = await request.post(`${API_PREFIX}/jobs`, {
      headers: auth(STUDENT_STATE),
      data: { source_type: 'paste', code: 'print("uji pemeliharaan")' },
    })
    expect(job.status(), 'job baru ditahan').toBe(503)
    expect(String((await job.json()).detail), 'alasan dijelaskan').toContain(
      'pemeliharaan',
    )

    // Mahasiswa: sesi interaktif BARU juga ditahan (jangan sampai ada celah).
    const sesi = await request.post(`${API_PREFIX}/interactive/sessions`, {
      headers: auth(STUDENT_STATE),
    })
    expect(sesi.status(), 'sesi interaktif baru ditahan').toBe(503)

    // Membaca data tetap normal — platform tidak boleh tampak rusak.
    const daftar = await request.get(`${API_PREFIX}/jobs`, {
      headers: auth(STUDENT_STATE),
    })
    expect(daftar.status(), 'daftar job tetap bisa dibuka').toBe(200)

    // Admin TETAP boleh mengirim (untuk uji coba setelah pemeliharaan).
    // Sengaja job CPU sepele agar tidak menyentuh GPU dan selesai seketika.
    const jobAdmin = await request.post(`${API_PREFIX}/jobs`, {
      headers: auth(ADMIN_STATE),
      data: {
        source_type: 'paste',
        code: 'print("uji bypass admin")',
        device: 'cpu',
      },
    })
    expect(jobAdmin.status(), 'admin tidak ikut ditahan').toBe(201)

    // Banner: alasan disiarkan ke semua pengguna.
    const ann = await request.get(`${API_PREFIX}/system/announcement`, {
      headers: auth(STUDENT_STATE),
    })
    expect(ann.status()).toBe(200)
    const body = await ann.json()
    expect(body.maintenance, 'penanda pemeliharaan').toBeTruthy()
    expect(String(body.text), 'pesan admin dipakai').toContain(PESAN_UJI)
  })

  test('TC-MAINT-03 dimatikan → platform normal kembali', async ({ request }) => {
    const mati = await request.put(`${API_PREFIX}/admin/maintenance-mode`, {
      headers: auth(SUPERADMIN_STATE),
      data: { active: false },
    })
    test.skip(
      mati.status() === 401,
      'Token super admin tak sah (tidak ada sesi aktif) — dilewati secara sah.',
    )
    expect(mati.status()).toBe(200)
    expect((await mati.json()).active, 'sudah nonaktif').toBeFalsy()

    const ann = await request.get(`${API_PREFIX}/system/announcement`, {
      headers: auth(STUDENT_STATE),
    })
    expect((await ann.json()).maintenance, 'penanda hilang').toBeFalsy()

    // Job baru boleh masuk lagi (job CPU sepele, langsung dibatalkan).
    const job = await request.post(`${API_PREFIX}/jobs`, {
      headers: auth(STUDENT_STATE),
      data: { source_type: 'paste', code: 'print("normal")', device: 'cpu' },
    })
    expect(job.status(), 'job diterima kembali').toBe(201)
    const id = (await job.json()).id
    await request.post(`${API_PREFIX}/jobs/${id}/cancel`, {
      headers: auth(STUDENT_STATE),
    })
  })
})
