// Penampil .ipynb READ-ONLY ala Jupyter/VS Code: sel markdown ter-render, sel kode
// beserta OUTPUT-nya (teks/gambar/grafik/HTML/error). Dipakai di detail job saat
// membuka berkas .ipynb, supaya tampil sebagai notebook — bukan JSON mentah.
import { useMemo } from 'react'

import { parseNotebookFull, type ParsedFullCell } from '../lib/ipynb'
import { renderMarkdown } from '../lib/markdown'
import { OutputView } from './NotebookOutput'

export default function NotebookPreview({ content }: { content: string }) {
  const parsed = useMemo(() => {
    try {
      return { cells: parseNotebookFull(content), error: null as string | null }
    } catch (e) {
      return {
        cells: [] as ParsedFullCell[],
        error: e instanceof Error ? e.message : 'Gagal membaca notebook.',
      }
    }
  }, [content])

  if (parsed.error) {
    // Notebook rusak/kosong -> tampilkan pesan + JSON mentah sebagai cadangan.
    return (
      <div className="p-4 text-xs">
        <p className="mb-2 rounded-lg bg-amber-50 px-3 py-1.5 text-amber-700">{parsed.error}</p>
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 font-mono text-[11px] text-slate-600 ring-1 ring-slate-100">
          {content}
        </pre>
      </div>
    )
  }

  return (
    <div className="space-y-3 p-3">
      {parsed.cells.map((cell, i) =>
        cell.kind === 'markdown' ? (
          <div
            key={i}
            className="md-body px-2"
            // Aman: HTML di-escape lebih dulu di renderMarkdown().
            dangerouslySetInnerHTML={{ __html: renderMarkdown(cell.source) }}
          />
        ) : (
          <CodeCell key={i} cell={cell} />
        ),
      )}
    </div>
  )
}

function CodeCell({ cell }: { cell: ParsedFullCell }) {
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
