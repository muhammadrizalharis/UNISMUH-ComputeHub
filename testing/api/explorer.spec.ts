// Uji ALUR NYATA explorer notebook interaktif: buat sesi, unggah berkas ke
// subfolder, salin path (cwd), pindahkan berkas antar folder, lalu bersihkan.
import { test, expect, type APIRequestContext } from '@playwright/test'

import { API_PREFIX, STUDENT_STATE } from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

let auth: Record<string, string>
let sid = ''

async function tree(ctx: APIRequestContext) {
  const r = await ctx.get(`${API_PREFIX}/interactive/sessions/${sid}/files`, { headers: auth })
  expect(r.status(), 'baca tree').toBe(200)
  return (await r.json()) as {
    cwd?: string
    tree: { children?: { name: string; path: string; type: string; children?: unknown[] }[] }
  }
}

function namaDi(t: Awaited<ReturnType<typeof tree>>, dir: string): string[] {
  const cari = (
    node: { name: string; path: string; type: string; children?: unknown[] },
  ): string[] => {
    if (node.path === dir)
      return ((node.children ?? []) as { name: string }[]).map((c) => c.name)
    for (const c of (node.children ?? []) as typeof node[]) {
      const hasil = cari(c)
      if (hasil.length) return hasil
    }
    return []
  }
  if (!dir) return (t.tree.children ?? []).map((c) => c.name)
  return (t.tree.children ?? []).flatMap((c) => cari(c))
}

test.describe('Explorer notebook interaktif — unggah, path, pindah', () => {
  test.beforeAll(async ({ playwright }) => {
    auth = { Authorization: `Bearer ${tokenFromState(STUDENT_STATE)}` }
    const ctx = await playwright.request.newContext()
    const buat = await ctx.post(`${API_PREFIX}/interactive/sessions`, {
      headers: auth,
      data: { device: 'cpu' },
    })
    expect([200, 201], 'buat sesi kernel').toContain(buat.status())
    sid = ((await buat.json()) as { session_id: string }).session_id
    await ctx.dispose()
  })

  test.afterAll(async ({ playwright }) => {
    if (!sid) return
    const ctx = await playwright.request.newContext()
    await ctx.delete(`${API_PREFIX}/interactive/sessions/${sid}`, { headers: auth })
    await ctx.dispose()
  })

  test('TC-EXP-01 unggah berkas ke subfolder + cwd tersedia untuk salin path', async ({
    request,
  }) => {
    const mk = await request.post(`${API_PREFIX}/interactive/sessions/${sid}/mkdir`, {
      headers: auth,
      data: { path: 'data' },
    })
    expect(mk.status(), 'buat folder data').toBe(200)

    const naik = await request.post(
      `${API_PREFIX}/interactive/sessions/${sid}/import/chunk?path=${encodeURIComponent('data/uji.csv')}&first=1`,
      { headers: { ...auth, 'Content-Type': 'application/octet-stream' }, data: 'a,b\n1,2\n' },
    )
    expect(naik.status(), 'unggah ke subfolder').toBe(200)

    const t = await tree(request)
    expect(t.cwd, 'cwd dikirim untuk fitur salin path').toBeTruthy()
    expect(namaDi(t, 'data'), 'berkas masuk ke folder data').toContain('uji.csv')
  })

  test('TC-EXP-02 pindahkan berkas antar folder (seret & lepas)', async ({ request }) => {
    await request.post(`${API_PREFIX}/interactive/sessions/${sid}/mkdir`, {
      headers: auth,
      data: { path: 'arsip' },
    })
    const pindah = await request.post(`${API_PREFIX}/interactive/sessions/${sid}/rename`, {
      headers: auth,
      data: { path: 'data/uji.csv', new_path: 'arsip/uji.csv' },
    })
    expect(pindah.status(), 'pindah lintas folder').toBe(200)

    const t = await tree(request)
    expect(namaDi(t, 'arsip'), 'sudah di folder tujuan').toContain('uji.csv')
    expect(namaDi(t, 'data'), 'tidak tertinggal di folder asal').not.toContain('uji.csv')
  })

  test('TC-EXP-03 unggah DITOLAK bila path keluar dari project', async ({ request }) => {
    const jahat = await request.post(
      `${API_PREFIX}/interactive/sessions/${sid}/import/chunk?path=${encodeURIComponent('../../etc/passwd')}&first=1`,
      { headers: { ...auth, 'Content-Type': 'application/octet-stream' }, data: 'x' },
    )
    expect(jahat.status(), 'path traversal ditolak').toBe(400)
  })
})
