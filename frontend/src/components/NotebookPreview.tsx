// Penampil & EDITOR .ipynb ala Jupyter/VS Code. Mode BACA: sel markdown ter-render +
// sel kode beserta OUTPUT-nya (teks/gambar/grafik/HTML/error). Mode EDIT (job selesai /
// file bisa ditulis): ubah source tiap sel LANGSUNG di tampilan notebook, tambah/hapus
// sel, lalu Simpan -> di-serialisasi jadi JSON .ipynb yang VALID. Dipakai di detail job
// & explorer Notebook Interaktif saat membuka berkas .ipynb.
import { useEffect, useRef, useState } from 'react'

import CodeEditor from './CodeEditor'
import { parseNotebookFull, serializeNotebook, type ParsedFullCell } from '../lib/ipynb'
import { renderMarkdown } from '../lib/markdown'
import { IconX } from './icons'
import { OutputView } from './NotebookOutput'

export default function NotebookPreview({
  content,
  editable = false,
  onSave,
  onEditRaw,
}: {
  content: string
  editable?: boolean
  onSave?: (content: string) => void
  onEditRaw?: () => void
}) {
  const [cells, setCells] = useState<ParsedFullCell[] | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saved, setSaved] = useState(false)
  // Konten hasil "Simpan" kita sendiri -> jangan di-parse ulang (agar edit tak ter-reset).
  const lastEmittedRef = useRef<string | null>(null)

  useEffect(() => {
    if (content === lastEmittedRef.current) return
    try {
      setCells(parseNotebookFull(content))
      setParseError(null)
    } catch (e) {
      setCells(null)
      setParseError(e instanceof Error ? e.message : 'Gagal membaca notebook.')
    }
    setDirty(false)
  }, [content])

  const update = (i: number, src: string) => {
    setCells((cs) => (cs ? cs.map((c, j) => (j === i ? { ...c, source: src } : c)) : cs))
    setDirty(true)
    setSaved(false)
  }
  const addCell = (kind: 'code' | 'markdown') => {
    setCells((cs) => [...(cs ?? []), { kind, source: '', execCount: null, outputs: [] }])
    setDirty(true)
    setSaved(false)
  }
  const removeCell = (i: number) => {
    setCells((cs) => (cs ? cs.filter((_, j) => j !== i) : cs))
    setDirty(true)
    setSaved(false)
  }
  const save = () => {
    if (!cells) return
    const json = serializeNotebook(cells)
    lastEmittedRef.current = json
    onSave?.(json)
    setDirty(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  if (parseError) {
    // Notebook rusak/kosong -> pesan jelas + (bila bisa diedit) arahkan ke tab mentah.
    return (
      <div className="p-4 text-xs">
        <div className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-amber-700">
          <p className="font-semibold">Tidak bisa ditampilkan sebagai notebook.</p>
          <p className="mt-0.5">
            {parseError} Berkas ini bukan .ipynb yang valid, jadi sel-selnya tak dapat
            dirender.{editable && onEditRaw ? ' Perbaiki JSON-nya di tab "Kode mentah".' : ''}
          </p>
          {editable && onEditRaw && (
            <button
              onClick={onEditRaw}
              className="mt-2 rounded-md bg-amber-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-amber-500"
            >
              Buka di Kode mentah
            </button>
          )}
        </div>
        <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 font-mono text-[11px] text-slate-600 ring-1 ring-slate-100">
          {content}
        </pre>
      </div>
    )
  }

  if (!cells) return null

  return (
    <div>
      {editable && (
        <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-100 bg-white/95 px-3 py-2 backdrop-blur">
          <span className="text-[11px] text-slate-400">
            Edit langsung di notebook — {cells.length} sel
          </span>
          <span className="flex-1" />
          <button
            onClick={() => addCell('code')}
            className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
          >
            + Sel kode
          </button>
          <button
            onClick={() => addCell('markdown')}
            className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
          >
            + Sel teks
          </button>
          <button
            onClick={save}
            disabled={!dirty}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-40"
          >
            {saved ? '✓ Tersimpan' : 'Simpan'}
          </button>
        </div>
      )}
      <div className="space-y-3 p-3">
        {cells.map((cell, i) => (
          <NbCell
            key={i}
            cell={cell}
            editable={editable}
            onChange={(src) => update(i, src)}
            onDelete={() => removeCell(i)}
          />
        ))}
      </div>
    </div>
  )
}

// Satu sel notebook ala Colab/VS Code: gutter nomor eksekusi + editor Monaco (berwarna),
// dengan OUTPUT ter-render di BAWAH kode. Mode baca = read-only; mode edit = bisa diubah
// + hapus sel. Dipakai sama di detail job, explorer interaktif, & Penyimpanan.
function NbCell({
  cell,
  editable,
  onChange,
  onDelete,
}: {
  cell: ParsedFullCell
  editable: boolean
  onChange: (src: string) => void
  onDelete: () => void
}) {
  const isMd = cell.kind === 'markdown'
  const label = isMd ? 'md' : cell.execCount != null ? `[${cell.execCount}]` : '[ ]'
  const showRendered = isMd && !editable // markdown read-only -> tampilkan hasil render

  return (
    <div className="group overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200 transition focus-within:ring-brand-400">
      <div className="flex">
        {/* Gutter: nomor eksekusi / penanda markdown (ala 'In [n]:') */}
        <div className="flex w-11 shrink-0 flex-col items-center border-r border-slate-100 bg-slate-50/70 py-2.5">
          <span className="font-mono text-[10px] text-slate-400">{label}</span>
        </div>

        {/* Konten sel */}
        <div className="min-w-0 flex-1">
          {showRendered ? (
            cell.source.trim() ? (
              <div
                className="md-body px-4 py-3"
                // Aman: HTML di-escape lebih dulu di renderMarkdown().
                dangerouslySetInnerHTML={{ __html: renderMarkdown(cell.source) }}
              />
            ) : (
              <p className="px-4 py-3 text-sm italic text-slate-400">Sel markdown kosong.</p>
            )
          ) : (
            <CodeEditor
              autoGrow
              minHeight={52}
              maxHeight={560}
              language={isMd ? 'markdown' : 'python'}
              value={cell.source}
              onChange={onChange}
              readOnly={!editable}
              lint={editable && !isMd}
              summaryMode={editable && !isMd ? 'problems-only' : 'hidden'}
            />
          )}
          {/* Pratinjau markdown saat mengedit */}
          {isMd && editable && cell.source.trim() && (
            <div
              className="md-body border-t border-slate-100 px-4 py-2"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(cell.source) }}
            />
          )}
        </div>

        {/* Aksi sel (hapus) — hanya mode edit */}
        {editable && (
          <div className="flex w-8 shrink-0 flex-col items-center py-2 opacity-0 transition group-hover:opacity-100">
            <button
              onClick={onDelete}
              title="Hapus sel"
              className="grid h-6 w-6 place-items-center rounded text-slate-400 hover:bg-rose-50 hover:text-rose-600"
            >
              <IconX className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* OUTPUT sel kode (teks/gambar/grafik/HTML/error) — tampil di BAWAH kode */}
      {!isMd && cell.outputs.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/40">
          {cell.outputs.map((o, j) => (
            <OutputView key={j} out={o} />
          ))}
        </div>
      )}
    </div>
  )
}
