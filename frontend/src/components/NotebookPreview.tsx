// Penampil & EDITOR .ipynb ala Jupyter/VS Code. Mode BACA: sel markdown ter-render +
// sel kode beserta OUTPUT-nya (teks/gambar/grafik/HTML/error). Mode EDIT (job selesai /
// file bisa ditulis): ubah source tiap sel LANGSUNG di tampilan notebook, tambah/hapus
// sel, lalu Simpan -> di-serialisasi jadi JSON .ipynb yang VALID. Dipakai di detail job
// & explorer Notebook Interaktif saat membuka berkas .ipynb.
import { useEffect, useRef, useState } from 'react'

import { cn } from '../lib/format'
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
        {cells.map((cell, i) =>
          editable ? (
            <EditableCell
              key={i}
              cell={cell}
              onChange={(src) => update(i, src)}
              onDelete={() => removeCell(i)}
            />
          ) : cell.kind === 'markdown' ? (
            <div
              key={i}
              className="md-body px-2"
              // Aman: HTML di-escape lebih dulu di renderMarkdown().
              dangerouslySetInnerHTML={{ __html: renderMarkdown(cell.source) }}
            />
          ) : (
            <ReadonlyCodeCell key={i} cell={cell} />
          ),
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ mode BACA
function ReadonlyCodeCell({ cell }: { cell: ParsedFullCell }) {
  const label = cell.execCount != null ? `[${cell.execCount}]` : '[ ]'
  return (
    <div className="overflow-hidden rounded-lg ring-1 ring-slate-200">
      <div className="flex">
        <div
          className="select-none border-r border-slate-100 bg-slate-50 px-2 py-2 font-mono text-[11px] text-brand-500"
          title="Nomor eksekusi"
        >
          {label}
        </div>
        <pre className="flex-1 overflow-x-auto bg-slate-50/60 px-3 py-2 font-mono text-xs text-slate-800">
          {cell.source || ' '}
        </pre>
      </div>
      {cell.outputs.length > 0 && (
        <div className="divide-y divide-slate-100 border-t border-slate-100 bg-white">
          {cell.outputs.map((o, j) => (
            <OutputView key={j} out={o} />
          ))}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ mode EDIT
function EditableCell({
  cell,
  onChange,
  onDelete,
}: {
  cell: ParsedFullCell
  onChange: (src: string) => void
  onDelete: () => void
}) {
  const isMd = cell.kind === 'markdown'
  return (
    <div className="group overflow-hidden rounded-lg ring-1 ring-slate-200">
      <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-2 py-1">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          {isMd ? 'Teks (Markdown)' : 'Kode'}
        </span>
        <span className="flex-1" />
        <button
          onClick={onDelete}
          title="Hapus sel"
          className="text-slate-300 opacity-0 transition hover:text-rose-600 group-hover:opacity-100"
        >
          <IconX className="h-3.5 w-3.5" />
        </button>
      </div>
      <AutoTextarea
        value={cell.source}
        onChange={onChange}
        mono={!isMd}
        placeholder={isMd ? 'Tulis teks markdown…' : 'Tulis kode Python…'}
      />
      {isMd && cell.source.trim() && (
        <div
          className="md-body border-t border-slate-100 bg-white px-3 py-2"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(cell.source) }}
        />
      )}
      {!isMd && cell.outputs.length > 0 && (
        <div className="divide-y divide-slate-100 border-t border-slate-100 bg-white">
          {cell.outputs.map((o, j) => (
            <OutputView key={j} out={o} />
          ))}
        </div>
      )}
    </div>
  )
}

// Textarea yang tinggi-nya menyesuaikan jumlah baris (3–40 baris) + bisa di-resize.
function AutoTextarea({
  value,
  onChange,
  mono,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  mono?: boolean
  placeholder?: string
}) {
  const rows = Math.min(40, Math.max(3, value.split('\n').length))
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      spellCheck={false}
      rows={rows}
      className={cn(
        'block w-full resize-y border-0 bg-white px-3 py-2 text-xs text-slate-800 focus:outline-none focus:ring-1 focus:ring-inset focus:ring-brand-300',
        mono && 'font-mono',
      )}
    />
  )
}
