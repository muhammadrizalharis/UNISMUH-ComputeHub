// Notebook interaktif ala Colab/VS Code: editor Monaco + tombol Run per sel,
// kernel HIDUP di GPU (state variabel tersimpan antar-sel), output streaming
// lewat WebSocket.
//
// Mode (sumber):
//   - 'paste'    : tempel kode (poin 1)
//   - 'notebook' : unggah .ipynb -> sel-sel interaktif (poin 2)
//   - 'zip'      : unggah project .zip -> file explorer + jalan di project (poin 3)
//   - 'github'   : clone repo GitHub -> file explorer + jalan di repo (poin 4)
import Editor from '@monaco-editor/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import { parseNotebook } from '../lib/ipynb'
import { renderMarkdown } from '../lib/markdown'
import { NB_LS_PREFIX, pruneForeignDrafts } from '../lib/notebookDrafts'
import type { FileNode, InteractiveFile } from '../lib/types'
import {
  IconChevron,
  IconCode,
  IconDownload,
  IconFile,
  IconFolder,
  IconGithub,
  IconGpu,
  IconNotebook,
  IconPlay,
  IconPlus,
  IconRefresh,
  IconStop,
  IconUpload,
  IconX,
} from './icons'

export type NotebookMode = 'paste' | 'notebook' | 'zip' | 'github'

type OutStream = { kind: 'stream'; name: string; text: string }
type OutResult = { kind: 'result'; data: Record<string, string> }
type OutError = { kind: 'error'; ename: string; evalue: string; traceback: string[] }
type CellOutput = OutStream | OutResult | OutError

type CellKind = 'code' | 'markdown'

type Cell = {
  id: string
  kind: CellKind
  code: string
  editing: boolean // khusus markdown: tampil editor vs hasil render
  outputs: CellOutput[]
  running: boolean
  execCount: number | null
  errored: boolean
}

