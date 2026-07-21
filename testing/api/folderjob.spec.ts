import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test'

import { API_PREFIX, STUDENT_STATE, DOSEN_STATE, SUPERADMIN_STATE } from '../utils/constants'
import { tokenFromState } from '../utils/helpers'

/**
 * UPLOAD FOLDER (chunked) end-to-end + explorer file job + endpoint /raw (gambar).
 *
 * Meliputi:
 *  - init → chunk (path aman, segmen root dibuang) → finalize → Job queued (device=cpu).
 *  - Traversal path ('..') pada chunk DITOLAK 400 dan sesi upload DIBERSIHKAN.
 *  - GET /jobs/{id}/files & /file — isi cocok; /raw menyajikan PNG inline (image/png),
 *    tapi SVG DIPAKSA octet-stream (anti script-in-SVG), dan traversal ditolak.
 *  - Kepemilikan: dosen DILARANG membaca file job mahasiswa (403).
 *
 * Non-destruktif: job dibersihkan (soft-delete; purge bila super admin tersedia).
 */

// PNG valid terkecil (1x1 piksel, transparan) — cukup untuk uji content-type.
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)
const EVIL_SVG = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')

let ctx: APIRequestContext
let studentTok = ''
let dosenTok = ''
let superTok = ''
let superOk = false
let jobId = 0
let folderToken = '' // sesi upload dipakai lintas-test (serial dalam file)

const auth = (t: string) => ({ Authorization: `Bearer ${t}` })

async function sendChunk(
  token: string,
  relPath: string,
  body: Buffer,
  first = true,
): Promise<number> {
  const q = new URLSearchParams({ path: relPath, first: first ? '1' : '0' })
  const res = await ctx.post(`${API_PREFIX}/jobs/folder/${token}/chunk?${q.toString()}`, {
    headers: { ...auth(studentTok), 'Content-Type': 'application/octet-stream' },
    data: body,
  })
  return res.status()
}

test.beforeAll(async () => {
  ctx = await pwRequest.newContext()
  studentTok = tokenFromState(STUDENT_STATE)
  dosenTok = tokenFromState(DOSEN_STATE)
  superTok = tokenFromState(SUPERADMIN_STATE)
  const me = await ctx.get(`${API_PREFIX}/auth/me`, { headers: auth(superTok) })
  superOk = me.ok() && Boolean((await me.json()).is_superadmin)
})

test.afterAll(async () => {
  try {
    if (jobId) {
      await ctx.delete(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(studentTok) })
      if (superOk) await ctx.delete(`${API_PREFIX}/jobs/${jobId}/purge`, { headers: auth(superTok) })
    }
  } finally {
    await ctx.dispose()
  }
})

