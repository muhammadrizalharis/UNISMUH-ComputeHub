// Parser .ipynb -> daftar sel (code & markdown). Tahan banting terhadap format
// notebook v4: `source` bisa berupa string ATAU array string.

export type ParsedCell = { kind: 'code' | 'markdown'; source: string }

// Tipe output sel (dipakai bersama komponen render di components/NotebookOutput).
export type OutStream = { kind: 'stream'; name: string; text: string }
export type OutResult = { kind: 'result'; data: Record<string, string> }
export type OutError = { kind: 'error'; ename: string; evalue: string; traceback: string[] }
export type CellOutput = OutStream | OutResult | OutError

export function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.replace(/\u001b\[[0-9;]*m/g, '')
}

// Terapkan carriage-return (\r) ala terminal: \r memindah kursor ke awal baris lalu
// teks berikutnya MENIMPA. Membuat progress bar (tqdm) jadi SATU baris yang berubah,
// bukan ribuan baris. Baris tanpa \r dibiarkan (cepat).
export function applyCarriageReturns(s: string): string {
  if (s.indexOf('\r') === -1) return s
  return s
    .split('\n')
    .map((line) => {
      if (line.indexOf('\r') === -1) return line
      let buf = ''
      let col = 0
      for (const ch of line) {
        if (ch === '\r') col = 0
        else {
          buf = buf.slice(0, col) + ch + buf.slice(col + 1)
          col += 1
        }
      }
      return buf
    })
    .join('\n')
}

export function parseNotebook(text: string): ParsedCell[] {
  let nb: unknown
  try {
    nb = JSON.parse(text)
  } catch {
    throw new Error('File .ipynb tidak valid (JSON rusak).')
  }
  const cells = Array.isArray((nb as { cells?: unknown[] })?.cells)
    ? (nb as { cells: unknown[] }).cells
    : []
  const out: ParsedCell[] = []
  for (const raw of cells) {
    const c = raw as { cell_type?: string; source?: unknown }
    const t = c?.cell_type
    if (t !== 'code' && t !== 'markdown') continue
    const source = Array.isArray(c.source)
      ? c.source.join('')
      : String(c.source ?? '')
    if (t === 'markdown' && !source.trim()) continue
    out.push({ kind: t, source })
  }
  if (out.length === 0) {
    throw new Error('Notebook tidak berisi sel kode/markdown.')
  }
  return out
}

// ---- Parser LENGKAP (sel + OUTPUT) untuk menampilkan .ipynb ala Jupyter/VS Code.
// Berbeda dari parseNotebook (hanya source), ini juga membaca hasil eksekusi tiap
// sel code: stream (stdout/stderr), hasil (execute_result/display_data: teks/HTML/
// gambar), dan error (traceback). Dipakai NotebookPreview (read-only) di detail job.

export type ParsedFullCell = {
  kind: 'code' | 'markdown'
  source: string
  execCount: number | null
  outputs: CellOutput[]
}

function joinSource(v: unknown): string {
  return Array.isArray(v) ? v.map((x) => String(x)).join('') : String(v ?? '')
}

// MIME yang kita render (urutan tak penting; renderer memilih yang terbaik).
const SUPPORTED_MIME = ['image/png', 'image/jpeg', 'text/html', 'text/plain'] as const

function parseOutputs(raw: unknown): CellOutput[] {
  if (!Array.isArray(raw)) return []
  const outs: CellOutput[] = []
  for (const o of raw) {
    const ob = o as {
      output_type?: string
      name?: string
      text?: unknown
      data?: Record<string, unknown>
      ename?: string
      evalue?: string
      traceback?: unknown
    }
    switch (ob?.output_type) {
      case 'stream':
        outs.push({
          kind: 'stream',
          name: ob.name === 'stderr' ? 'stderr' : 'stdout',
          text: applyCarriageReturns(joinSource(ob.text)),
        })
        break
      case 'execute_result':
      case 'display_data': {
        const data: Record<string, string> = {}
        const src = ob.data ?? {}
        for (const mime of SUPPORTED_MIME) {
          if (src[mime] == null) continue
          // Gambar disimpan base64 (kadang dipecah baris) -> rapatkan; teks di-join.
          data[mime] = mime.startsWith('image/')
            ? joinSource(src[mime]).replace(/\s+/g, '')
            : joinSource(src[mime])
        }
        if (Object.keys(data).length) outs.push({ kind: 'result', data })
        break
      }
      case 'error':
        outs.push({
          kind: 'error',
          ename: String(ob.ename ?? 'Error'),
          evalue: String(ob.evalue ?? ''),
          traceback: Array.isArray(ob.traceback) ? ob.traceback.map((x) => String(x)) : [],
        })
        break
      default:
        break
    }
  }
  return outs
}

export function parseNotebookFull(text: string): ParsedFullCell[] {
  let nb: unknown
  try {
    nb = JSON.parse(text)
  } catch {
    throw new Error('File .ipynb tidak valid (JSON rusak).')
  }
  const cells = Array.isArray((nb as { cells?: unknown[] })?.cells)
    ? (nb as { cells: unknown[] }).cells
    : []
  const out: ParsedFullCell[] = []
  for (const raw of cells) {
    const c = raw as {
      cell_type?: string
      source?: unknown
      outputs?: unknown
      execution_count?: unknown
    }
    const t = c?.cell_type
    if (t !== 'code' && t !== 'markdown') continue
    const source = joinSource(c.source)
    if (t === 'markdown') {
      if (!source.trim()) continue
      out.push({ kind: 'markdown', source, execCount: null, outputs: [] })
    } else {
      out.push({
        kind: 'code',
        source,
        execCount: typeof c.execution_count === 'number' ? c.execution_count : null,
        outputs: parseOutputs(c.outputs),
      })
    }
  }
  if (out.length === 0) {
    throw new Error('Notebook tidak berisi sel kode/markdown.')
  }
  return out
}
