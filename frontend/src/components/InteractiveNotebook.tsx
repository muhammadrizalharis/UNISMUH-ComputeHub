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
import { applyCarriageReturns, parseNotebook, stripAnsi, type CellOutput } from '../lib/ipynb'
import { renderMarkdown } from '../lib/markdown'
import { NB_LS_PREFIX, pruneForeignDrafts } from '../lib/notebookDrafts'
import type { FileNode, InteractiveFile, InteractiveQueued } from '../lib/types'
import AssistantPanel from './AssistantPanel'
import CodeEditor from './CodeEditor'
import { OutputView } from './NotebookOutput'
import NotebookPreview from './NotebookPreview'
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
  IconSparkles,
  IconStop,
  IconUpload,
  IconX,
} from './icons'

export type NotebookMode = 'paste' | 'notebook' | 'zip' | 'github'

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

type KernelState = 'inactive' | 'queued' | 'starting' | 'idle' | 'busy' | 'disconnected' | 'error'

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
function makeCell(code = '', kind: CellKind = 'code', id?: string): Cell {
  seq += 1
  return {
    id: id ?? `cell-${Date.now()}-${seq}`,
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

// Ingat session_id kernel per-mode & per-USER supaya saat user PINDAH MENU / WINDOW /
// TAB atau REFRESH lalu kembali, frontend menyambung ULANG ke sesi yang sama & menerima
// REPLAY output sel yang sedang berjalan (progress lanjut tampil, TIDAK beku). Disimpan
// di module (cepat, utk pindah menu) + localStorage (tahan refresh / tab dibuang browser).
const sessionStore = new Map<string, string>()
const SESSION_LS_PREFIX = 'ch:isess:'

function saveSession(skey: string, sid: string): void {
  sessionStore.set(skey, sid)
  try {
    localStorage.setItem(SESSION_LS_PREFIX + skey, sid)
  } catch {
    /* localStorage nonaktif -> module store tetap jalan utk pindah menu */
  }
}

function loadSession(skey: string): string | undefined {
  const mem = sessionStore.get(skey)
  if (mem) return mem
  try {
    return localStorage.getItem(SESSION_LS_PREFIX + skey) ?? undefined
  } catch {
    return undefined
  }
}

function clearSession(skey: string): void {
  sessionStore.delete(skey)
  try {
    localStorage.removeItem(SESSION_LS_PREFIX + skey)
  } catch {
    /* noop */
  }
}

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
    const arr = JSON.parse(raw) as { id?: string; kind?: string; code?: string }[]
    if (!Array.isArray(arr) || arr.length === 0) return null
    return arr.map((c) => makeCell(c.code ?? '', c.kind === 'markdown' ? 'markdown' : 'code', c.id))
  } catch {
    return null
  }
}

function saveLocalCells(mode: NotebookMode, uid: number, cells: Cell[]): void {
  try {
    // Simpan ID sel juga -> setelah REFRESH, ID tetap sama sehingga REPLAY output dari
    // buffer server (yang memakai cell_id lama) tetap menempel ke sel yang benar.
    const slim = cells.map((c) => ({ id: c.id, kind: c.kind, code: c.code }))
    const json = JSON.stringify(slim)
    if (json.length > LS_MAX_CHARS) return // jangan bebani localStorage
    localStorage.setItem(LS_PREFIX + storeKey(mode, uid), json)
  } catch {
    /* kuota penuh / localStorage nonaktif -> abaikan */
  }
}

// Gabungkan output stream BERUNTUN (nama sama) menjadi satu entri + timpa \r. Cegah
// ribuan entri untuk progress bar & menjaga output tetap ringkas.
function appendStream(outputs: CellOutput[], name: string, chunk: string): CellOutput[] {
  const last = outputs[outputs.length - 1]
  if (last && last.kind === 'stream' && last.name === name) {
    return [...outputs.slice(0, -1), { ...last, text: applyCarriageReturns(last.text + chunk) }]
  }
  return [...outputs, { kind: 'stream', name, text: applyCarriageReturns(chunk) }]
}

