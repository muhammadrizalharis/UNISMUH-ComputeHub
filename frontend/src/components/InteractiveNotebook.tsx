// Notebook interaktif ala Colab/VS Code: editor Monaco + tombol Run per sel,
// kernel HIDUP di GPU (state variabel tersimpan antar-sel), output streaming
// lewat WebSocket. Dipakai untuk "Tempel Kode" (poin 1).
import Editor from '@monaco-editor/react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import { cn } from '../lib/format'
import {
  IconGpu,
  IconPlay,
  IconPlus,
  IconRefresh,
  IconStop,
  IconX,
} from './icons'

type OutStream = { kind: 'stream'; name: string; text: string }
type OutResult = { kind: 'result'; data: Record<string, string> }
type OutError = { kind: 'error'; ename: string; evalue: string; traceback: string[] }
type CellOutput = OutStream | OutResult | OutError

type Cell = {
  id: string
  code: string
  outputs: CellOutput[]
  running: boolean
  execCount: number | null
  errored: boolean
}

type KernelState =
  | 'starting'
  | 'idle'
  | 'busy'
  | 'disconnected'
  | 'error'

type WsMessage = {
  type: string
  cell_id?: string
  state?: string
  name?: string
  text?: string
  data?: Record<string, string>
  ename?: string
  evalue?: string
  traceback?: string[]
  execution_count?: number | null
}

let seq = 0
function makeCell(code = ''): Cell {
  seq += 1
  return {
    id: `cell-${Date.now()}-${seq}`,
    code,
    outputs: [],
    running: false,
    execCount: null,
    errored: false,
  }
}

const STARTER = `# Tulis kode Python, lalu klik \u25b6 Run (atau Shift+Enter).
# Variabel tetap hidup antar-sel (seperti Google Colab).
import torch
print("GPU:", torch.cuda.get_device_name(0))
print("CUDA tersedia:", torch.cuda.is_available())`

function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.replace(/\u001b\[[0-9;]*m/g, '')
}

function editorHeight(code: string): number {
  const lines = code.split('\n').length
  return Math.min(Math.max(lines, 2), 22) * 19 + 16
}

