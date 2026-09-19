import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import { API_PREFIX, ADMIN_STATE, STUDENT_STATE } from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * KLASIFIKASI LAPORAN "Pengguna Server (OS)": akun sistem/layanan/container WAJIB
 * ditandai `is_system=true` supaya tersembunyi dari daftar utama (fix d3ce675/dc3e5b3).
 *
 * Aturan backend (report.py):
 *  - username NUMERIK (UID container tanpa entri passwd host, mis. 65535/65532/10001) → sistem.
 *  - akun nologin (nobody, slurm, www-data, ...) → sistem.
 *  - UID < 1000 (root, systemd-*, sshd, ...) → sistem.
 *  - proses infra (pause, coredns, kube.., node_exporter, slurm..) → sistem.
 * User manusia (folder /home) TIDAK boleh tersembunyi.
 */

let ctx: APIRequestContext
let adminTok = ''

interface OsUser {
  username: string
  is_system: boolean
}
interface Proc {
  username: string
  name: string
  is_system: boolean
}

test.beforeAll(async () => {
  ctx = await pwRequest.newContext()
  adminTok = tokenFromState(ADMIN_STATE)
})

test.afterAll(async () => {
  await ctx.dispose()
})

test.describe('Laporan: klasifikasi akun sistem vs user manusia', () => {
  test('TC-REPORT-01 username numerik & akun layanan bertanda is_system', async () => {
    const res = await ctx.get(`${API_PREFIX}/admin/report`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    expect(res.status(), 'admin boleh /admin/report').toBe(200)
    const body = (await res.json()) as { os_users: OsUser[]; top_processes: Proc[] }

    expect(Array.isArray(body.os_users)).toBeTruthy()
    // (1) SEMUA username numerik (UID container) harus is_system=true.
    const numeric = body.os_users.filter((u) => /^\d+$/.test(u.username))
    for (const u of numeric) {
      expect(u.is_system, `UID container "${u.username}" tersembunyi (is_system)`).toBe(true)
    }
    // (2) Akun layanan terkenal (bila muncul) harus is_system=true.
    for (const name of ['nobody', 'slurm', 'root', 'www-data']) {
      const u = body.os_users.find((x) => x.username === name)
      if (u) expect(u.is_system, `akun layanan "${name}" tersembunyi`).toBe(true)
    }
    // (3) Minimal ada 1 user NON-sistem (manusia) — daftar utama tidak kosong.
    expect(
      body.os_users.some((u) => !u.is_system),
      'ada user manusia yang tampil di daftar utama',
    ).toBeTruthy()
  })

  test('TC-REPORT-02 proses infrastruktur (pause/coredns/kube/slurm) bertanda is_system', async () => {
    const res = await ctx.get(`${API_PREFIX}/admin/report`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    expect(res.status()).toBe(200)
    const body = (await res.json()) as { top_processes: Proc[] }
    const infra = body.top_processes.filter((p) =>
      /^(pause|coredns|kube|node_exporter|slurm|containerd)/i.test(p.name || ''),
    )
    for (const p of infra) {
      expect(p.is_system, `proses infra "${p.name}" (user ${p.username}) is_system`).toBe(true)
    }
  })
})

test.describe('Batas Linux: snapshot sistem baca-saja', () => {
  test('TC-LINUX-01 admin membaca batas aktif tanpa nilai pengganti', async () => {
    const res = await ctx.get(`${API_PREFIX}/admin/linux-accounts/limits`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    })
    expect(res.status()).toBe(200)
    expect(res.headers()['cache-control']).toBe('no-store')
    const body = await res.json()
    expect(body.read_only).toBe(true)
    expect(body.source).toBe('cgroup_v2')
    expect(body.available).toBe(true)
    expect(Number.isFinite(Date.parse(body.collected_at))).toBe(true)
    expect(body.users.length).toBeGreaterThan(0)
    for (const account of body.users) {
      expect(account.uid).toBeGreaterThanOrEqual(1000)
      expect(account.cgroup).toBe(`/user.slice/user-${account.uid}.slice`)
      if (!account.active) {
        expect(account.limits).toBeNull()
        continue
      }
      for (const key of ['cpu_cores', 'memory_high_bytes', 'memory_max_bytes', 'tasks']) {
        const limit = account.limits[key]
        expect(['limited', 'unlimited', 'unavailable']).toContain(limit.state)
        if (limit.state === 'limited') {
          expect(limit.value).toBeGreaterThanOrEqual(0)
          expect(limit.source).toMatch(/^\/user\.slice/)
        } else {
          expect(limit.value).toBeNull()
        }
      }
    }
  })

  test('TC-LINUX-02 informasi akun Linux tertutup untuk mahasiswa dan pengunjung', async () => {
    const anonymous = await ctx.get(`${API_PREFIX}/admin/linux-accounts/limits`)
    expect(anonymous.status()).toBe(401)
    const student = await ctx.get(`${API_PREFIX}/admin/linux-accounts/limits`, {
      headers: { Authorization: `Bearer ${tokenFromState(STUDENT_STATE)}` },
    })
    expect(student.status()).toBe(403)
  })

  test('TC-LINUX-03 endpoint tulis ditolak sebelum menyentuh systemd (RBAC + konfirmasi)', async () => {
    // Semua kasus di bawah gagal di gerbang otorisasi/validasi -> TIDAK ada perubahan OS.
    const body = { data: { cpu_cores: 1, confirm_username: 'x' } }
    const url = `${API_PREFIX}/admin/linux-accounts/1015/limits`
    expect((await ctx.put(url, body)).status()).toBe(401)
    expect((await ctx.put(url, { ...body, headers: { Authorization: `Bearer ${tokenFromState(STUDENT_STATE)}` } })).status()).toBe(403)
    expect((await ctx.delete(url, { headers: { Authorization: `Bearer ${tokenFromState(STUDENT_STATE)}` } })).status()).toBe(403)
    // Admin biasa (bukan administrator utama) juga ditolak walau fitur aktif.
    const admin = await ctx.put(url, { ...body, headers: { Authorization: `Bearer ${adminTok}` } })
    expect([403]).toContain(admin.status())
    // Akun sistem (uid 0) tak boleh disentuh siapa pun.
    const root = await ctx.put(`${API_PREFIX}/admin/linux-accounts/0/limits`, { ...body, headers: { Authorization: `Bearer ${adminTok}` } })
    expect([400, 403]).toContain(root.status())
  })
})
