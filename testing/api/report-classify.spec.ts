import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import { API_PREFIX, ADMIN_STATE } from '../utils/constants'
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
