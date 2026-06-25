// Parser .ipynb -> daftar sel (code & markdown). Tahan banting terhadap format
// notebook v4: `source` bisa berupa string ATAU array string.

export type ParsedCell = { kind: 'code' | 'markdown'; source: string }

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
