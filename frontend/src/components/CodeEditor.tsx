// Editor kode Monaco dengan "error lens": garis bawah merah/kuning + pesan inline
// di akhir baris + ringkasan jumlah error/peringatan. Analisis dari backend (/lint),
// statik & aman (tidak menjalankan kode). Dipakai di form tempel-kode & sel notebook.

import { useEffect, useRef, useState } from 'react'
import Editor, { type Monaco, type OnMount } from '@monaco-editor/react'

import { api } from '../lib/api'
import type { LintDiagnostic } from '../lib/types'

type SummaryMode = 'always' | 'problems-only' | 'hidden'

interface LintSummary {
  errors: number
  warnings: number
  loading: boolean
  ran: boolean
}

export default function CodeEditor({
  value,
  onChange,
  language = 'python',
  height = 256,
  theme = 'vs-dark',
  readOnly = false,
  lint = true,
  summaryMode = 'always',
  onMount,
  autoGrow = false,
  minHeight = 64,
  maxHeight = 600,
}: {
  value: string
  onChange: (v: string) => void
  language?: string
  height?: number | string
  theme?: string
  readOnly?: boolean
  lint?: boolean
  summaryMode?: SummaryMode
  onMount?: OnMount
  // Auto-tinggi: editor mengikuti tinggi konten nyata (termasuk baris ter-wrap),
  // membesar hingga maxHeight lalu BISA DI-SCROLL di dalam editor (kode tak terpotong).
  autoGrow?: boolean
  minHeight?: number
  maxHeight?: number
}) {
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const monacoRef = useRef<Monaco | null>(null)
  const decoRef = useRef<string[]>([])
  const reqRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [summary, setSummary] = useState<LintSummary>({
    errors: 0,
    warnings: 0,
    loading: false,
    ran: false,
  })
  const [autoHeight, setAutoHeight] = useState<number>(minHeight)

  const lintActive = lint && language === 'python' && !readOnly

  function clearDiagnostics() {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco) return
    const model = editor.getModel()
    if (model) monaco.editor.setModelMarkers(model, 'pyflakes', [])
    decoRef.current = editor.deltaDecorations(decoRef.current, [])
  }

  function applyDiagnostics(diags: LintDiagnostic[]) {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco) return
    const model = editor.getModel()
    if (!model) return
    const lineCount = model.getLineCount()
    const clamp = (ln: number) => Math.min(Math.max(ln, 1), lineCount)

    // Garis bawah (squiggle) + hover via markers.
    const markers = diags.map((d) => {
      const ln = clamp(d.line)
      return {
        startLineNumber: ln,
        startColumn: Math.max(d.col, 1),
        endLineNumber: ln,
        endColumn: model.getLineMaxColumn(ln),
        message: d.message,
        severity:
          d.severity === 'error'
            ? monaco.MarkerSeverity.Error
            : monaco.MarkerSeverity.Warning,
      }
    })
    monaco.editor.setModelMarkers(model, 'pyflakes', markers)

    // Pesan inline di akhir baris (1 pesan per baris) — tampilan "error lens".
    const firstPerLine = new Map<number, LintDiagnostic>()
    for (const d of diags) {
      const ln = clamp(d.line)
      if (!firstPerLine.has(ln)) firstPerLine.set(ln, d)
    }
    const decos = [...firstPerLine.entries()].map(([ln, d]) => {
      const endCol = model.getLineMaxColumn(ln)
      return {
        range: new monaco.Range(ln, endCol, ln, endCol),
        options: {
          showIfCollapsed: true,
          after: {
            content:
              (d.severity === 'error' ? '\u2716 ' : '\u26a0 ') + d.message,
            inlineClassName:
              d.severity === 'error' ? 'lens-error' : 'lens-warning',
          },
        },
      }
    })
    decoRef.current = editor.deltaDecorations(decoRef.current, decos)
  }

  async function lintNow(code: string) {
    if (!lintActive) return
    if (!code.trim()) {
      clearDiagnostics()
      setSummary({ errors: 0, warnings: 0, loading: false, ran: false })
      return
    }
    const token = ++reqRef.current
    setSummary((s) => ({ ...s, loading: true }))
    try {
      const res = await api.lint(code)
      if (token !== reqRef.current) return // hasil usang, abaikan
      applyDiagnostics(res.diagnostics)
      setSummary({
        errors: res.error_count,
        warnings: res.warning_count,
        loading: false,
        ran: true,
      })
    } catch {
      if (token !== reqRef.current) return
      setSummary((s) => ({ ...s, loading: false }))
    }
  }

  // Lint debounced setiap kode berubah.
  useEffect(() => {
    if (!lintActive) {
      clearDiagnostics()
      return
    }
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => void lintNow(value), 450)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, lintActive])

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    monacoRef.current = monaco
    if (autoGrow) {
      // Ikuti tinggi konten nyata (Monaco sudah memperhitungkan word-wrap), dibatasi
      // [minHeight, maxHeight]. Lebih dari itu -> editor scroll sendiri (kode tak terpotong).
      const applyHeight = () => {
        const h = Math.min(
          maxHeight,
          Math.max(minHeight, Math.ceil(editor.getContentHeight())),
        )
        setAutoHeight(h)
      }
      editor.onDidContentSizeChange(applyHeight)
      applyHeight()
    }
    onMount?.(editor, monaco)
    if (lintActive) void lintNow(editor.getValue())
  }

  const showSummary =
    summaryMode !== 'hidden' &&
    lintActive &&
    (summaryMode === 'always' ||
      summary.errors > 0 ||
      summary.warnings > 0 ||
      summary.loading)

  return (
    <div className="overflow-hidden rounded-lg border border-slate-300">
      <Editor
        height={autoGrow ? autoHeight : height}
        language={language}
        theme={theme}
        value={value}
        onChange={(v) => onChange(v ?? '')}
        onMount={handleMount}
        loading={<div className="p-3 text-xs text-slate-400">Memuat editor…</div>}
        options={{
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbers: language === 'markdown' ? 'off' : 'on',
          scrollBeyondLastLine: false,
          automaticLayout: true,
          padding: { top: 8, bottom: 8 },
          wordWrap: 'on',
          renderLineHighlight: 'none',
          overviewRulerLanes: 0,
          readOnly,
          scrollbar: { alwaysConsumeMouseWheel: false, vertical: 'auto' },
        }}
      />
      {showSummary && <LintSummaryBar {...summary} />}
    </div>
  )
}

function LintSummaryBar({ errors, warnings, loading, ran }: LintSummary) {
  const clean = ran && errors === 0 && warnings === 0
  return (
    <div className="flex items-center gap-3 border-t border-slate-200 bg-slate-50 px-3 py-1.5 text-xs">
      {loading ? (
        <span className="text-slate-400">Memeriksa kode…</span>
      ) : clean ? (
        <span className="font-medium text-emerald-600">
          ✓ Tidak ada masalah terdeteksi
        </span>
      ) : errors > 0 || warnings > 0 ? (
        <>
          {errors > 0 && (
            <span className="flex items-center gap-1 font-medium text-rose-600">
              <span className="h-2 w-2 rounded-full bg-rose-500" />
              {errors} error
            </span>
          )}
          {warnings > 0 && (
            <span className="flex items-center gap-1 font-medium text-amber-600">
              <span className="h-2 w-2 rounded-full bg-amber-500" />
              {warnings} peringatan
            </span>
          )}
          <span className="text-slate-400">
            — garis bawah &amp; pesan di editor menandai lokasinya
          </span>
        </>
      ) : (
        <span className="text-slate-400">Mulai ketik kode…</span>
      )}
    </div>
  )
}