const KERNEL_LABEL: Record<KernelState, { text: string; cls: string; dot: string }> = {
  starting: { text: 'Menyiapkan kernel…', cls: 'bg-amber-50 text-amber-700 ring-amber-600/20', dot: 'bg-amber-400 animate-pulse' },
  idle: { text: 'Kernel siap', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20', dot: 'bg-emerald-500' },
  busy: { text: 'Menjalankan…', cls: 'bg-blue-50 text-blue-700 ring-blue-600/20', dot: 'bg-blue-500 animate-pulse' },
  disconnected: { text: 'Terputus', cls: 'bg-slate-100 text-slate-600 ring-slate-500/20', dot: 'bg-slate-400' },
  error: { text: 'Gagal', cls: 'bg-rose-50 text-rose-700 ring-rose-600/20', dot: 'bg-rose-500' },
}

export default function InteractiveNotebook() {
  const [cells, setCells] = useState<Cell[]>(() => [makeCell(STARTER)])
  const [kernel, setKernel] = useState<KernelState>('starting')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [gpuIndex, setGpuIndex] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pendingRef = useRef<Map<string, () => void>>(new Map())
  const cellsRef = useRef<Cell[]>(cells)
  cellsRef.current = cells

  const patchCell = useCallback((id: string, fn: (c: Cell) => Cell) => {
    setCells((cs) => cs.map((c) => (c.id === id ? fn(c) : c)))
  }, [])

  const connect = useCallback(
    (sid: string) => {
      const ws = new WebSocket(api.interactiveWsUrl(sid))
      wsRef.current = ws
      ws.onclose = () => setKernel((k) => (k === 'error' ? k : 'disconnected'))
      ws.onerror = () => setKernel('error')
      ws.onmessage = (ev) => {
        let m: WsMessage
        try {
          m = JSON.parse(ev.data as string)
        } catch {
          return
        }
        const cid = m.cell_id
        switch (m.type) {
          case 'ready':
            setKernel('idle')
            break
          case 'status':
            setKernel(m.state === 'busy' ? 'busy' : 'idle')
            break
          case 'stream':
            if (cid)
              patchCell(cid, (c) => ({
                ...c,
                outputs: [...c.outputs, { kind: 'stream', name: m.name || 'stdout', text: m.text || '' }],
              }))
            break
          case 'result':
            if (cid)
              patchCell(cid, (c) => ({
                ...c,
                outputs: [...c.outputs, { kind: 'result', data: m.data || {} }],
              }))
            break
          case 'error':
            if (cid)
              patchCell(cid, (c) => ({
                ...c,
                errored: true,
                outputs: [
                  ...c.outputs,
                  { kind: 'error', ename: m.ename || '', evalue: m.evalue || '', traceback: m.traceback || [] },
                ],
              }))
            break
          case 'execute_reply':
            if (cid) {
              patchCell(cid, (c) => ({ ...c, running: false, execCount: m.execution_count ?? c.execCount }))
              const resolve = pendingRef.current.get(cid)
              if (resolve) {
                resolve()
                pendingRef.current.delete(cid)
              }
            }
            break
        }
      }
    },
    [patchCell],
  )

  const initSession = useCallback(() => {
    setKernel('starting')
    setError(null)
    api
      .createInteractiveSession()
      .then((s) => {
        setSessionId(s.session_id)
        setGpuIndex(s.gpu_index)
        connect(s.session_id)
      })
      .catch((e) => {
        setKernel('error')
        setError(e?.message || 'Gagal memulai kernel.')
      })
  }, [connect])

  useEffect(() => {
    initSession()
    return () => {
      wsRef.current?.close()
      // Kernel sengaja dibiarkan hidup saat pindah halaman; idle reaper di server
      // akan membebaskan GPU otomatis. Tutup manual lewat tombol "Matikan".
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runCell = useCallback(
    (cell: Cell): Promise<void> =>
      new Promise((resolve) => {
        const ws = wsRef.current
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          resolve()
          return
        }
        patchCell(cell.id, (c) => ({ ...c, running: true, errored: false, outputs: [] }))
        pendingRef.current.set(cell.id, resolve)
        ws.send(JSON.stringify({ type: 'execute', cell_id: cell.id, code: cell.code }))
      }),
    [patchCell],
  )

  const runAll = useCallback(async () => {
    const ids = cellsRef.current.map((c) => c.id)
    for (const id of ids) {
      const latest = cellsRef.current.find((c) => c.id === id)
      if (latest) {
        await runCell(latest)
        const after = cellsRef.current.find((c) => c.id === id)
        if (after?.errored) break // berhenti di sel yang error
      }
    }
  }, [runCell])

  const interrupt = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: 'interrupt' }))
  }, [])

  const restartKernel = useCallback(async () => {
    if (!sessionId) return
    try {
      await api.restartInteractiveSession(sessionId)
      setCells((cs) => cs.map((c) => ({ ...c, outputs: [], execCount: null, errored: false, running: false })))
      setKernel('idle')
    } catch (e) {
      setError((e as Error)?.message || 'Gagal restart kernel.')
    }
  }, [sessionId])

  const shutdown = useCallback(async () => {
    wsRef.current?.close()
    if (sessionId) {
      try {
        await api.deleteInteractiveSession(sessionId)
      } catch {
        /* noop */
      }
    }
    setSessionId(null)
    setKernel('disconnected')
  }, [sessionId])

  const addCell = useCallback((afterId?: string) => {
    setCells((cs) => {
      const nc = makeCell('')
      if (!afterId) return [...cs, nc]
      const i = cs.findIndex((c) => c.id === afterId)
      const copy = [...cs]
      copy.splice(i + 1, 0, nc)
      return copy
    })
  }, [])

  const deleteCell = useCallback((id: string) => {
    setCells((cs) => (cs.length <= 1 ? cs : cs.filter((c) => c.id !== id)))
  }, [])

  const kbusy = kernel === 'busy'
  const klabel = KERNEL_LABEL[kernel]
  const connected = kernel === 'idle' || kernel === 'busy'

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="sticky top-2 z-10 flex flex-wrap items-center gap-2 rounded-xl bg-slate-900/95 px-3 py-2 text-slate-200 shadow-lg ring-1 ring-white/10 backdrop-blur">
        <span className={cn('badge', klabel.cls)}>
          <span className={cn('h-1.5 w-1.5 rounded-full', klabel.dot)} />
          {klabel.text}
        </span>
        {gpuIndex != null && connected && (
          <span className="inline-flex items-center gap-1 text-xs text-slate-400">
            <IconGpu className="h-3.5 w-3.5 text-brand-400" /> GPU {gpuIndex}
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => void runAll()}
            disabled={!connected || kbusy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-brand-500 disabled:opacity-40"
          >
            <IconPlay className="h-3.5 w-3.5" /> Run All
          </button>
          <button
            onClick={interrupt}
            disabled={!kbusy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-white/20 disabled:opacity-40"
          >
            <IconStop className="h-3.5 w-3.5" /> Stop
          </button>
          <button
            onClick={() => void restartKernel()}
            disabled={!connected}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-white/20 disabled:opacity-40"
          >
            <IconRefresh className="h-3.5 w-3.5" /> Restart
          </button>
          {connected ? (
            <button
              onClick={() => void shutdown()}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-rose-300 transition hover:bg-rose-500/20"
            >
              <IconX className="h-3.5 w-3.5" /> Matikan
            </button>
          ) : (
            <button
              onClick={initSession}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500"
            >
              <IconRefresh className="h-3.5 w-3.5" /> Sambungkan ulang
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          {error}
        </div>
      )}

      {/* Cells */}
      <div className="space-y-3">
        {cells.map((cell) => (
          <NotebookCell
            key={cell.id}
            cell={cell}
            disabled={!connected}
            onChange={(code) => patchCell(cell.id, (c) => ({ ...c, code }))}
            onRun={() => void runCell(cellsRef.current.find((c) => c.id === cell.id) || cell)}
            onDelete={() => deleteCell(cell.id)}
            onAddBelow={() => addCell(cell.id)}
            canDelete={cells.length > 1}
          />
        ))}
      </div>

      <button
        onClick={() => addCell()}
        className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 py-2.5 text-sm font-medium text-slate-500 transition hover:border-brand-400 hover:bg-brand-50/40 hover:text-brand-600"
      >
        <IconPlus className="h-4 w-4" /> Tambah sel
      </button>
    </div>
  )
}

function NotebookCell({
  cell,
  disabled,
  onChange,
  onRun,
  onDelete,
  onAddBelow,
  canDelete,
}: {
  cell: Cell
  disabled: boolean
  onChange: (code: string) => void
  onRun: () => void
  onDelete: () => void
  onAddBelow: () => void
  canDelete: boolean
}) {
  const onRunRef = useRef(onRun)
  onRunRef.current = onRun

  return (
    <div className="group overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200 transition focus-within:ring-brand-400">
      <div className="flex">
        {/* Gutter: run + exec count */}
        <div className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-slate-100 bg-slate-50/60 py-2">
          <button
            onClick={onRun}
            disabled={disabled || cell.running}
            title="Run (Shift+Enter)"
            className={cn(
              'grid h-8 w-8 place-items-center rounded-lg text-white transition disabled:opacity-40',
              cell.running ? 'bg-blue-500' : 'bg-brand-600 hover:bg-brand-500',
            )}
          >
            {cell.running ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            ) : (
              <IconPlay className="h-4 w-4" />
            )}
          </button>
          <span className="text-[10px] font-mono text-slate-400">
            {cell.running ? '[*]' : cell.execCount != null ? `[${cell.execCount}]` : '[ ]'}
          </span>
        </div>

        {/* Editor */}
        <div className="min-w-0 flex-1">
          <Editor
            height={editorHeight(cell.code)}
            language="python"
            theme="vs-dark"
            value={cell.code}
            onChange={(v) => onChange(v ?? '')}
            onMount={(editor, monaco) => {
              editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () =>
                onRunRef.current(),
              )
            }}
            loading={<div className="p-3 text-xs text-slate-400">Memuat editor…</div>}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              automaticLayout: true,
              padding: { top: 8, bottom: 8 },
              wordWrap: 'on',
              renderLineHighlight: 'none',
              overviewRulerLanes: 0,
              scrollbar: { alwaysConsumeMouseWheel: false, vertical: 'auto' },
            }}
          />
        </div>

        {/* Cell actions */}
        <div className="flex w-8 shrink-0 flex-col items-center gap-1 py-2 opacity-0 transition group-hover:opacity-100">
          <button
            onClick={onAddBelow}
            title="Tambah sel di bawah"
            className="grid h-6 w-6 place-items-center rounded text-slate-400 hover:bg-slate-100 hover:text-brand-600"
          >
            <IconPlus className="h-3.5 w-3.5" />
          </button>
          {canDelete && (
            <button
              onClick={onDelete}
              title="Hapus sel"
              className="grid h-6 w-6 place-items-center rounded text-slate-400 hover:bg-rose-50 hover:text-rose-600"
            >
              <IconX className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Outputs */}
      {cell.outputs.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/40">
          {cell.outputs.map((out, i) => (
            <OutputView key={i} out={out} />
          ))}
        </div>
      )}
    </div>
  )
}