// Tinggi maksimum editor sel ≈ 68% tinggi layar; bila kode lebih panjang, editor
// auto-tinggi mengikuti isi (kode tak pernah terpotong) lalu BISA DI-SCROLL di dalam sel.
function cellMaxHeight(): number {
  const vh = typeof window !== 'undefined' ? window.innerHeight : 900
  return Math.max(360, Math.round(vh * 0.68))
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
  queued: { text: 'Mengantre giliran GPU…', cls: 'bg-violet-50 text-violet-700 ring-violet-600/20', dot: 'bg-violet-400 animate-pulse' },
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
    // Hanya 'paste' (scratchpad) yang dipulihkan dari localStorage agar aman saat refresh.
    // Mode 'notebook' (juga zip/github) MULAI KOSONG: sel hanya muncul SETELAH user
    // mengunggah .ipynb / memuat project — bukan sisa unggahan sebelumnya.
    if (mode === 'paste') {
      const local = loadLocalCells(mode, uid)
      if (local) return local
    }
    return starterCells(mode)
  })
  const [kernel, setKernel] = useState<KernelState>('inactive')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [gpuIndex, setGpuIndex] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Antrian GPU: posisi & estimasi tunggu saat semua slot penuh.
  const [queueInfo, setQueueInfo] = useState<{ position: number; eta: number | null } | null>(null)
  const queueCancelRef = useRef(false)

  // Project (zip/github)
  const [tree, setTree] = useState<FileNode | null>(() => notebookStore.get(skey)?.tree ?? null)
  const [projectBusy, setProjectBusy] = useState(false)
  const [projectError, setProjectError] = useState<string | null>(null)
  const [preview, setPreview] = useState<InteractiveFile | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pushOpen, setPushOpen] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)
  // Catatan Google Drive di paling atas notebook — bisa ditutup (per-user, persist).
  const [showDriveNote, setShowDriveNote] = useState(() => {
    try {
      return localStorage.getItem(`${LS_PREFIX}drivehint:${uid}`) !== '1'
    } catch {
      return true
    }
  })

  const wsRef = useRef<WebSocket | null>(null)
  const pendingRef = useRef<Map<string, () => void>>(new Map())
  const cellsRef = useRef<Cell[]>(cells)
  cellsRef.current = cells
  // Ref stabil ke skey supaya handler WS (closure lama) tetap menunjuk sesi yang benar.
  const skeyRef = useRef(skey)
  skeyRef.current = skey
  // Sel yang sedang aktif (di-klik/fokus) -> target tombol "Terapkan" dari asisten AI.
  const [activeId, setActiveId] = useState<string | null>(null)
  const activeIdRef = useRef<string | null>(null)
  activeIdRef.current = activeId
  // Cermin state kernel utk dibaca di cleanup unmount (deps kosong).
  const kernelRef = useRef<KernelState>(kernel)
  kernelRef.current = kernel
  // Auto-save notebook ke /persist (anti hilang saat refresh).
  const autosaveRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSavedRef = useRef<string>('')

  // Persist tampilan notebook per-mode (anti hilang saat pindah menu) + cadangan
  // kode ke localStorage (anti hilang saat refresh penuh browser).
  useEffect(() => {
    notebookStore.set(skey, { cells, tree })
    // localStorage HANYA utk 'paste' (scratchpad mandiri, aman saat refresh). 'notebook'
    // (dan zip/github) TIDAK dipersist supaya menu Notebook selalu mulai dari unggah
    // .ipynb tanpa sel sisa; project zip/github terikat kernel.
    if (mode === 'paste') saveLocalCells(mode, uid, cells)
  }, [skey, mode, uid, cells, tree])

  // Auto-save notebook ke Penyimpanan (/persist) -> kerja tak hilang walau refresh penuh.
  // Hanya 'paste' & 'notebook' (punya sel kode). Disimpan ke _autosave/<mode>.ipynb,
  // debounce 8 dtk & hanya bila isi berubah; bisa dipulihkan dari menu Penyimpanan.
  useEffect(() => {
    if (mode !== 'paste' && mode !== 'notebook') return
    if (cells.length === 0) return
    if (autosaveRef.current) clearTimeout(autosaveRef.current)
    autosaveRef.current = setTimeout(() => {
      const json = cellsToIpynb(cellsRef.current)
      if (json === lastSavedRef.current) return
      void api
        .saveWorkspaceFile(`_autosave/${mode}.ipynb`, json)
        .then(() => {
          lastSavedRef.current = json
          setSavedAt(new Date().toLocaleTimeString('id-ID'))
        })
        .catch(() => {})
    }, 8000)
    return () => {
      if (autosaveRef.current) clearTimeout(autosaveRef.current)
    }
  }, [cells, mode])

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
      ws.onclose = (ev) => {
        // 4404 = sesi tidak ada lagi di server (kernel sudah dibersihkan idle-reaper).
        // Bersihkan sesi tersimpan (module + localStorage) & tandai BELUM AKTIF (bukan
        // "idle" palsu) supaya Run berikutnya memesan kernel BARU.
        if (ev.code === 4404) {
          clearSession(skeyRef.current)
          setSessionId(null)
          setKernel('inactive')
        } else {
          setKernel((k) => (k === 'error' ? k : 'disconnected'))
        }
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
            // 'busy' menandai AWAL eksekusi sebuah sel. Reset output sel itu supaya
            // REPLAY (saat user kembali dari menu lain) tidak menumpuk di atas output lama.
            if (m.state === 'busy' && cid)
              patchCell(cid, (c) => ({ ...c, running: true, errored: false, outputs: [] }))
            break
          case 'stream':
            if (cid)
              patchCell(cid, (c) => ({
                ...c,
                outputs: appendStream(c.outputs, m.name || 'stdout', m.text || ''),
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
  const startKernel = useCallback(
    (s: { session_id: string; gpu_index: number }): string => {
      setSessionId(s.session_id)
      saveSession(skeyRef.current, s.session_id)
      setGpuIndex(s.gpu_index)
      setQueueInfo(null)
      setKernel('starting')
      connect(s.session_id)
      return s.session_id
    },
    [connect],
  )

  // Menunggu giliran GPU saat semua slot penuh. Polling status antrian; begitu
  // backend memberi sinyal "ready", sesi otomatis dimulai memakai ticket_id.
  const waitInQueue = useCallback(
    async (q: InteractiveQueued): Promise<string | null> => {
      queueCancelRef.current = false
      setKernel('queued')
      setQueueInfo({ position: q.position, eta: q.eta_seconds })
      for (;;) {
        if (queueCancelRef.current) {
          setKernel('inactive')
          setQueueInfo(null)
          return null
        }
        await new Promise((r) => setTimeout(r, 3000))
        if (queueCancelRef.current) {
          setKernel('inactive')
          setQueueInfo(null)
          return null
        }
        let st
        try {
          st = await api.getInteractiveQueue()
        } catch {
          continue
        }
        if (st.state === 'ready') {
          try {
            const s = await api.createInteractiveSession(mode, st.ticket_id)
            if ('queued' in s) {
              setQueueInfo({ position: s.position, eta: s.eta_seconds })
              continue
            }
            return startKernel(s)
          } catch (e) {
            setKernel('error')
            setError((e as Error)?.message || 'Gagal memulai kernel.')
            setQueueInfo(null)
            return null
          }
        } else if (st.state === 'queued') {
          setQueueInfo({ position: st.position ?? 0, eta: st.eta_seconds ?? null })
        } else {
          // Tiket kedaluwarsa / hilang -> coba pesan ulang dari awal.
          try {
            const s = await api.createInteractiveSession(mode)
            if ('queued' in s) {
              setQueueInfo({ position: s.position, eta: s.eta_seconds })
              continue
            }
            return startKernel(s)
          } catch {
            continue
          }
        }
      }
    },
    [mode, startKernel],
  )

  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (sessionId) return sessionId
    setKernel('starting')
    setError(null)
    try {
      const s = await api.createInteractiveSession(mode)
      if ('queued' in s) return await waitInQueue(s)
      return startKernel(s)
    } catch (e) {
      setKernel('error')
      setError((e as Error)?.message || 'Gagal memulai kernel.')
      return null
    }
  }, [sessionId, mode, waitInQueue, startKernel])

  // Keluar dari antrian (tombol batal / saat meninggalkan halaman).
  const leaveQueue = useCallback(() => {
    queueCancelRef.current = true
    api.leaveInteractiveQueue().catch(() => {})
    setQueueInfo(null)
    setKernel('inactive')
  }, [])

  useEffect(() => {
    // Bersihkan draf milik akun lain / legacy -> kode tidak bocor antar akun.
    pruneForeignDrafts(uid)
    // Kernel TIDAK auto-start. Kernel + GPU baru menyala saat user menekan Run
    // (paste/notebook) atau mengunggah/clone project (zip/github) -> hemat GPU.
    // TAPI bila user punya sesi yang MASIH berjalan (mis. pindah menu lalu kembali),
    // sambung ULANG supaya menerima REPLAY output sel yang sedang berjalan -> progress
    // lanjut tampil, bukan beku. Menyambung ke sesi HIDUP tidak memesan GPU baru.
    // loadSession() memakai module store (cepat, utk pindah menu) lalu localStorage
    // (tahan REFRESH / tab dibuang browser). Bila sesi sudah tak ada di server, WS
    // ditutup dgn kode 4404 -> handler onclose membersihkannya & menandai belum aktif.
    const cached = loadSession(skey)
    if (cached) {
      setSessionId(cached)
      setKernel('starting')
      connect(cached)
    }
    return () => {
      wsRef.current?.close()
      // Hentikan polling antrian & lepaskan tiket bila sedang mengantre saat
      // user pindah halaman (cegah tiket "menggantung" memesan GPU).
      if (queueCancelRef.current === false && kernelRef.current === 'queued') {
        api.leaveInteractiveQueue().catch(() => {})
      }
      queueCancelRef.current = true
      // Kernel dibiarkan hidup saat pindah halaman; idle reaper membebaskan GPU.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Saat TAB/WINDOW kembali aktif: bila koneksi WS sempat ditutup browser (tab lama di
  // latar) TAPI kita masih punya sesi tersimpan -> sambung ULANG supaya output yang
  // berjalan (di-buffer server) muncul lagi & progress lanjut. Bila WS masih terbuka,
  // biarkan apa adanya (output real-time tetap mengalir, tak perlu sambung ulang).
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      const ws = wsRef.current
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
      const sid = loadSession(skey)
      if (sid) {
        setSessionId(sid)
        setKernel('starting')
        connect(sid)
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [skey, connect])

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
    clearSession(skeyRef.current)
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

  // ---- poin 3 & 4: muat project (FOLDER, chunked) + buka file ----
  const uploadFolder = useCallback(
    async (files: File[]) => {
      if (!files.length) return
      setProjectBusy(true)
      setProjectError(null)
      try {
        const sid = await ensureSession()
        if (!sid) return
        const CHUNK = 24 * 1024 * 1024 // di bawah batas body nginx
        const totalBytes = files.reduce((s, f) => s + f.size, 0) || 1
        let sent = 0
        let started = false
        for (const f of files) {
          const rel =
            (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name
          if (f.size === 0) {
            await api.uploadInteractiveFolderChunk(sid, rel, true, !started, new Blob([]))
            started = true
            continue
          }
          for (let off = 0; off < f.size; off += CHUNK) {
            const blob = f.slice(off, Math.min(off + CHUNK, f.size))
            await api.uploadInteractiveFolderChunk(sid, rel, off === 0, !started, blob)
            started = true
            sent += blob.size
            setNotice(`Mengunggah folder… ${Math.min(99, Math.round((sent / totalBytes) * 100))}%`)
          }
        }
        const res = await api.finalizeInteractiveFolder(sid)
        setTree(res.tree)
        setCells((cs) => (cs.length ? cs : [makeCell('')]))
        const rootName =
          (files[0] as File & { webkitRelativePath?: string }).webkitRelativePath?.split(
            '/',
          )[0] || 'project'
        setNotice(`Folder "${rootName}" dimuat. CWD kernel kini di folder project.`)
      } catch (e) {
        setNotice(null)
        setProjectError((e as Error).message || 'Gagal mengunggah folder.')
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

  // ---- CRUD file/folder ala VS Code (buat/rename/hapus) di workdir kernel ----
  const createFile = useCallback(
    async (dir: string) => {
      if (!sessionId) return
      const nm = window.prompt(dir ? `Nama file baru di "${dir}/":` : 'Nama file baru (mis. main.py):')
      if (!nm?.trim()) return
      const path = dir ? `${dir}/${nm.trim()}` : nm.trim()
      try {
        setTree((await api.writeInteractiveFile(sessionId, path, '')).tree)
        setNotice(`File "${path}" dibuat.`)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal membuat file.')
      }
    },
    [sessionId],
  )

  const createFolder = useCallback(
    async (dir: string) => {
      if (!sessionId) return
      const nm = window.prompt(dir ? `Nama folder baru di "${dir}/":` : 'Nama folder baru:')
      if (!nm?.trim()) return
      const path = dir ? `${dir}/${nm.trim()}` : nm.trim()
      try {
        setTree((await api.mkdirInteractive(sessionId, path)).tree)
        setNotice(`Folder "${path}" dibuat.`)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal membuat folder.')
      }
    },
    [sessionId],
  )

  const renameItem = useCallback(
    async (path: string, curName: string) => {
      if (!sessionId) return
      const nm = window.prompt('Nama baru:', curName)
      if (!nm?.trim() || nm.trim() === curName) return
      const parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
      const newPath = parent ? `${parent}/${nm.trim()}` : nm.trim()
      try {
        setTree((await api.renameInteractive(sessionId, path, newPath)).tree)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal mengganti nama.')
      }
    },
    [sessionId],
  )

  const deleteItem = useCallback(
    async (path: string) => {
      if (!sessionId) return
      if (!window.confirm(`Hapus "${path}"? Tindakan ini tidak bisa dibatalkan.`)) return
      try {
        setTree((await api.deleteInteractiveItem(sessionId, path)).tree)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal menghapus.')
      }
    },
    [sessionId],
  )

  const saveFile = useCallback(
    async (path: string, content: string) => {
      if (!sessionId) return
      try {
        setTree((await api.writeInteractiveFile(sessionId, path, content)).tree)
        setNotice(`"${path}" disimpan.`)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal menyimpan file.')
      }
    },
    [sessionId],
  )

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

  // Simpan notebook ke Penyimpanan persisten (/persist) -> tetap ada antar-sesi (ala Colab Drive).
  const saveToWorkspace = useCallback(async () => {
    const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
    const input = window.prompt(
      'Simpan notebook ke Penyimpanan sebagai:',
      `notebooks/notebook-${ts}.ipynb`,
    )
    if (!input) return
    const path = input.toLowerCase().endsWith('.ipynb') ? input : `${input}.ipynb`
    try {
      const json = cellsToIpynb(cellsRef.current)
      const r = await api.saveWorkspaceFile(path, json)
      setNotice(`Notebook disimpan ke Penyimpanan: ${r.path}`)
    } catch (e) {
      setNotice((e as Error).message || 'Gagal menyimpan ke Penyimpanan.')
    }
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
  const canRun = kernel !== 'starting' && kernel !== 'queued' && !kbusy
  const isProjectMode = mode === 'zip' || mode === 'github'

  // ----- Asisten AI (panel kanan: ciut/lebar + resize dengan seret) -----
  const [assistantCollapsed, setAssistantCollapsed] = useState(
    () => localStorage.getItem('nb_assistant_collapsed') === '1',
  )
  const [assistantWidth, setAssistantWidth] = useState(() => {
    const v = Number(localStorage.getItem('nb_assistant_w'))
    return v >= 280 && v <= 720 ? v : 380
  })
  const assistantWidthRef = useRef(assistantWidth)
  assistantWidthRef.current = assistantWidth
  useEffect(() => {
    localStorage.setItem('nb_assistant_collapsed', assistantCollapsed ? '1' : '0')
  }, [assistantCollapsed])

  const getAssistantContext = useCallback(
    () =>
      cellsRef.current
        .map((c, i) => {
          const tag = c.kind === 'markdown' ? 'teks/markdown' : 'kode'
          const lang = c.kind === 'markdown' ? 'markdown' : 'python'
          const body = c.code.trim() ? c.code : '(kosong)'
          let block = `### Sel ${i + 1} (${tag})\n\`\`\`${lang}\n${body}\n\`\`\``
          // Sertakan OUTPUT/ERROR sel kode supaya asisten melihat masalah NYATA
          // (mis. ModuleNotFoundError cupy) dan tidak menjawab ngawur.
          if (c.kind === 'code' && c.outputs.length) {
            const outText = c.outputs
              .map((o) => {
                if (o.kind === 'stream') return o.text
                if (o.kind === 'error')
                  return `[ERROR] ${o.ename}: ${o.evalue}\n${o.traceback
                    .map(stripAnsi)
                    .join('\n')}`
                if (o.data['text/plain']) return o.data['text/plain']
                if (o.data['image/png'] || o.data['image/jpeg']) return '[output: gambar]'
                if (o.data['text/html']) return '[output: HTML]'
                return ''
              })
              .filter(Boolean)
              .join('\n')
              .trim()
            if (outText) {
              const clipped =
                outText.length > 4000 ? `${outText.slice(0, 4000)}\n…(dipotong)` : outText
              block += `\nOutput / hasil eksekusi:\n\`\`\`\n${clipped}\n\`\`\``
            }
          }
          return block
        })
        .join('\n\n'),
    [],
  )
  const insertAssistantCode = useCallback((code: string) => {
    setCells((cs) => [...cs, makeCell(code, 'code')])
    setNotice('Kode dari asisten disisipkan sebagai sel baru di bawah.')
  }, [])
  // Terapkan kode asisten dgn MENIMPA sel aktif (yang sedang dikerjakan). Bila belum ada
  // sel aktif, jatuh ke menyisipkan sel baru. Tetap aman: user melihat kodenya sebelum klik.
  const applyAssistantCode = useCallback((code: string) => {
    const id = activeIdRef.current
    const idx = cellsRef.current.findIndex((c) => c.id === id && c.kind === 'code')
    if (idx === -1) {
      setCells((cs) => [...cs, makeCell(code, 'code')])
      setNotice(
        'Belum ada sel aktif — kode disisipkan sebagai sel baru. Klik sel yang mau diperbaiki lalu "Terapkan".',
      )
      return
    }
    setCells((cs) => cs.map((c, i) => (i === idx ? { ...c, code, editing: false } : c)))
    setNotice(`Kode asisten diterapkan ke Sel ${idx + 1} (isi lama ditimpa).`)
  }, [])
  const startAssistantResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = assistantWidthRef.current
    const onMove = (ev: MouseEvent) => {
      setAssistantWidth(Math.min(720, Math.max(280, startW + (startX - ev.clientX))))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.userSelect = ''
      localStorage.setItem('nb_assistant_w', String(assistantWidthRef.current))
    }
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [])

  const cellList = useMemo(
    () => (
      <div className="space-y-3">
        {cells.map((cell) => (
          <div
            key={cell.id}
            onMouseDownCapture={() => setActiveId(cell.id)}
            onFocusCapture={() => setActiveId(cell.id)}
            className={
              'rounded-xl transition ' +
              (activeId === cell.id ? 'ring-2 ring-brand-300/70' : 'ring-0')
            }
          >
            <NotebookCell
              cell={cell}
              disabled={!canRun}
              onChange={(code) => patchCell(cell.id, (c) => ({ ...c, code }))}
              onRun={() => void runCell(cellsRef.current.find((c) => c.id === cell.id) || cell)}
              onEdit={() => patchCell(cell.id, (c) => ({ ...c, editing: true }))}
              onDelete={() => deleteCell(cell.id)}
              onAddBelow={() => addCell(cell.id)}
              canDelete={cells.length > 1}
            />
          </div>
        ))}
      </div>
    ),
    [cells, canRun, patchCell, runCell, deleteCell, addCell, activeId],
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
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1 space-y-4">
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
        {savedAt && (
          <span
            className="hidden items-center gap-1 text-xs text-slate-500 sm:inline-flex"
            title="Notebook tersimpan otomatis ke Penyimpanan (/persist)"
          >
            ✓ tersimpan {savedAt}
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
          <button
            onClick={() => void saveToWorkspace()}
            disabled={cells.length === 0}
            title="Simpan notebook ke Penyimpanan (/persist) — tetap ada antar-sesi"
            className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-white/20 disabled:opacity-40"
          >
            <IconFolder className="h-3.5 w-3.5" /> Simpan
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
              onClick={() => {
                // Sesi masih tersimpan -> coba SAMBUNG ULANG (kalau hidup: reattach +
                // replay; kalau sudah mati: server balas 4404 -> onclose bersihkan sesi
                // & set 'inactive', lalu Run/upload berikutnya pesan kernel BARU).
                // Tak ada sesi -> langsung pesan kernel baru.
                if (sessionId) {
                  setKernel('starting')
                  connect(sessionId)
                } else {
                  void ensureSession()
                }
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500"
            >
              <IconRefresh className="h-3.5 w-3.5" /> Sambungkan ulang
            </button>
          ) : null}
        </div>
      </div>

      {showDriveNote && (
        <div className="flex items-start gap-3 rounded-lg bg-sky-50 px-4 py-3 text-sm text-sky-800 ring-1 ring-inset ring-sky-600/20">
          <div className="min-w-0 flex-1 space-y-1">
            <p className="font-semibold">Mengakses Google Drive di sini</p>
            <p>
              Perintah Google Colab{' '}
              <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">from google.colab import drive</code>{' '}
              /{' '}
              <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">drive.mount()</code>{' '}
              <b>tidak berlaku</b> di ComputeHub (itu khusus Google Colab). Gunakan salah satu cara berikut:
            </p>
            <ul className="ml-4 list-disc space-y-0.5">
              <li>
                File/folder Drive yang di-<b>share publik</b> → pakai{' '}
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">gdown</code> (sudah terpasang), contoh:{' '}
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">gdown.download("LINK_DRIVE", "data.csv")</code>.
              </li>
              <li>
                File milik sendiri → klik tombol <b>Upload</b>, lalu baca dari path lokal, mis.{' '}
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">pd.read_csv("data.csv")</code>.
              </li>
            </ul>
          </div>
          <button
            onClick={() => {
              setShowDriveNote(false)
              try {
                localStorage.setItem(`${LS_PREFIX}drivehint:${uid}`, '1')
              } catch {
                /* abaikan */
              }
            }}
            className="shrink-0 text-sky-400 transition hover:text-sky-600"
            title="Tutup catatan"
          >
            <IconX className="h-4 w-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          {error}
        </div>
      )}
      {kernel === 'queued' && queueInfo && (
        <div className="flex items-start gap-3 rounded-lg bg-violet-50 px-4 py-3 text-sm text-violet-700 ring-1 ring-inset ring-violet-600/20">
          <span className="mt-0.5 h-2 w-2 shrink-0 animate-pulse rounded-full bg-violet-500" />
          <div className="flex-1">
            <p className="font-medium">
              Semua GPU sedang penuh — kamu di antrian{queueInfo.position > 0 ? ` posisi ${queueInfo.position}` : ''}.
            </p>
            <p className="text-violet-600/80">
              Sesi akan otomatis dimulai begitu ada slot kosong
              {queueInfo.eta != null ? `, perkiraan ~${Math.max(1, Math.round(queueInfo.eta / 60))} menit` : ''}. Halaman boleh dibiarkan terbuka.
            </p>
          </div>
          <button
            onClick={leaveQueue}
            className="shrink-0 rounded-lg bg-white/70 px-2.5 py-1.5 text-xs font-medium text-violet-700 ring-1 ring-inset ring-violet-600/20 transition hover:bg-white"
          >
            Keluar antrian
          </button>
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
          onFolder={uploadFolder}
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
              onNewFile={createFile}
              onNewFolder={createFolder}
              onRename={renameItem}
              onDelete={deleteItem}
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
          key={preview.path}
          file={preview}
          onClose={() => setPreview(null)}
          onLoadToCell={() => loadPreviewToCell(preview)}
          onSave={(content) => void saveFile(preview.path, content)}
        />
      )}

      {pushOpen && (
        <PushPanel busy={pushing} onClose={() => setPushOpen(false)} onPush={doPush} />
      )}
      </div>

      {/* Dock Asisten AI (kanan): strip saat diciutkan, panel + resizer saat dibuka. lg+ */}
      {assistantCollapsed ? (
        <button
          onClick={() => setAssistantCollapsed(false)}
          title="Buka Asisten AI"
          className="sticky top-2 hidden shrink-0 flex-col items-center gap-2 self-start rounded-xl border border-slate-200 bg-white px-2 py-3 text-slate-500 shadow-sm transition hover:border-brand-300 hover:text-brand-600 lg:flex"
        >
          <IconSparkles className="h-5 w-5 text-brand-500" />
          <span className="text-xs font-semibold tracking-wide [writing-mode:vertical-rl]">
            Asisten AI
          </span>
        </button>
      ) : (
        <div
          className="sticky top-2 hidden shrink-0 self-start lg:flex"
          style={{ height: 'calc(100vh - 6rem)' }}
        >
          <div
            onMouseDown={startAssistantResize}
            title="Seret untuk mengubah lebar"
            className="flex w-2 cursor-col-resize items-center justify-center"
          >
            <div className="h-10 w-1 rounded-full bg-slate-300" />
          </div>
          <div style={{ width: assistantWidth }} className="h-full">
            <AssistantPanel
              onCollapse={() => setAssistantCollapsed(true)}
              getContext={getAssistantContext}
              onInsertCode={insertAssistantCode}
              onApplyCode={applyAssistantCode}
            />
          </div>
        </div>
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
  editorMinHeight = 72,
  editorMaxHeight,
}: {
  cell: Cell
  disabled: boolean
  onChange: (code: string) => void
  onRun: () => void
  onEdit: () => void
  onDelete: () => void
  onAddBelow: () => void
  canDelete: boolean
  editorMinHeight?: number
  editorMaxHeight?: number
}) {
  const onRunRef = useRef(onRun)
  onRunRef.current = onRun

  const isMd = cell.kind === 'markdown'
  const showEditor = !isMd || cell.editing

  const editor = (
    <CodeEditor
      autoGrow
      minHeight={editorMinHeight}
      maxHeight={editorMaxHeight ?? cellMaxHeight()}
      language={isMd ? 'markdown' : 'python'}
      value={cell.code}
      onChange={(v) => onChange(v)}
      summaryMode="problems-only"
      onMount={(editorInst, monaco) => {
        editorInst.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () =>
          onRunRef.current(),
        )
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

// Output panjang dipangkas (ala terminal VS Code): tampilkan sebagian ATAS + BAWAH,
// dengan tombol JELAS "Tampilkan semua" -> lihat SEMUA baris (mis. tiap epoch training)
// dalam kotak tinggi yang bisa di-scroll. Semua teks tetap tersimpan, tak ada yg hilang.
// Output sel (OutputView + LongText + OutputActions) dipindah ke ./NotebookOutput
// agar dipakai bersama NotebookPreview (baca .ipynb di detail job).

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
  onFolder,
  onClone,
}: {
  mode: NotebookMode
  busy: boolean
  error: string | null
  onFolder: (files: File[]) => void
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
          {isZip ? 'Unggah project (folder)' : 'Clone repo GitHub'}
        </h3>
      </div>

      {isZip ? (
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const fs = Array.from(e.dataTransfer.files || [])
            if (fs.length && !busy) onFolder(fs)
          }}
          className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 px-4 py-8 text-center"
        >
          <IconUpload className="mb-2 h-8 w-8 text-slate-300" />
          <p className="text-sm text-slate-500">Pilih SATU folder project (ukuran nyata, tanpa zip)</p>
          <input
            ref={inputRef}
            type="file"
            multiple
            // @ts-expect-error webkitdirectory: pemilih FOLDER (Chrome/Edge/Firefox)
            webkitdirectory=""
            directory=""
            className="hidden"
            onChange={(e) => {
              const fs = Array.from(e.target.files ?? [])
              if (fs.length) onFolder(fs)
              e.target.value = ''
            }}
          />
          <button
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:opacity-40"
          >
            {busy ? 'Mengunggah…' : 'Pilih Folder'}
          </button>
          <p className="mt-2 text-xs text-slate-400">Semua isi folder diunggah apa adanya; batas = sisa kuota penyimpanan Anda.</p>
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
  onNewFile,
  onNewFolder,
  onRename,
  onDelete,
  onDownload,
  onPush,
  onChangeProject,
}: {
  tree: FileNode
  busy: boolean
  mode: NotebookMode
  onOpen: (path: string, name: string) => void
  onRefresh: () => void
  onNewFile: (dir: string) => void
  onNewFolder: (dir: string) => void
  onRename: (path: string, name: string) => void
  onDelete: (path: string) => void
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
      <div className="flex items-center gap-1 border-b border-slate-100 px-2 py-1">
        <button
          onClick={() => onNewFile('')}
          className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
        >
          + File
        </button>
        <button
          onClick={() => onNewFolder('')}
          className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
        >
          + Folder
        </button>
      </div>
      <div className="max-h-[28rem] overflow-auto p-1.5">
        {tree.children && tree.children.length > 0 ? (
          tree.children.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              onOpen={onOpen}
              onNewFile={onNewFile}
              onNewFolder={onNewFolder}
              onRename={onRename}
              onDelete={onDelete}
            />
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
  onNewFile,
  onNewFolder,
  onRename,
  onDelete,
}: {
  node: FileNode
  depth: number
  onOpen: (path: string, name: string) => void
  onNewFile: (dir: string) => void
  onNewFolder: (dir: string) => void
  onRename: (path: string, name: string) => void
  onDelete: (path: string) => void
}) {
  const [open, setOpen] = useState(depth < 1)
  const pad = { paddingLeft: `${depth * 12 + 8}px` }

  if (node.type === 'file') {
    return (
      <div className="group flex items-center rounded-md hover:bg-brand-50" style={pad}>
        <button
          onClick={() => onOpen(node.path, node.name)}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-xs text-slate-600 group-hover:text-brand-700"
        >
          <IconFile className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate">{node.name}</span>
        </button>
        <span className="flex shrink-0 items-center pr-1 opacity-0 group-hover:opacity-100">
          <button onClick={() => onRename(node.path, node.name)} title="Ganti nama" className="px-1 text-[11px] text-slate-400 hover:text-brand-600">✎</button>
          <button onClick={() => onDelete(node.path)} title="Hapus" className="text-slate-400 hover:text-rose-600"><IconX className="h-3 w-3" /></button>
        </span>
      </div>
    )
  }

  return (
    <div>
      <div className="group flex items-center rounded-md hover:bg-slate-100" style={pad}>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 flex-1 items-center gap-1 py-1 text-left text-xs font-medium text-slate-700"
        >
          <IconChevron className={cn('h-3 w-3 shrink-0 text-slate-400 transition', open && 'rotate-90')} />
          <IconFolder className="h-3.5 w-3.5 shrink-0 text-amber-500" />
          <span className="truncate">{node.name}</span>
        </button>
        <span className="flex shrink-0 items-center pr-1 opacity-0 group-hover:opacity-100">
          <button onClick={() => onNewFile(node.path)} title="File baru di sini" className="text-slate-400 hover:text-brand-600"><IconFile className="h-3 w-3" /></button>
          <button onClick={() => onNewFolder(node.path)} title="Folder baru di sini" className="ml-0.5 text-slate-400 hover:text-brand-600"><IconFolder className="h-3 w-3" /></button>
          <button onClick={() => onRename(node.path, node.name)} title="Ganti nama" className="ml-0.5 px-0.5 text-[11px] text-slate-400 hover:text-brand-600">✎</button>
          <button onClick={() => onDelete(node.path)} title="Hapus" className="text-slate-400 hover:text-rose-600"><IconX className="h-3 w-3" /></button>
        </span>
      </div>
      {open &&
        node.children?.map((child) => (
          <TreeNode
            key={child.path}
            node={child}
            depth={depth + 1}
            onOpen={onOpen}
            onNewFile={onNewFile}
            onNewFolder={onNewFolder}
            onRename={onRename}
            onDelete={onDelete}
          />
        ))}
    </div>
  )
}

// ---------------------------------------------------------------- preview file
function FilePreview({
  file,
  onClose,
  onLoadToCell,
  onSave,
}: {
  file: InteractiveFile
  onClose: () => void
  onLoadToCell: () => void
  onSave: (content: string) => void
}) {
  const [content, setContent] = useState(file.content)
  const [dirty, setDirty] = useState(false)
  const editable = !file.truncated
  const isNotebook = file.path.toLowerCase().endsWith('.ipynb')
  // Notebook -> default tampilan ter-render; berkas lain selalu "mentah" (editor).
  const [raw, setRaw] = useState(!isNotebook)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className={cn(
          'flex max-h-[85vh] w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200',
          isNotebook ? 'max-w-4xl' : 'max-w-3xl',
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
          <IconFile className="h-4 w-4 text-slate-400" />
          <span className="flex-1 truncate font-mono text-xs text-slate-600">{file.path}</span>
          {isNotebook && (
            <div className="flex overflow-hidden rounded-lg ring-1 ring-slate-200">
              <button
                onClick={() => setRaw(false)}
                className={cn(
                  'px-2 py-1 text-[11px] font-medium transition',
                  !raw ? 'bg-brand-600 text-white' : 'text-slate-500 hover:bg-slate-50',
                )}
              >
                Notebook
              </button>
              <button
                onClick={() => setRaw(true)}
                className={cn(
                  'px-2 py-1 text-[11px] font-medium transition',
                  raw ? 'bg-brand-600 text-white' : 'text-slate-500 hover:bg-slate-50',
                )}
              >
                Kode mentah
              </button>
            </div>
          )}
          {file.truncated && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">dipotong (tak bisa edit)</span>}
          {editable && raw && (
            <button
              onClick={() => {
                onSave(content)
                setDirty(false)
              }}
              disabled={!dirty}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-40"
            >
              Simpan
            </button>
          )}
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
        <div className="min-h-0 flex-1 overflow-auto">
          {isNotebook && !raw ? (
            <NotebookPreview
              content={content}
              editable={editable}
              onSave={(c) => {
                setContent(c)
                onSave(c)
                setDirty(false)
              }}
              onEditRaw={() => setRaw(true)}
            />
          ) : (
            <Editor
              height="60vh"
              language={file.language}
              theme="vs-dark"
              value={content}
              onChange={(v) => {
                if (!editable) return
                setContent(v ?? '')
                setDirty(true)
              }}
              options={{
                readOnly: !editable,
                minimap: { enabled: false },
                fontSize: 13,
                scrollBeyondLastLine: false,
                automaticLayout: true,
                wordWrap: 'on',
              }}
              loading={<div className="p-3 text-xs text-slate-400">Memuat…</div>}
            />
          )}
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