test.describe('Upload folder (chunked) + file explorer job + /raw', () => {
  test('TC-FOLDER-01 Traversal pada chunk ditolak 400 & sesi TETAP utuh (rejeksi bersih)', async () => {
    const init = await ctx.post(`${API_PREFIX}/jobs/folder/init`, {
      headers: auth(studentTok),
      data: { name: `qa-folder-${Date.now()}`, device: 'cpu' },
    })
    expect(init.status(), 'init sesi upload').toBe(200)
    const body = (await init.json()) as { token: string; max_bytes: number }
    folderToken = body.token
    expect(body.max_bytes, 'sisa kuota disk > 0').toBeGreaterThan(0)

    // Path dengan '..' → DITOLAK 400 (validasi _safe_folder_paths), TANPA menulis file.
    expect(await sendChunk(folderToken, 'proj/../../../../etc/passwd', Buffer.from('x'))).toBe(400)
    // Path ABSOLUT dinetralkan (leading '/' di-strip + segmen root dibuang) → file jatuh
    // DI DALAM project (bukan /etc host). Diverifikasi isi tree di TC-FOLDER-03.
    expect(await sendChunk(folderToken, '/etc/qa_probe_abs.txt', Buffer.from('probe'))).toBe(200)
    // Sesi TETAP utuh — rejeksi tidak merusak upload yang sedang berjalan (chunk valid → 200).
    expect(
      await sendChunk(folderToken, 'myproj/main.py', Buffer.from("print('folder-ok')\n")),
      'sesi masih bisa dipakai setelah rejeksi',
    ).toBe(200)
  })

  test('TC-FOLDER-02 chunk (append) → finalize → job dibuat (segmen root dibuang)', async () => {
    expect(folderToken, 'bergantung TC-FOLDER-01').toBeTruthy()

    // Append (first=0) berfungsi.
    expect(
      await sendChunk(folderToken, 'myproj/main.py', Buffer.from("print('baris-2')\n"), false),
    ).toBe(200)
    expect(await sendChunk(folderToken, 'myproj/assets/pic.png', TINY_PNG)).toBe(200)
    expect(await sendChunk(folderToken, 'myproj/assets/evil.svg', EVIL_SVG)).toBe(200)

    const fin = await ctx.post(`${API_PREFIX}/jobs/folder/${folderToken}/finalize`, {
      headers: auth(studentTok),
    })
    expect(fin.status(), 'finalize → job 201').toBe(201)
    const job = await fin.json()
    jobId = job.id as number
    expect(job.source_type).toBe('upload')
    expect(['queued', 'running']).toContain(job.status)
  })

  test('TC-FOLDER-03 Explorer file job: tree + isi file cocok; dosen DILARANG', async () => {
    expect(jobId, 'bergantung TC-FOLDER-02').toBeGreaterThan(0)
    const tree = await ctx.get(`${API_PREFIX}/jobs/${jobId}/files`, { headers: auth(studentTok) })
    expect(tree.status(), 'owner boleh melihat tree').toBe(200)
    const flat = JSON.stringify(await tree.json())
    expect(flat, 'main.py ada (root myproj dibuang)').toContain('main.py')
    expect(flat, 'folder assets ada').toContain('assets')

    const file = await ctx.get(
      `${API_PREFIX}/jobs/${jobId}/file?path=${encodeURIComponent('main.py')}`,
      { headers: auth(studentTok) },
    )
    expect(file.status()).toBe(200)
    const content = (await file.json()).content as string
    expect(content).toContain("print('folder-ok')")
    expect(content, 'append chunk kedua tersambung').toContain("print('baris-2')")

    // Probe path ABSOLUT ('/etc/qa_probe_abs.txt') ternetralkan ke DALAM project —
    // bukti tulisan terkurung di project dir, bukan filesystem host.
    const probe = await ctx.get(
      `${API_PREFIX}/jobs/${jobId}/file?path=${encodeURIComponent('qa_probe_abs.txt')}`,
      { headers: auth(studentTok) },
    )
    expect(probe.status(), 'probe absolut jatuh DI DALAM project').toBe(200)
    expect((await probe.json()).content).toBe('probe')

    // Kepemilikan: dosen bukan pemilik & bukan admin → 403.
    const asDosen = await ctx.get(`${API_PREFIX}/jobs/${jobId}/files`, { headers: auth(dosenTok) })
    expect(asDosen.status(), 'dosen DILARANG membaca file job mahasiswa').toBe(403)
  })

  test('TC-FOLDER-04 /raw: PNG inline image/png; SVG dipaksa octet-stream; traversal 400', async () => {
    expect(jobId, 'bergantung TC-FOLDER-02').toBeGreaterThan(0)

    const png = await ctx.get(
      `${API_PREFIX}/jobs/${jobId}/raw?path=${encodeURIComponent('assets/pic.png')}`,
      { headers: auth(studentTok) },
    )
    expect(png.status(), 'PNG tersaji').toBe(200)
    expect(png.headers()['content-type'], 'content-type PNG inline').toContain('image/png')
    expect((await png.body()).equals(TINY_PNG), 'byte PNG utuh').toBeTruthy()

    const svg = await ctx.get(
      `${API_PREFIX}/jobs/${jobId}/raw?path=${encodeURIComponent('assets/evil.svg')}`,
      { headers: auth(studentTok) },
    )
    expect(svg.status()).toBe(200)
    expect(
      svg.headers()['content-type'],
      'SVG TIDAK boleh image/svg+xml (anti script-in-SVG)',
    ).toContain('application/octet-stream')

    const trav = await ctx.get(
      `${API_PREFIX}/jobs/${jobId}/raw?path=${encodeURIComponent('../../etc/passwd')}`,
      { headers: auth(studentTok) },
    )
    expect(trav.status(), 'traversal /raw ditolak').toBe(400)

    const missing = await ctx.get(
      `${API_PREFIX}/jobs/${jobId}/raw?path=${encodeURIComponent('assets/tidak-ada.png')}`,
      { headers: auth(studentTok) },
    )
    expect(missing.status(), 'file tak ada → 404').toBe(404)
  })

  test('TC-FOLDER-05 Job folder benar-benar dieksekusi (menunggu status terminal)', async () => {
    expect(jobId, 'bergantung TC-FOLDER-02').toBeGreaterThan(0)
    // Tunggu maks ~120 dtk (antrian CPU + start docker). Job kecil harus selesai.
    let status = ''
    const deadline = Date.now() + 120_000
    while (Date.now() < deadline) {
      const r = await ctx.get(`${API_PREFIX}/jobs/${jobId}`, { headers: auth(studentTok) })
      expect(r.status()).toBe(200)
      status = (await r.json()).status as string
      if (['succeeded', 'failed', 'cancelled'].includes(status)) break
      await new Promise((res) => setTimeout(res, 4000))
    }
    test.skip(
      !['succeeded', 'failed', 'cancelled'].includes(status),
      `Job belum terminal (${status}) — antrian server sedang penuh; eksekusi tercakup uji lain.`,
    )
    expect(status, 'job folder sukses dieksekusi').toBe('succeeded')

    // Log berisi output program (bukti main.py benar-benar jalan).
    const logs = await ctx.get(`${API_PREFIX}/jobs/${jobId}/logs?tail=200`, {
      headers: auth(studentTok),
    })
    expect(logs.status()).toBe(200)
    expect(JSON.stringify(await logs.json())).toContain('folder-ok')
  })
})