type KernelState = 'inactive' | 'starting' | 'idle' | 'busy' | 'disconnected' | 'error'

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
function makeCell(code = '', kind: CellKind = 'code'): Cell {
  seq += 1
  return {
    id: `cell-${Date.now()}-${seq}`,
    kind,
    code,
    editing: kind === 'code' ? true : !code.trim(),
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

function starterCells(mode: NotebookMode): Cell[] {
  // Hanya 'paste' yang langsung punya sel contoh. notebook/zip/github MULAI
  // KOSONG — sel baru muncul setelah .ipynb diunggah / project dimuat.
  return mode === 'paste' ? [makeCell(STARTER)] : []
}

// Simpan notebook per-mode & per-USER di memori modul supaya TIDAK hilang saat
// pindah menu (komponen unmount) DAN tidak bocor antar akun. Kernel di server
// tetap hidup (idle reaper), dan createInteractiveSession() memakai ulang kernel
// milik user, jadi cukup memulihkan tampilan sel + file tree.
type SavedNotebook = { cells: Cell[]; tree: FileNode | null }
const notebookStore = new Map<string, SavedNotebook>()

// Cadangan RINGAN (kode saja, tanpa output) ke localStorage supaya isi sel tetap
// ada walau browser di-REFRESH penuh. Kunci di-scope per-user supaya kode milik
// satu akun tidak terlihat akun lain di browser yang sama. Output tidak disimpan.
const LS_PREFIX = NB_LS_PREFIX
const LS_MAX_CHARS = 400_000

function storeKey(mode: NotebookMode, uid: number): string {
  return `${mode}:${uid}`
}

function loadLocalCells(mode: NotebookMode, uid: number): Cell[] | null {
  try {
    const raw = localStorage.getItem(LS_PREFIX + storeKey(mode, uid))
    if (!raw) return null
    const arr = JSON.parse(raw) as { kind?: string; code?: string }[]
    if (!Array.isArray(arr) || arr.length === 0) return null
    return arr.map((c) => makeCell(c.code ?? '', c.kind === 'markdown' ? 'markdown' : 'code'))
  } catch {
    return null
  }
}

function saveLocalCells(mode: NotebookMode, uid: number, cells: Cell[]): void {
  try {
    const slim = cells.map((c) => ({ kind: c.kind, code: c.code }))
    const json = JSON.stringify(slim)
    if (json.length > LS_MAX_CHARS) return // jangan bebani localStorage
    localStorage.setItem(LS_PREFIX + storeKey(mode, uid), json)
  } catch {
    /* kuota penuh / localStorage nonaktif -> abaikan */
  }
}

function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.replace(/\u001b\[[0-9;]*m/g, '')
}

function editorHeight(code: string): number {
  const lines = code.split('\n').length
  return Math.min(Math.max(lines, 2), 22) * 19 + 16
}

function fmtBytes(n?: number): string {
  if (!n || n <= 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Bangun JSON .ipynb (nbformat 4) dari sel-sel notebook (untuk ekspor/unduh).
// Output sel (stream/hasil/gambar/error) IKUT disertakan supaya hasil run
// tersimpan di berkas .ipynb.
function cellsToIpynb(cells: Cell[]): string {
  const toSource = (s: string): string[] => (s.length ? s.split(/(?<=\n)/) : [''])
  const mapOutputs = (outs: CellOutput[], execCount: number | null): object[] =>
    outs.map((o) => {
      if (o.kind === 'stream') {
        return { output_type: 'stream', name: o.name || 'stdout', text: toSource(o.text) }
      }
      if (o.kind === 'error') {
        return {
          output_type: 'error',
          ename: o.ename,
          evalue: o.evalue,
          traceback: o.traceback.length ? o.traceback : [`${o.ename}: ${o.evalue}`],
        }
      }
      // hasil eksekusi (teks/HTML/gambar) -> execute_result
      const data: Record<string, string | string[]> = {}
      for (const [mime, val] of Object.entries(o.data)) {
        data[mime] = mime.startsWith('image/') ? val : toSource(val)
      }
      return { output_type: 'execute_result', execution_count: execCount, data, metadata: {} }
    })
  const nb = {
    cells: cells.map((c) =>
      c.kind === 'markdown'
        ? { cell_type: 'markdown', metadata: {}, source: toSource(c.code) }
        : {
            cell_type: 'code',
            metadata: {},
            execution_count: c.execCount ?? null,
            outputs: mapOutputs(c.outputs, c.execCount ?? null),
            source: toSource(c.code),
          },
    ),
    metadata: {
      kernelspec: { name: 'python3', display_name: 'Python 3' },
      language_info: { name: 'python' },
    },
    nbformat: 4,
    nbformat_minor: 5,
  }
  return JSON.stringify(nb, null, 1)
}

const KERNEL_LABEL: Record<KernelState, { text: string; cls: string; dot: string }> = {
  inactive: { text: 'Kernel belum aktif', cls: 'bg-slate-100 text-slate-500 ring-slate-400/20', dot: 'bg-slate-300' },
  starting: { text: 'Menyiapkan kernel…', cls: 'bg-amber-50 text-amber-700 ring-amber-600/20', dot: 'bg-amber-400 animate-pulse' },
  idle: { text: 'Kernel siap', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20', dot: 'bg-emerald-500' },
  busy: { text: 'Menjalankan…', cls: 'bg-blue-50 text-blue-700 ring-blue-600/20', dot: 'bg-blue-500 animate-pulse' },
  disconnected: { text: 'Terputus', cls: 'bg-slate-100 text-slate-600 ring-slate-500/20', dot: 'bg-slate-400' },
  error: { text: 'Gagal', cls: 'bg-rose-50 text-rose-700 ring-rose-600/20', dot: 'bg-rose-500' },
}

export default function InteractiveNotebook({ mode = 'paste' }: { mode?: NotebookMode }) {
  const { user } = useAuth()
  const uid = user?.id ?? 0
  const skey = storeKey(mode, uid)
  const [cells, setCells] = useState<Cell[]>(() => {
    const saved = notebookStore.get(skey)
    if (saved && saved.cells.length) return saved.cells.map((c) => ({ ...c, running: false }))
    const local = loadLocalCells(mode, uid)
    if (local) return local
    return starterCells(mode)
  })
  const [kernel, setKernel] = useState<KernelState>('inactive')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [gpuIndex, setGpuIndex] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Project (zip/github)
  const [tree, setTree] = useState<FileNode | null>(() => notebookStore.get(skey)?.tree ?? null)
  const [projectBusy, setProjectBusy] = useState(false)
  const [projectError, setProjectError] = useState<string | null>(null)
  const [preview, setPreview] = useState<InteractiveFile | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pushOpen, setPushOpen] = useState(false)
  const [pushing, setPushing] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const pendingRef = useRef<Map<string, () => void>>(new Map())
  const cellsRef = useRef<Cell[]>(cells)
  cellsRef.current = cells

  // Persist tampilan notebook per-mode (anti hilang saat pindah menu) + cadangan
  // kode ke localStorage (anti hilang saat refresh penuh browser).
  useEffect(() => {
    notebookStore.set(skey, { cells, tree })
    // localStorage hanya utk paste & notebook (kode mandiri). zip/github terikat
    // project di kernel, jadi tak disimpan ke localStorage (cukup memori sesi).
    if (mode === 'paste' || mode === 'notebook') saveLocalCells(mode, uid, cells)
  }, [skey, mode, uid, cells, tree])

  const patchCell = useCallback((id: string, fn: (c: Cell) => Cell) => {
    setCells((cs) => cs.map((c) => (c.id === id ? fn(c) : c)))
  }, [])

  const connect = useCallback(
    (sid: string) => {
      // Tutup koneksi lama (jika ada) tanpa memicu handler-nya -> cegah WS ganda.
      if (wsRef.current) {
        const old = wsRef.current
        old.onclose = null
        old.onerror = null
        old.onmessage = null
        try {
          old.close()
        } catch {
          /* noop */
        }
      }
      const ws = new WebSocket(api.interactiveWsUrl(sid))
      wsRef.current = ws
      ws.onclose = () => {
        setKernel((k) => (k === 'error' ? k : 'disconnected'))
        // Bebaskan promise sel yang menggantung + hentikan status "running" agar
        // Run All tidak menggantung & spinner tidak macet saat koneksi terputus.
        pendingRef.current.forEach((resolve) => resolve())
        pendingRef.current.clear()
        setCells((cs) => cs.map((c) => (c.running ? { ...c, running: false } : c)))
      }
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

  // Buat/sambung kernel SEKALI (idempoten). HEMAT GPU: kernel baru dipesan saat
  // benar-benar dipakai (paste saat mount; notebook/zip/github saat unggah/clone).
  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (sessionId) return sessionId
    setKernel('starting')
    setError(null)
    try {
      const s = await api.createInteractiveSession(mode)
      setSessionId(s.session_id)
      setGpuIndex(s.gpu_index)
      connect(s.session_id)
      return s.session_id
    } catch (e) {
      setKernel('error')
      setError((e as Error)?.message || 'Gagal memulai kernel.')
      return null
    }
  }, [sessionId, connect, mode])

  useEffect(() => {
    // Bersihkan draf milik akun lain / legacy -> kode tidak bocor antar akun.
    pruneForeignDrafts(uid)
    // Kernel TIDAK auto-start. Kernel + GPU baru menyala saat user menekan Run
    // (paste/notebook) atau mengunggah/clone project (zip/github) -> hemat GPU.
    return () => {
      wsRef.current?.close()
      // Kernel dibiarkan hidup saat pindah halaman; idle reaper membebaskan GPU.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Pastikan kernel siap: start bila belum aktif, lalu tunggu WS terbuka. Dipakai
  // saat user menekan Run -> kernel/GPU baru dipesan tepat saat dibutuhkan.
  const ensureReady = useCallback(async (): Promise<boolean> => {
    const cur = wsRef.current
    if (cur && cur.readyState === WebSocket.OPEN) return true
    const sid = await ensureSession()
    if (!sid) return false
    for (let i = 0; i < 300; i++) {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) return true
      if (ws && ws.readyState === WebSocket.CLOSED) return false
      await new Promise((r) => setTimeout(r, 100))
    }
    return false
  }, [ensureSession])

  const runCell = useCallback(
    async (cell: Cell): Promise<void> => {
      if (cell.kind === 'markdown') {
        patchCell(cell.id, (c) => ({ ...c, editing: false }))
        return
      }
      const ready = await ensureReady() // start kernel bila belum aktif
      const ws = wsRef.current
      if (!ready || !ws || ws.readyState !== WebSocket.OPEN) return
      await new Promise<void>((resolve) => {
        patchCell(cell.id, (c) => ({ ...c, running: true, errored: false, outputs: [] }))
        pendingRef.current.set(cell.id, resolve)
        ws.send(JSON.stringify({ type: 'execute', cell_id: cell.id, code: cell.code }))
      })
    },
    [patchCell, ensureReady],
  )

  const runAll = useCallback(async () => {
    const ids = cellsRef.current.filter((c) => c.kind === 'code').map((c) => c.id)
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

  const addCell = useCallback((afterId?: string, kind: CellKind = 'code') => {
    setCells((cs) => {
      const nc = makeCell('', kind)
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

  // ---- poin 2: muat .ipynb jadi sel (parse di sisi klien) ----
  const loadNotebookText = useCallback((text: string, label?: string) => {
    try {
      const parsed = parseNotebook(text)
      setCells(parsed.map((pc) => makeCell(pc.source, pc.kind)))
      setError(null)
      setNotice(label ? `Notebook "${label}" dimuat (${parsed.length} sel).` : null)
    } catch (e) {
      setError((e as Error).message || 'Gagal membaca notebook.')
    }
  }, [])

  const onPickNotebook = useCallback(
    async (file: File) => {
      const text = await file.text()
      loadNotebookText(text, file.name)
      // Kernel TIDAK dinyalakan di sini -> menyala saat user menekan Run.
    },
    [loadNotebookText],
  )

  // ---- poin 3 & 4: muat project + buka file ----
  const uploadZip = useCallback(
    async (file: File) => {
      setProjectBusy(true)
      setProjectError(null)
      try {
        const sid = await ensureSession()
        if (!sid) return
        const res = await api.uploadInteractiveZip(sid, file)
        setTree(res.tree)
        setCells((cs) => (cs.length ? cs : [makeCell('')]))
        setNotice(`Project "${file.name}" diekstrak. CWD kernel kini di folder project.`)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal mengunggah project.')
      } finally {
        setProjectBusy(false)
      }
    },
    [ensureSession],
  )

  const cloneRepo = useCallback(
    async (url: string, ref: string) => {
      setProjectBusy(true)
      setProjectError(null)
      try {
        const sid = await ensureSession()
        if (!sid) return
        const res = await api.cloneInteractiveRepo(sid, url, ref || undefined)
        setTree(res.tree)
        setCells((cs) => (cs.length ? cs : [makeCell('')]))
        setNotice('Repo berhasil di-clone. CWD kernel kini di folder repo.')
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal clone repo.')
      } finally {
        setProjectBusy(false)
      }
    },
    [ensureSession],
  )

  const refreshTree = useCallback(async () => {
    if (!sessionId) return
    try {
      const res = await api.listInteractiveFiles(sessionId)
      setTree(res.tree)
    } catch (e) {
      setProjectError((e as Error).message)
    }
  }, [sessionId])

  const openFile = useCallback(
    async (path: string, name: string) => {
      if (!sessionId) return
      setProjectError(null)
      try {
        const f = await api.readInteractiveFile(sessionId, path)
        if (name.toLowerCase().endsWith('.ipynb')) {
          loadNotebookText(f.content, name)
        } else {
          setPreview(f)
        }
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal membuka file.')
      }
    },
    [sessionId, loadNotebookText],
  )

  const loadPreviewToCell = useCallback((f: InteractiveFile) => {
    setCells((cs) => [...cs, makeCell(f.content, 'code')])
    setPreview(null)
    setNotice(`"${f.path}" dimuat ke sel baru.`)
  }, [])

  const exportIpynb = useCallback(() => {
    const json = cellsToIpynb(cellsRef.current)
    triggerDownload(new Blob([json], { type: 'application/json' }), 'notebook.ipynb')
  }, [])

  const downloadProject = useCallback(async () => {
    if (!sessionId) return
    try {
      const blob = await api.downloadInteractiveProject(sessionId)
      triggerDownload(blob, `${tree?.name || 'project'}.zip`)
    } catch (e) {
      setProjectError((e as Error).message || 'Gagal mengunduh project.')
    }
  }, [sessionId, tree])

  const doPush = useCallback(
    async (message: string, token: string) => {
      if (!sessionId) return
      setPushing(true)
      setProjectError(null)
      try {
        const res = await api.pushInteractiveRepo(sessionId, message, token)
        setNotice(
          `Push ke branch "${res.branch}" berhasil${res.committed ? '' : ' (tak ada perubahan baru untuk di-commit)'}.`,
        )
        setPushOpen(false)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal push.')
      } finally {
        setPushing(false)
      }
    },
    [sessionId],
  )

  const kbusy = kernel === 'busy'
  const klabel = KERNEL_LABEL[kernel]
  const connected = kernel === 'idle' || kernel === 'busy'
  // Bisa memicu Run (akan start kernel bila belum aktif). Hanya terhalang saat
  // kernel sedang disiapkan atau sedang menjalankan sel lain.
  const canRun = kernel !== 'starting' && !kbusy
  const isProjectMode = mode === 'zip' || mode === 'github'

  const cellList = useMemo(
    () => (
      <div className="space-y-3">
        {cells.map((cell) => (
          <NotebookCell
            key={cell.id}
            cell={cell}
            disabled={!canRun}
            onChange={(code) => patchCell(cell.id, (c) => ({ ...c, code }))}
            onRun={() => void runCell(cellsRef.current.find((c) => c.id === cell.id) || cell)}
            onEdit={() => patchCell(cell.id, (c) => ({ ...c, editing: true }))}
            onDelete={() => deleteCell(cell.id)}
            onAddBelow={() => addCell(cell.id)}
            canDelete={cells.length > 1}
          />
        ))}
      </div>
    ),
    [cells, canRun, patchCell, runCell, deleteCell, addCell],
  )

  const addBar = (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => addCell()}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 py-2.5 text-sm font-medium text-slate-500 transition hover:border-brand-400 hover:bg-brand-50/40 hover:text-brand-600"
      >
        <IconCode className="h-4 w-4" /> Sel kode
      </button>
      <button
        onClick={() => addCell(undefined, 'markdown')}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 py-2.5 text-sm font-medium text-slate-500 transition hover:border-violet-400 hover:bg-violet-50/40 hover:text-violet-600"
      >
        <IconNotebook className="h-4 w-4" /> Sel teks (Markdown)
      </button>
    </div>
  )

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
            disabled={!canRun}
            title="Jalankan semua sel (kernel menyala otomatis bila belum aktif)"
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
          <button
            onClick={exportIpynb}
            disabled={cells.length === 0}
            title="Ekspor sel ke berkas .ipynb"
            className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-white/20 disabled:opacity-40"
          >
            <IconDownload className="h-3.5 w-3.5" /> .ipynb
          </button>
          {connected ? (
            <button
              onClick={() => void shutdown()}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-rose-300 transition hover:bg-rose-500/20"
            >
              <IconX className="h-3.5 w-3.5" /> Matikan
            </button>
          ) : kernel === 'disconnected' || kernel === 'error' ? (
            <button
              onClick={() => void ensureSession()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500"
            >
              <IconRefresh className="h-3.5 w-3.5" /> Sambungkan ulang
            </button>
          ) : null}
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          {error}
        </div>
      )}
      {notice && (
        <div className="flex items-start gap-2 rounded-lg bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
          <span className="flex-1">{notice}</span>
          <button onClick={() => setNotice(null)} className="text-emerald-500 hover:text-emerald-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Poin 2: unggah .ipynb (sel muncul SETELAH diunggah) */}
      {mode === 'notebook' && <NotebookUploadBar disabled={false} onPick={onPickNotebook} />}

      {/* Poin 3 & 4: init project bila belum dimuat (sel muncul SETELAH dimuat) */}
      {isProjectMode && !tree && (
        <ProjectInit
          mode={mode}
          busy={projectBusy}
          error={projectError}
          onZip={uploadZip}
          onClone={cloneRepo}
        />
      )}

      {/* Area notebook: muncul sesuai keadaan tiap mode */}
      {isProjectMode ? (
        tree && (
          <div className="grid items-start gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
            <FileExplorer
              tree={tree}
              busy={projectBusy}
              mode={mode}
              onOpen={openFile}
              onRefresh={refreshTree}
              onDownload={() => void downloadProject()}
              onPush={() => setPushOpen(true)}
              onChangeProject={() => {
                setTree(null)
                setProjectError(null)
              }}
            />
            <div className="space-y-3">
              {cellList}
              {addBar}
            </div>
          </div>
        )
      ) : mode === 'notebook' ? (
        cells.length > 0 && (
          <>
            {cellList}
            {addBar}
          </>
        )
      ) : (
        <>
          {cellList}
          {addBar}
        </>
      )}

      {preview && (
        <FilePreview
          file={preview}
          onClose={() => setPreview(null)}
          onLoadToCell={() => loadPreviewToCell(preview)}
        />
      )}

      {pushOpen && (
        <PushPanel busy={pushing} onClose={() => setPushOpen(false)} onPush={doPush} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------- sel notebook
function NotebookCell({
  cell,
  disabled,
  onChange,
  onRun,
  onEdit,
  onDelete,
  onAddBelow,
  canDelete,
}: {
  cell: Cell
  disabled: boolean
  onChange: (code: string) => void
  onRun: () => void
  onEdit: () => void
  onDelete: () => void
  onAddBelow: () => void
  canDelete: boolean
}) {
  const onRunRef = useRef(onRun)
  onRunRef.current = onRun

  const isMd = cell.kind === 'markdown'
  const showEditor = !isMd || cell.editing

  const editor = (
    <Editor
      height={editorHeight(cell.code)}
      language={isMd ? 'markdown' : 'python'}
      theme="vs-dark"
      value={cell.code}
      onChange={(v) => onChange(v ?? '')}
      onMount={(editorInst, monaco) => {
        editorInst.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () =>
          onRunRef.current(),
        )
      }}
      loading={<div className="p-3 text-xs text-slate-400">Memuat editor…</div>}
      options={{
        minimap: { enabled: false },
        fontSize: 13,
        lineNumbers: isMd ? 'off' : 'on',
        scrollBeyondLastLine: false,
        automaticLayout: true,
        padding: { top: 8, bottom: 8 },
        wordWrap: 'on',
        renderLineHighlight: 'none',
        overviewRulerLanes: 0,
        scrollbar: { alwaysConsumeMouseWheel: false, vertical: 'auto' },
      }}
    />
  )

  return (
    <div className="group overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200 transition focus-within:ring-brand-400">
      <div className="flex">
        {/* Gutter */}
        <div className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-slate-100 bg-slate-50/60 py-2">
          <button
            onClick={onRun}
            disabled={disabled || cell.running}
            title={isMd ? 'Render (Shift+Enter)' : 'Run (Shift+Enter)'}
            className={cn(
              'grid h-8 w-8 place-items-center rounded-lg text-white transition disabled:opacity-40',
              cell.running ? 'bg-blue-500' : isMd ? 'bg-violet-500 hover:bg-violet-400' : 'bg-brand-600 hover:bg-brand-500',
            )}
          >
            {cell.running ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            ) : (
              <IconPlay className="h-4 w-4" />
            )}
          </button>
          <span className="text-[10px] font-mono text-slate-400">
            {isMd ? 'md' : cell.running ? '[*]' : cell.execCount != null ? `[${cell.execCount}]` : '[ ]'}
          </span>
        </div>

        {/* Konten: editor (code / markdown-edit) atau markdown ter-render */}
        <div className="min-w-0 flex-1">
          {showEditor ? (
            editor
          ) : (
            <div
              onDoubleClick={onEdit}
              className="cursor-text px-4 py-3"
              title="Klik dua kali untuk mengedit"
            >
              {cell.code.trim() ? (
                <div
                  className="md-body"
                  // Aman: HTML di-escape lebih dulu di renderMarkdown().
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(cell.code) }}
                />
              ) : (
                <p className="text-sm italic text-slate-400">Sel markdown kosong — klik dua kali untuk menulis.</p>
              )}
            </div>
          )}
        </div>

        {/* Aksi sel */}
        <div className="flex w-8 shrink-0 flex-col items-center gap-1 py-2 opacity-0 transition group-hover:opacity-100">
          {isMd && !cell.editing && (
            <button
              onClick={onEdit}
              title="Edit markdown"
              className="grid h-6 w-6 place-items-center rounded text-slate-400 hover:bg-slate-100 hover:text-violet-600"
            >
              <IconCode className="h-3.5 w-3.5" />
            </button>
          )}
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

      {/* Output (code) */}
      {!isMd && cell.outputs.length > 0 && (
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

// ---------------------------------------------------------- unggah .ipynb (p2)
function NotebookUploadBar({ disabled, onPick }: { disabled: boolean; onPick: (f: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
      <IconNotebook className="h-5 w-5 text-orange-500" />
      <div className="flex-1">
        <p className="text-sm font-medium text-slate-700">Muat notebook (.ipynb) ke sel interaktif</p>
        <p className="text-xs text-slate-400">Sel kode & markdown dimuat; jalankan satu per satu di GPU.</p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".ipynb"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onPick(f)
          e.target.value = ''
        }}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
        className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:opacity-40"
      >
        <IconUpload className="h-4 w-4" /> Pilih .ipynb
      </button>
    </div>
  )
}

// ------------------------------------------------------- init project (p3 & p4)
function ProjectInit({
  mode,
  busy,
  error,
  onZip,
  onClone,
}: {
  mode: NotebookMode
  busy: boolean
  error: string | null
  onZip: (f: File) => void
  onClone: (url: string, ref: string) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [url, setUrl] = useState('')
  const [ref, setRef] = useState('')
  const isZip = mode === 'zip'

  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <div className="mb-3 flex items-center gap-2">
        {isZip ? <IconUpload className="h-5 w-5 text-emerald-500" /> : <IconGithub className="h-5 w-5 text-violet-500" />}
        <h3 className="text-sm font-semibold text-slate-700">
          {isZip ? 'Unggah project (.zip)' : 'Clone repo GitHub'}
        </h3>
      </div>

      {isZip ? (
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const f = e.dataTransfer.files?.[0]
            if (f && !busy) onZip(f)
          }}
          className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 px-4 py-8 text-center"
        >
          <IconUpload className="mb-2 h-8 w-8 text-slate-300" />
          <p className="text-sm text-slate-500">Tarik &amp; lepas .zip di sini, atau</p>
          <input
            ref={inputRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onZip(f)
              e.target.value = ''
            }}
          />
          <button
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:opacity-40"
          >
            {busy ? 'Mengekstrak…' : 'Pilih file .zip'}
          </button>
          <p className="mt-2 text-xs text-slate-400">Entrypoint tidak wajib — kamu jalankan kodenya secara interaktif.</p>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!busy) onClone(url.trim(), ref.trim())
          }}
          className="space-y-3"
        >
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">URL repo (publik)</label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              className="input w-full"
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Branch / tag / commit (opsional)</label>
            <input
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              placeholder="main"
              className="input w-full"
            />
          </div>
          <button
            type="submit"
            disabled={busy || !url.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-violet-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-violet-400 disabled:opacity-40"
          >
            <IconGithub className="h-4 w-4" /> {busy ? 'Meng-clone…' : 'Clone & buka'}
          </button>
        </form>
      )}

      {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
    </div>
  )
}

// --------------------------------------------------------- file explorer (p3/p4)
function FileExplorer({
  tree,
  busy,
  mode,
  onOpen,
  onRefresh,
  onDownload,
  onPush,
  onChangeProject,
}: {
  tree: FileNode
  busy: boolean
  mode: NotebookMode
  onOpen: (path: string, name: string) => void
  onRefresh: () => void
  onDownload: () => void
  onPush: () => void
  onChangeProject: () => void
}) {
  return (
    <aside className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200 lg:sticky lg:top-20">
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
        <IconFolder className="h-4 w-4 text-amber-500" />
        <span className="flex-1 truncate text-xs font-semibold text-slate-700">{tree.name || 'project'}</span>
        {mode === 'github' && (
          <button onClick={onPush} title="Commit & push ke GitHub" className="text-slate-400 hover:text-violet-600">
            <IconGithub className="h-3.5 w-3.5" />
          </button>
        )}
        <button onClick={onDownload} title="Unduh project (.zip)" className="text-slate-400 hover:text-brand-600">
          <IconDownload className="h-3.5 w-3.5" />
        </button>
        <button onClick={onRefresh} title="Muat ulang" className="text-slate-400 hover:text-brand-600" disabled={busy}>
          <IconRefresh className={cn('h-3.5 w-3.5', busy && 'animate-spin')} />
        </button>
        <button onClick={onChangeProject} title="Ganti project" className="text-slate-400 hover:text-rose-600">
          <IconX className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="max-h-[28rem] overflow-auto p-1.5">
        {tree.children && tree.children.length > 0 ? (
          tree.children.map((node) => (
            <TreeNode key={node.path} node={node} depth={0} onOpen={onOpen} />
          ))
        ) : (
          <p className="px-2 py-3 text-xs text-slate-400">Project kosong.</p>
        )}
      </div>
    </aside>
  )
}

function TreeNode({
  node,
  depth,
  onOpen,
}: {
  node: FileNode
  depth: number
  onOpen: (path: string, name: string) => void
}) {
  const [open, setOpen] = useState(depth < 1)
  const pad = { paddingLeft: `${depth * 12 + 8}px` }

  if (node.type === 'file') {
    return (
      <button
        onClick={() => onOpen(node.path, node.name)}
        style={pad}
        className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-xs text-slate-600 hover:bg-brand-50 hover:text-brand-700"
      >
        <IconFile className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <span className="flex-1 truncate">{node.name}</span>
        {node.size != null && <span className="shrink-0 text-[10px] text-slate-300">{fmtBytes(node.size)}</span>}
      </button>
    )
  }

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        style={pad}
        className="flex w-full items-center gap-1 rounded-md py-1 pr-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-100"
      >
        <IconChevron className={cn('h-3 w-3 shrink-0 text-slate-400 transition', open && 'rotate-90')} />
        <IconFolder className="h-3.5 w-3.5 shrink-0 text-amber-500" />
        <span className="flex-1 truncate">{node.name}</span>
      </button>
      {open &&
        node.children?.map((child) => (
          <TreeNode key={child.path} node={child} depth={depth + 1} onOpen={onOpen} />
        ))}
    </div>
  )
}

// ---------------------------------------------------------------- preview file
function FilePreview({
  file,
  onClose,
  onLoadToCell,
}: {
  file: InteractiveFile
  onClose: () => void
  onLoadToCell: () => void
}) {
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
          <IconFile className="h-4 w-4 text-slate-400" />
          <span className="flex-1 truncate font-mono text-xs text-slate-600">{file.path}</span>
          {file.truncated && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">dipotong</span>}
          <button
            onClick={onLoadToCell}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-brand-500"
          >
            <IconPlus className="h-3.5 w-3.5" /> Muat ke sel
          </button>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <Editor
            height="60vh"
            language={file.language}
            theme="vs-dark"
            value={file.content}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontSize: 13,
              scrollBeyondLastLine: false,
              automaticLayout: true,
              wordWrap: 'on',
            }}
            loading={<div className="p-3 text-xs text-slate-400">Memuat…</div>}
          />
        </div>
      </div>
    </div>
  )
}

// ----------------------------------------------------------- push GitHub (p4)
function PushPanel({
  busy,
  onClose,
  onPush,
}: {
  busy: boolean
  onClose: () => void
  onPush: (message: string, token: string) => void
}) {
  const [message, setMessage] = useState('Update from ComputeHub')
  const [token, setToken] = useState('')
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
          <IconGithub className="h-4 w-4 text-violet-500" />
          <span className="flex-1 text-sm font-semibold text-slate-700">Commit &amp; Push ke GitHub</span>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!busy && token.trim()) onPush(message, token.trim())
          }}
          className="space-y-3 p-4"
        >
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Pesan commit</label>
            <input
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              className="input w-full"
              placeholder="Update from ComputeHub"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              GitHub Personal Access Token (scope: repo)
            </label>
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              type="password"
              autoComplete="off"
              className="input w-full font-mono"
              placeholder="ghp_… / github_pat_…"
              required
            />
            <p className="mt-1 text-[11px] text-slate-400">
              Dipakai sekali untuk push ini saja — <b>tidak disimpan</b>. Butuh akses tulis ke repo.
            </p>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100"
            >
              Batal
            </button>
            <button
              type="submit"
              disabled={busy || !token.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-violet-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-violet-400 disabled:opacity-40"
            >
              <IconGithub className="h-4 w-4" /> {busy ? 'Meng-push…' : 'Push'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