function OutputView({ out }: { out: CellOutput }) {
  if (out.kind === 'stream') {
    return (
      <pre
        className={cn(
          'overflow-x-auto whitespace-pre-wrap break-words px-3 py-1.5 font-mono text-xs',
          out.name === 'stderr' ? 'text-rose-600' : 'text-slate-700',
        )}
      >
        {out.text}
      </pre>
    )
  }
  if (out.kind === 'error') {
    const tb = out.traceback.length
      ? out.traceback.map(stripAnsi).join('\n')
      : `${out.ename}: ${out.evalue}`
    return (
      <pre className="overflow-x-auto whitespace-pre-wrap break-words bg-rose-50 px-3 py-2 font-mono text-xs text-rose-700">
        {tb}
      </pre>
    )
  }
  const d = out.data
  if (d['image/png'])
    return <img alt="output" className="max-w-full px-3 py-2" src={`data:image/png;base64,${d['image/png']}`} />
  if (d['image/jpeg'])
    return <img alt="output" className="max-w-full px-3 py-2" src={`data:image/jpeg;base64,${d['image/jpeg']}`} />
  if (d['text/html'])
    return (
      <div
        className="max-w-none overflow-x-auto px-3 py-2 text-xs"
        // Output HTML berasal dari kode milik pengguna sendiri.
        dangerouslySetInnerHTML={{ __html: d['text/html'] }}
      />
    )
  if (d['text/plain'])
    return (
      <pre className="overflow-x-auto whitespace-pre-wrap break-words px-3 py-1.5 font-mono text-xs text-slate-800">
        {d['text/plain']}
      </pre>
    )
  return null
}
