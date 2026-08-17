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
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import { applyCarriageReturns, parseNotebook, stripAnsi, type CellOutput } from '../lib/ipynb'
import { JOB_TEMPLATES } from '../lib/jobTemplates'
import { renderMarkdown } from '../lib/markdown'
import { defineOneDarkProDarker, ONE_DARK_PRO_DARKER } from '../lib/monacoTheme'
import { NB_LS_PREFIX, pruneForeignDrafts, registerLogoutCleanup } from '../lib/notebookDrafts'
import type { FileNode, InteractiveFile, InteractiveQueued } from '../lib/types'
import AssistantPanel from './AssistantPanel'
import CodeEditor from './CodeEditor'
import { isImagePath } from './ImagePreview'
import { OutputView } from './NotebookOutput'
import NotebookPreview from './NotebookPreview'
import {
  IconChevron,
  IconClock,
  IconCode,
  IconCopy,
  IconDownload,
  IconFile,
  IconFolder,
  IconGithub,
  IconGpu,
  IconImage,
  IconNotebook,
  IconPlay,
  IconPlus,
  IconRefresh,
  IconSparkles,
  IconStop,
  IconTerminal,
  IconTrash,
  IconUpload,
  IconX,
} from './icons'

// Lazy: xterm.js (~300KB) hanya dimuat saat user membuka terminal.
const TerminalPanel = lazy(() => import('./TerminalPanel'))

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
  expires_in_seconds?: number | null
}

// Sisa waktu (detik) saat peringatan "kernel akan berhenti" mulai ditampilkan.
const EXPIRY_WARN_SECONDS = 300

/** "12 menit" / "4:05" — sisa waktu sesi dalam bentuk yang mudah dibaca. */
function formatSisaWaktu(detik: number): string {
  if (detik <= 0) return '0:00'
  const m = Math.floor(detik / 60)
  const d = Math.floor(detik % 60)
  return `${m}:${String(d).padStart(2, '0')}`
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
type SavedNotebook = { cells: Cell[]; tree: FileNode | null; activeFilePath: string | null }
const notebookStore = new Map<string, SavedNotebook>()

// Satu tab explorer = satu berkas terbuka. 'notebook' dirender sebagai sel yang bisa
// dijalankan, 'text' sebagai editor, 'image' sebagai pratinjau.
type TabKind = 'notebook' | 'text' | 'image'
type OpenTab = { path: string; name: string; kind: TabKind }

// Cache sel (DENGAN OUTPUT) per FILE .ipynb dalam sesi -> pindah antar-notebook di explorer
// project & kembali TIDAK menghilangkan output (bertahan sampai logout / refresh penuh).
// Kunci: `${skey}:${path}`. Memori modul -> tahan pindah menu, tak bocor antar akun (skey).
const fileCellsStore = new Map<string, Cell[]>()

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

// Bersihkan SEMUA store notebook interaktif (memori + localStorage sesi) saat LOGOUT
// supaya sel/output/peta-kernel akun lama tak tersisa di browser bersama. Didaftarkan
// ke notebookDrafts (dipanggil dari auth.logout) -> tanpa import melingkar.
function clearInteractiveStores(): void {
  notebookStore.clear()
  fileCellsStore.clear()
  sessionStore.clear()
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(SESSION_LS_PREFIX)) keys.push(k)
    }
    keys.forEach((k) => localStorage.removeItem(k))
  } catch {
    /* noop */
  }
}
registerLogoutCleanup(clearInteractiveStores)

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

export default function InteractiveNotebook({
  mode = 'paste',
  templateId,
}: {
  mode?: NotebookMode
  // id template galeri (/templates) -> .ipynb-nya di-fetch & dimuat jadi sel.
  templateId?: string
}) {
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
  // Batas waktu sesi (epoch ms) dari server -> ditampilkan sbg hitung mundur supaya
  // kernel tidak terasa "mati sendiri". null = tak ada batas / belum diketahui.
  const [expiryAt, setExpiryAt] = useState<number | null>(null)
  const [nowTick, setNowTick] = useState(() => Date.now())
  const [error, setError] = useState<string | null>(null)
  // Pilihan versi Python kernel (mode docker). '' = default sistem. Daftar versi
  // dari backend (capabilities); dropdown terkunci saat sesi aktif.
  const [pyVer, setPyVer] = useState<string>('')
  const [pyVersions, setPyVersions] = useState<string[]>([])
  const [pyDefault, setPyDefault] = useState<string>('3.10')
  useEffect(() => {
    api
      .capabilities()
      .then((c) => {
        setPyVersions(c.python_versions ?? [])
        if (c.python_default) setPyDefault(c.python_default)
      })
      .catch(() => {})
  }, [])
  // Antrian GPU: posisi & estimasi tunggu saat semua slot penuh.
  const [queueInfo, setQueueInfo] = useState<{ position: number; eta: number | null } | null>(null)
  const queueCancelRef = useRef(false)

  // Project (zip/github)
  const [tree, setTree] = useState<FileNode | null>(() => notebookStore.get(skey)?.tree ?? null)
  const [projectBusy, setProjectBusy] = useState(false)
  const [projectError, setProjectError] = useState<string | null>(null)
  // Tab ala VS Code: beberapa berkas boleh terbuka sekaligus dan bisa dipindah-pindah
  // tanpa menutup yang lain. Isi tiap tab disimpan terpisah agar tak dibaca ulang.
  const [tabs, setTabs] = useState<OpenTab[]>([])
  const [activeTab, setActiveTab] = useState<string | null>(null)
  const [textFiles, setTextFiles] = useState<Record<string, InteractiveFile>>({})
  // Pratinjau GAMBAR (objectURL blob terautentikasi) -> di-revoke saat tab ditutup.
  const [imageUrls, setImageUrls] = useState<Record<string, string>>({})
  // CWD kernel (mis. /work/project) -> dipakai menu "Salin path" di explorer.
  const [cwd, setCwd] = useState('')
  // Path notebook .ipynb yang SEDANG dimuat ke sel (folder/zip/github) -> kunci cache
  // output per-file saat pindah antar-notebook.
  const [activeFilePath, setActiveFilePath] = useState<string | null>(
    () => notebookStore.get(skey)?.activeFilePath ?? null,
  )
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
  // Auto-refresh panel File setelah eksekusi: sel bisa membuat file/folder baru
  // (mis. output/) -> harus langsung tampil di explorer tanpa klik ↻ manual.
  const refreshTreeRef = useRef<(() => Promise<void>) | null>(null)
  const treeRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const projectModeRef = useRef(false)

  // Persist tampilan notebook per-mode (anti hilang saat pindah menu) + cadangan
  // kode ke localStorage (anti hilang saat refresh penuh browser).
  useEffect(() => {
    notebookStore.set(skey, { cells, tree, activeFilePath })
    // Cache sel (dgn OUTPUT) per FILE aktif -> pindah antar-notebook tak hilang output.
    if (activeFilePath) fileCellsStore.set(`${skey}:${activeFilePath}`, cells)
    // localStorage HANYA utk 'paste' (scratchpad mandiri, aman saat refresh), DI-DEBOUNCE
    // ~1 dtk supaya tak menulis tiap ketik (hemat). 'notebook'/zip/github tak dipersist.
    if (mode !== 'paste') return
    const t = setTimeout(() => saveLocalCells(mode, uid, cells), 1000)
    return () => clearTimeout(t)
  }, [skey, mode, uid, cells, tree, activeFilePath])

  // Bersihkan timer auto-refresh tree saat unmount (hindari refresh sesudah lepas).
  useEffect(
    () => () => {
      if (treeRefreshTimerRef.current) clearTimeout(treeRefreshTimerRef.current)
    },
    [],
  )

  // Revoke object URL gambar saat komponen dilepas (cegah bocor memori blob).
  // Pakai ref supaya efek ini tak ikut berjalan tiap ada tab gambar baru.
  const imageUrlsRef = useRef(imageUrls)
  imageUrlsRef.current = imageUrls
  useEffect(
    () => () => {
      Object.values(imageUrlsRef.current).forEach((u) => URL.revokeObjectURL(u))
    },
    [],
  )

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
        setExpiryAt(null)
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
        // Server mengirim sisa umur sesi di 'ready' dan berkala lewat 'expiry'.
        if (m.expires_in_seconds != null)
          setExpiryAt(Date.now() + m.expires_in_seconds * 1000)
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
              // Sel yang selesai mungkin membuat file/folder baru (mis. output/).
              // Segarkan panel File otomatis; debounce -> saat Run All cukup sekali
              // di akhir. Hanya di mode project (yang punya panel File).
              if (projectModeRef.current) {
                if (treeRefreshTimerRef.current) clearTimeout(treeRefreshTimerRef.current)
                treeRefreshTimerRef.current = setTimeout(() => void refreshTreeRef.current?.(), 500)
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
    (s: { session_id: string; gpu_index: number; python_version?: string }): string => {
      setSessionId(s.session_id)
      saveSession(skeyRef.current, s.session_id)
      setGpuIndex(s.gpu_index)
      // Sinkronkan pilihan dgn versi NYATA sesi (bisa beda bila sesi lama dipakai ulang).
      if (s.python_version) setPyVer(s.python_version)
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
            const s = await api.createInteractiveSession(mode, st.ticket_id, pyVer || undefined)
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
            const s = await api.createInteractiveSession(mode, undefined, pyVer || undefined)
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
    [mode, startKernel, pyVer],
  )

  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (sessionId) return sessionId
    setKernel('starting')
    setError(null)
    try {
      const s = await api.createInteractiveSession(mode, undefined, pyVer || undefined)
      if ('queued' in s) return await waitInQueue(s)
      return startKernel(s)
    } catch (e) {
      setKernel('error')
      setError((e as Error)?.message || 'Gagal memulai kernel.')
      return null
    }
  }, [sessionId, mode, waitInQueue, startKernel, pyVer])

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

  // ---- terminal web di dalam container sesi (toggle Ctrl+` ala VS Code) ----
  const [termOpen, setTermOpen] = useState(false)
  const toggleTerminal = useCallback(() => {
    setTermOpen((open) => {
      const next = !open
      // Terminal butuh container kernel hidup -> nyalakan dulu bila belum ada.
      if (next && !sessionId) void ensureSession()
      return next
    })
  }, [sessionId, ensureSession])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && !e.shiftKey && !e.altKey && e.code === 'Backquote') {
        e.preventDefault()
        toggleTerminal()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [toggleTerminal])

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

  // Riwayat sel terhapus (undo delete, ala Colab). Maks 30 entri terakhir.
  const [deletedStack, setDeletedStack] = useState<
    { cell: Cell; index: number }[]
  >([])

  const deleteCell = useCallback((id: string) => {
    // Baca via ref (bukan di dalam updater) -> aman dari double-invoke StrictMode.
    const cs = cellsRef.current
    const i = cs.findIndex((c) => c.id === id)
    if (cs.length <= 1 || i === -1) return
    setDeletedStack((st) => [...st.slice(-29), { cell: cs[i], index: i }])
    setCells((prev) => (prev.length <= 1 ? prev : prev.filter((c) => c.id !== id)))
  }, [])

  // Kembalikan sel terakhir yang dihapus ke posisi semula (kode + output utuh).
  const restoreDeletedCell = useCallback(() => {
    if (deletedStack.length === 0) return
    const { cell, index } = deletedStack[deletedStack.length - 1]
    setDeletedStack((st) => st.slice(0, -1))
    setCells((cs) => {
      if (cs.some((c) => c.id === cell.id)) return cs // guard dobel
      const copy = [...cs]
      copy.splice(Math.min(index, copy.length), 0, cell)
      return copy
    })
  }, [deletedStack])

  // Bersihkan SEMUA sel -> reset ke 1 sel kosong; semuanya masuk riwayat undo.
  const clearAllCells = useCallback(() => {
    const cs = cellsRef.current
    const hasContent =
      cs.length > 1 || cs.some((c) => c.code.trim() !== '' || c.outputs.length > 0)
    if (!hasContent) return
    if (
      !window.confirm(
        'Bersihkan semua sel? Sel yang dihapus masih bisa dikembalikan lewat tombol "Kembalikan sel".',
      )
    )
      return
    setDeletedStack((st) =>
      [...st, ...cs.map((cell, index) => ({ cell, index }))].slice(-30),
    )
    setCells([makeCell('', 'code')])
  }, [])

  // Geser urutan sel (dir -1 = naik, +1 = turun).
  const moveCell = useCallback((id: string, dir: -1 | 1) => {
    setCells((cs) => {
      const i = cs.findIndex((c) => c.id === id)
      const j = i + dir
      if (i === -1 || j < 0 || j >= cs.length) return cs
      const copy = [...cs]
      ;[copy[i], copy[j]] = [copy[j], copy[i]]
      return copy
    })
  }, [])

  // Duplikat sel (kode & jenis; output tidak ikut).
  const duplicateCell = useCallback((id: string) => {
    const cs = cellsRef.current
    const i = cs.findIndex((c) => c.id === id)
    if (i === -1) return
    const nc = makeCell(cs[i].code, cs[i].kind)
    setCells((prev) => {
      if (prev.some((c) => c.id === nc.id)) return prev
      const j = prev.findIndex((c) => c.id === id)
      if (j === -1) return prev
      const copy = [...prev]
      copy.splice(j + 1, 0, nc)
      return copy
    })
  }, [])

  // Sisipkan sel kosong relatif thd sel aktif (0 = di atas, 1 = di bawah).
  const insertRelative = useCallback((id: string | null, offset: 0 | 1) => {
    const nc = makeCell('', 'code')
    setCells((prev) => {
      if (prev.some((c) => c.id === nc.id)) return prev
      if (!id) return [...prev, nc]
      const i = prev.findIndex((c) => c.id === id)
      if (i === -1) return [...prev, nc]
      const copy = [...prev]
      copy.splice(i + offset, 0, nc)
      return copy
    })
  }, [])

  // Pintasan keyboard ala Jupyter (aktif saat TIDAK sedang mengetik di input/editor):
  // A = sel baru di atas sel aktif · B = di bawah · D D = hapus · M = toggle markdown.
  const lastDRef = useRef(0)
  useEffect(() => {
    const isTyping = (el: EventTarget | null): boolean => {
      const n = el as HTMLElement | null
      if (!n || !n.tagName) return false
      const tag = n.tagName.toLowerCase()
      return (
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select' ||
        n.isContentEditable ||
        Boolean(n.closest?.('.monaco-editor'))
      )
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isTyping(e.target)) return
      const id = activeIdRef.current
      const k = e.key.toLowerCase()
      if (k === 'a' || k === 'b') {
        e.preventDefault()
        insertRelative(id, k === 'a' ? 0 : 1)
      } else if (k === 'm' && id) {
        e.preventDefault()
        patchCell(id, (c) => ({
          ...c,
          kind: c.kind === 'markdown' ? 'code' : 'markdown',
          editing: true,
        }))
      } else if (k === 'd' && id) {
        const now = Date.now()
        if (now - lastDRef.current < 500) {
          lastDRef.current = 0
          deleteCell(id)
        } else {
          lastDRef.current = now
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [insertRelative, patchCell, deleteCell])

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

  // ---- galeri template: fetch .ipynb statis & muat jadi sel (sekali per template).
  const loadedTemplateRef = useRef<string | null>(null)
  useEffect(() => {
    if (!templateId || loadedTemplateRef.current === templateId) return
    loadedTemplateRef.current = templateId
    const safe = encodeURIComponent(templateId)
    fetch(`/templates/${safe}.ipynb`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((text) => loadNotebookText(text, `template ${templateId}`))
      .catch(() => setError('Template tidak ditemukan. Buka menu Template lalu pilih ulang.'))
  }, [templateId, loadNotebookText])

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
        if (res.cwd) setCwd(res.cwd)
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
        if (res.cwd) setCwd(res.cwd)
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

  // Tutup sekumpulan tab sekaligus. Dihitung dari ref, bukan di dalam updater
  // state, supaya tidak ada efek samping saat React menjalankan updater dua kali.
  const tabsRef = useRef<OpenTab[]>([])
  tabsRef.current = tabs
  const closeTabs = useCallback((paths: string[]) => {
    const buang = new Set(paths)
    const kini = tabsRef.current
    const idx = kini.findIndex((t) => buang.has(t.path))
    if (idx < 0) return
    const sisa = kini.filter((t) => !buang.has(t.path))
    setTabs(sisa)
    // Yang aktif ikut ditutup -> pindah ke tab penggantinya, atau yang terakhir.
    setActiveTab((cur) =>
      cur && buang.has(cur) ? ((sisa[idx] ?? sisa[sisa.length - 1])?.path ?? null) : cur,
    )
    setImageUrls((m) => {
      const next = { ...m }
      let ubah = false
      buang.forEach((p) => {
        if (next[p]) {
          URL.revokeObjectURL(next[p])
          delete next[p]
          ubah = true
        }
      })
      return ubah ? next : m
    })
    setTextFiles((m) => {
      const next = { ...m }
      let ubah = false
      buang.forEach((p) => {
        if (next[p]) {
          delete next[p]
          ubah = true
        }
      })
      return ubah ? next : m
    })
  }, [])

  const closeTab = useCallback((path: string) => closeTabs([path]), [closeTabs])

  // Berkas dihapus/dipindah -> tab yang menunjuk path lama (termasuk isi folder itu)
  // sudah tidak sahih, jadi ditutup daripada menampilkan isi yang menyesatkan.
  const closeTabsUnder = useCallback(
    (path: string) =>
      closeTabs(
        tabsRef.current
          .filter((t) => t.path === path || t.path.startsWith(`${path}/`))
          .map((t) => t.path),
      ),
    [closeTabs],
  )

  const refreshTree = useCallback(async () => {
    if (!sessionId) return
    try {
      const res = await api.listInteractiveFiles(sessionId)
      setTree(res.tree)
      if (res.cwd) setCwd(res.cwd)
    } catch (e) {
      setProjectError((e as Error).message)
    }
  }, [sessionId])
  // Ref stabil -> dipakai handler WS (execute_reply) untuk auto-refresh tanpa
  // mengubah dependensi callback.
  refreshTreeRef.current = refreshTree

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
        closeTabsUnder(path)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal mengganti nama.')
      }
    },
    [sessionId, closeTabsUnder],
  )

  // Pindah lewat seret & lepas: rename ke folder tujuan (backend sudah mendukung).
  const moveItem = useCallback(
    async (src: string, destDir: string) => {
      if (!sessionId) return
      const nama = src.slice(src.lastIndexOf('/') + 1)
      const tujuan = destDir ? `${destDir}/${nama}` : nama
      if (tujuan === src) return
      // Folder tak boleh dijatuhkan ke dalam dirinya sendiri (akan hilang).
      if (destDir === src || destDir.startsWith(`${src}/`)) {
        setProjectError('Folder tidak bisa dipindahkan ke dalam dirinya sendiri.')
        return
      }
      try {
        setTree((await api.renameInteractive(sessionId, src, tujuan)).tree)
        closeTabsUnder(src)
        setNotice(`"${nama}" dipindahkan ke "${destDir || 'root project'}".`)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal memindahkan.')
      }
    },
    [sessionId, closeTabsUnder],
  )

  // Unggah berkas dari komputer ke folder yang dipilih di explorer (chunked).
  const uploadInto = useCallback(
    async (destDir: string, files: File[]) => {
      if (!sessionId || !files.length) return
      setProjectBusy(true)
      setProjectError(null)
      try {
        const CHUNK = 24 * 1024 * 1024 // di bawah batas body nginx
        for (const f of files) {
          const rel =
            (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name
          const tujuan = destDir ? `${destDir}/${rel}` : rel
          if (f.size === 0) {
            await api.importInteractiveChunk(sessionId, tujuan, true, new Blob([]))
            continue
          }
          for (let off = 0; off < f.size; off += CHUNK) {
            const potongan = f.slice(off, Math.min(off + CHUNK, f.size))
            await api.importInteractiveChunk(sessionId, tujuan, off === 0, potongan)
          }
          setNotice(`Mengunggah… ${rel}`)
        }
        await refreshTree()
        setNotice(
          files.length === 1
            ? `"${files[0].name}" diunggah ke "${destDir || 'root project'}".`
            : `${files.length} berkas diunggah ke "${destDir || 'root project'}".`,
        )
      } catch (e) {
        setNotice(null)
        setProjectError((e as Error).message || 'Gagal mengunggah.')
      } finally {
        setProjectBusy(false)
      }
    },
    [sessionId, refreshTree],
  )

  const deleteItem = useCallback(
    async (path: string) => {
      if (!sessionId) return
      if (!window.confirm(`Hapus "${path}"? Tindakan ini tidak bisa dibatalkan.`)) return
      try {
        setTree((await api.deleteInteractiveItem(sessionId, path)).tree)
        closeTabsUnder(path)
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal menghapus.')
      }
    },
    [sessionId, closeTabsUnder],
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
      const bukaTab = (kind: TabKind) => {
        setTabs((ts) => (ts.some((t) => t.path === path) ? ts : [...ts, { path, name, kind }]))
        setActiveTab(path)
      }
      // Gambar -> pratinjau visual (ambil byte mentah sebagai blob, tampilkan <img>).
      if (isImagePath(name)) {
        try {
          const blob = await api.readInteractiveFileRaw(sessionId, path)
          setImageUrls((m) => {
            if (m[path]) URL.revokeObjectURL(m[path])
            return { ...m, [path]: URL.createObjectURL(blob) }
          })
          bukaTab('image')
        } catch (e) {
          setProjectError((e as Error).message || 'Gagal membuka gambar.')
        }
        return
      }
      const isNb = name.toLowerCase().endsWith('.ipynb')
      if (isNb) {
        // Sudah pernah dibuka/dijalankan di SESI ini? -> PULIHKAN sel DENGAN output
        // (tak baca ulang file) supaya pindah antar-notebook tak menghilangkan output.
        const cached = fileCellsStore.get(`${skey}:${path}`)
        if (cached && cached.length) {
          setCells(cached.map((c) => ({ ...c, running: false })))
          setActiveFilePath(path)
          setError(null)
          bukaTab('notebook')
          return
        }
      }
      try {
        const f = await api.readInteractiveFile(sessionId, path)
        if (isNb) {
          loadNotebookText(f.content, name)
          setActiveFilePath(path)
          bukaTab('notebook')
        } else {
          setTextFiles((m) => ({ ...m, [path]: f }))
          bukaTab('text')
        }
      } catch (e) {
        setProjectError((e as Error).message || 'Gagal membuka file.')
      }
    },
    [sessionId, skey, loadNotebookText],
  )

  const loadPreviewToCell = useCallback((f: InteractiveFile) => {
    setCells((cs) => [...cs, makeCell(f.content, 'code')])
    setActiveTab(activeFilePath)
    setNotice(`"${f.path}" dimuat ke sel baru.`)
  }, [activeFilePath])

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
      // Cegah menimpa tanpa sadar: bila file sudah ada, minta konfirmasi dulu.
      try {
        await api.readWorkspaceFile(path)
        if (
          !window.confirm(
            `File "${path}" sudah ada di Penyimpanan. Timpa versi lama?\n(Batal lalu ganti nama untuk menyimpan sebagai versi baru.)`,
          )
        )
          return
      } catch {
        /* belum ada -> lanjut simpan */
      }
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

  // Hitung mundur sisa umur sesi. Detik berdetak lokal; server menyegarkan angkanya
  // berkala (dan setiap kali kernel dipakai lagi, batasnya mundur otomatis).
  useEffect(() => {
    if (expiryAt == null || !connected) return
    const t = setInterval(() => setNowTick(Date.now()), 1000)
    return () => clearInterval(t)
  }, [expiryAt, connected])
  const sisaDetik =
    expiryAt != null && connected ? Math.max(0, Math.round((expiryAt - nowTick) / 1000)) : null
  // Saat sel sedang jalan, sesi TIDAK dihitung idle -> jangan menakuti user.
  const peringatanHabis = sisaDetik != null && sisaDetik <= EXPIRY_WARN_SECONDS && !kbusy

  // Bisa memicu Run (akan start kernel bila belum aktif). Hanya terhalang saat
  // kernel sedang disiapkan atau sedang menjalankan sel lain.
  const canRun = kernel !== 'starting' && kernel !== 'queued' && !kbusy
  const isProjectMode = mode === 'zip' || mode === 'github'
  // Auto-refresh tree hanya relevan saat ada panel File (mode project).
  projectModeRef.current = isProjectMode

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

  const tabAktif = tabs.find((t) => t.path === activeTab) ?? null

  const cellList = useMemo(
    () => (
      <div className="space-y-3">
        {cells.map((cell, idx) => (
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
              lintPrefix={cells
                .slice(0, idx)
                .filter((c) => c.kind === 'code')
                .map((c) => c.code)
                .join('\n\n')}
              onChange={(code) => patchCell(cell.id, (c) => ({ ...c, code }))}
              onRun={() => void runCell(cellsRef.current.find((c) => c.id === cell.id) || cell)}
              onInterrupt={interrupt}
              onEdit={() => patchCell(cell.id, (c) => ({ ...c, editing: true }))}
              onDelete={() => deleteCell(cell.id)}
              onAddBelow={() => addCell(cell.id)}
              onMoveUp={() => moveCell(cell.id, -1)}
              onMoveDown={() => moveCell(cell.id, 1)}
              onDuplicate={() => duplicateCell(cell.id)}
              canMoveUp={idx > 0}
              canMoveDown={idx < cells.length - 1}
              canDelete={cells.length > 1}
            />
          </div>
        ))}
      </div>
    ),
    [cells, canRun, patchCell, runCell, interrupt, deleteCell, addCell, moveCell, duplicateCell, activeId],
  )

  const addBar = (
    <div className="flex flex-wrap gap-2">
      {mode === 'paste' && (
        <select
          defaultValue=""
          onChange={(e) => {
            const t = JOB_TEMPLATES.find((x) => x.id === e.target.value)
            // addCell() hanya bikin sel KOSONG (param pertama = afterId, bukan kode)
            // -> tambah sel berisi kode template langsung via makeCell.
            if (t) setCells((cs) => [...cs, makeCell(t.code, 'code')])
            e.target.value = ''
          }}
          className="w-full cursor-pointer rounded-xl border border-dashed border-emerald-300 bg-transparent px-3 py-2.5 text-sm font-medium text-emerald-600 transition hover:border-emerald-400 dark:border-emerald-400/40 dark:text-emerald-300 sm:w-auto"
          title="Sisipkan sel berisi contoh siap pakai"
        >
          <option value="" disabled>
            ✨ Contoh siap pakai…
          </option>
          {JOB_TEMPLATES.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label} — {t.desc}
            </option>
          ))}
        </select>
      )}
      <button
        onClick={() => addCell()}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 py-2.5 text-sm font-medium text-slate-500 transition hover:border-brand-400 hover:bg-brand-50/40 hover:text-brand-600 dark:border-brand-400/40 dark:text-brand-300 dark:hover:bg-brand-500/10"
      >
        <IconCode className="h-4 w-4" /> Sel kode
      </button>
      <button
        onClick={() => addCell(undefined, 'markdown')}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 py-2.5 text-sm font-medium text-slate-500 transition hover:border-violet-400 hover:bg-violet-50/40 hover:text-violet-600 dark:border-violet-400/40 dark:text-violet-300 dark:hover:bg-violet-500/10"
      >
        <IconNotebook className="h-4 w-4" /> Sel teks (Markdown)
      </button>
      <button
        onClick={clearAllCells}
        title="Hapus semua sel (masih bisa dikembalikan)"
        className="flex items-center justify-center gap-2 rounded-xl border border-dashed border-rose-300 px-4 py-2.5 text-sm font-medium text-rose-500 transition hover:border-rose-400 hover:bg-rose-50/40 hover:text-rose-600 dark:border-rose-400/40 dark:text-rose-300 dark:hover:bg-rose-500/10"
      >
        <IconTrash className="h-4 w-4" /> Bersihkan
      </button>
      {deletedStack.length > 0 && (
        <button
          onClick={restoreDeletedCell}
          title="Kembalikan sel terakhir yang dihapus (kode & output utuh)"
          className="flex items-center justify-center gap-2 rounded-xl border border-dashed border-amber-300 px-4 py-2.5 text-sm font-medium text-amber-600 transition hover:border-amber-400 hover:bg-amber-50/40 hover:text-amber-700 dark:border-amber-400/40 dark:text-amber-300 dark:hover:bg-amber-500/10"
        >
          ↩ Kembalikan sel ({deletedStack.length})
        </button>
      )}
      <p className="w-full text-center text-[11px] text-slate-400">
        Pintasan (saat tidak mengetik): <b>A</b> sel di atas · <b>B</b> di bawah ·{' '}
        <b>D&nbsp;D</b> hapus · <b>M</b> markdown ↔ kode
      </p>
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
        {sisaDetik != null && (
          <span
            className={cn(
              'inline-flex items-center gap-1 text-xs tabular-nums',
              peringatanHabis ? 'font-semibold text-amber-300' : 'text-slate-400',
            )}
            title={
              'Sesi berhenti otomatis bila dibiarkan menganggur atau sudah mencapai umur maksimum. '
              + 'Menjalankan sel apa pun akan memperpanjangnya.'
            }
          >
            <IconClock className="h-3.5 w-3.5" /> sisa {formatSisaWaktu(sisaDetik)}
          </span>
        )}
        {pyVersions.length > 1 && (
          <select
            value={pyVer || pyDefault}
            onChange={(e) => setPyVer(e.target.value === pyDefault ? '' : e.target.value)}
            disabled={sessionId != null}
            title={
              sessionId != null
                ? 'Versi Python sesi aktif. Matikan kernel dulu untuk ganti versi.'
                : 'Pilih versi Python kernel (berlaku saat kernel dinyalakan)'
            }
            className="rounded-lg border-0 bg-white/10 px-2 py-1 text-xs font-medium text-slate-200 focus:outline-none focus:ring-1 focus:ring-brand-400 disabled:opacity-50"
          >
            {pyVersions.map((v) => (
              <option key={v} value={v} className="bg-slate-900 text-slate-100">
                Python {v}
              </option>
            ))}
          </select>
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
          <button
            onClick={toggleTerminal}
            title="Terminal di dalam sesi — bash + git, terisolasi di folder kerjamu (Ctrl+`)"
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition',
              termOpen
                ? 'bg-brand-600 text-white hover:bg-brand-500'
                : 'bg-white/10 text-slate-100 hover:bg-white/20',
            )}
          >
            <IconTerminal className="h-3.5 w-3.5" /> Terminal
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

      {peringatanHabis && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-800 ring-1 ring-inset ring-amber-600/20">
          <IconClock className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <p>
            <b>Sesi akan berhenti otomatis dalam {formatSisaWaktu(sisaDetik ?? 0)}</b> supaya GPU
            bisa dipakai mahasiswa lain. Jalankan sel mana pun untuk memperpanjang. Kodemu sudah
            tersimpan otomatis ke <b>Penyimpanan</b>, jadi tidak akan hilang — hanya variabel di
            memori yang direset.
          </p>
        </div>
      )}

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
                <b>Satu file</b> yang di-share &ldquo;Siapa saja yang memiliki link&rdquo; →{' '}
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">import gdown</code>{' '}
                lalu{' '}
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">
                  gdown.download(URL, "data.csv", fuzzy=True)
                </code>
                .
              </li>
              <li>
                <b>Satu folder</b> →{' '}
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">
                  gdown.download_folder(URL, output="data")
                </code>
                . Ingat: <b>foldernya sendiri</b> harus di-share — men-share file di dalamnya saja
                tidak cukup (nanti error 404).
              </li>
              <li>
                <b>Data pribadi</b> (tak ingin dipublikkan) → klik tombol <b>Unggah</b> (maks 256 MB
                per file) atau menu <b>Penyimpanan</b>; file masuk ke{' '}
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">/persist</code>{' '}
                dan tetap ada di sesi berikutnya — tanpa mengubah izin Drive sama sekali.
              </li>
              <li>
                <b>Dataset publik terkenal</b> (HuggingFace/Kaggle) → unduh langsung dari sumbernya
                (
                <code className="rounded bg-sky-100 px-1 py-0.5 font-mono text-xs">load_dataset(...)</code>
                ), lebih cepat dan tanpa batas kuota Drive.
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
              cwd={cwd}
              activePath={activeTab}
              onOpen={openFile}
              onRefresh={refreshTree}
              onNewFile={createFile}
              onNewFolder={createFolder}
              onRename={renameItem}
              onDelete={deleteItem}
              onMove={moveItem}
              onUpload={uploadInto}
              onDownload={() => void downloadProject()}
              onPush={() => setPushOpen(true)}
              onChangeProject={() => {
                setTree(null)
                setProjectError(null)
                setTabs([])
                setActiveTab(null)
              }}
            />
            <div className="space-y-3">
              <TabBar
                tabs={tabs}
                active={activeTab}
                onSelect={(t) => {
                  // Notebook: buka ulang supaya sel + output sesi ikut dipulihkan.
                  if (t.kind === 'notebook') void openFile(t.path, t.name)
                  else setActiveTab(t.path)
                }}
                onClose={closeTab}
              />
              {tabAktif?.kind === 'text' && textFiles[tabAktif.path] ? (
                <FilePane
                  key={tabAktif.path}
                  file={textFiles[tabAktif.path]}
                  onLoadToCell={() => loadPreviewToCell(textFiles[tabAktif.path])}
                  onSave={(content) => void saveFile(tabAktif.path, content)}
                />
              ) : tabAktif?.kind === 'image' && imageUrls[tabAktif.path] ? (
                <ImagePane name={tabAktif.name} url={imageUrls[tabAktif.path]} />
              ) : (
                <>
                  {cellList}
                  {addBar}
                </>
              )}
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

      {pushOpen && (
        <PushPanel busy={pushing} onClose={() => setPushOpen(false)} onPush={doPush} />
      )}

      {/* Terminal web (Ctrl+`): bash di DALAM container sesi — isolasi container. */}
      {termOpen &&
        (sessionId && connected ? (
          <Suspense
            fallback={
              <div className="rounded-xl bg-slate-900 px-4 py-6 text-center text-xs text-slate-400">
                Memuat terminal…
              </div>
            }
          >
            <TerminalPanel sessionId={sessionId} onClose={() => setTermOpen(false)} />
          </Suspense>
        ) : (
          <div className="rounded-xl bg-slate-900 px-4 py-6 text-center text-xs text-slate-400">
            {queueInfo
              ? `Menunggu giliran GPU (posisi ${queueInfo.position})…`
              : 'Menyalakan kernel untuk terminal…'}
          </div>
        ))}
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
              pythonVersion={pyVer || pyDefault}
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
  onInterrupt,
  onEdit,
  onDelete,
  onAddBelow,
  onMoveUp,
  onMoveDown,
  onDuplicate,
  canMoveUp,
  canMoveDown,
  canDelete,
  editorMinHeight = 72,
  editorMaxHeight,
  lintPrefix = '',
}: {
  cell: Cell
  disabled: boolean
  onChange: (code: string) => void
  onRun: () => void
  onInterrupt?: () => void
  onEdit: () => void
  onDelete: () => void
  onAddBelow: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  onDuplicate: () => void
  canMoveUp: boolean
  canMoveDown: boolean
  canDelete: boolean
  editorMinHeight?: number
  editorMaxHeight?: number
  lintPrefix?: string
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
      lintPrefix={isMd ? '' : lintPrefix}
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
          {cell.running ? (
            /* Sel BERJALAN -> tombol STOP (kirim interrupt = Ctrl+C / KeyboardInterrupt) */
            <button
              onClick={onInterrupt}
              title="Hentikan eksekusi sel ini (Ctrl+C / KeyboardInterrupt)"
              className="group/stop relative grid h-8 w-8 place-items-center rounded-lg bg-rose-600 text-white transition hover:bg-rose-500"
            >
              <span className="absolute inset-0 animate-ping rounded-lg bg-rose-500/40 group-hover/stop:hidden" />
              <span className="absolute h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white/80 group-hover/stop:hidden" />
              <IconStop className="relative hidden h-3.5 w-3.5 group-hover/stop:block" />
            </button>
          ) : (
            <button
              onClick={onRun}
              disabled={disabled}
              title={isMd ? 'Render (Shift+Enter)' : 'Run (Shift+Enter)'}
              className={cn(
                'grid h-8 w-8 place-items-center rounded-lg text-white transition disabled:opacity-40',
                isMd ? 'bg-violet-500 hover:bg-violet-400' : 'bg-brand-600 hover:bg-brand-500',
              )}
            >
              <IconPlay className="h-4 w-4" />
            </button>
          )}
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
          <button
            onClick={onMoveUp}
            disabled={!canMoveUp}
            title="Pindahkan sel ke atas"
            className="grid h-6 w-6 place-items-center rounded text-slate-400 hover:bg-slate-100 hover:text-brand-600 disabled:opacity-25 disabled:hover:bg-transparent"
          >
            <IconChevron className="h-3.5 w-3.5 rotate-180" />
          </button>
          <button
            onClick={onMoveDown}
            disabled={!canMoveDown}
            title="Pindahkan sel ke bawah"
            className="grid h-6 w-6 place-items-center rounded text-slate-400 hover:bg-slate-100 hover:text-brand-600 disabled:opacity-25 disabled:hover:bg-transparent"
          >
            <IconChevron className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onDuplicate}
            title="Duplikat sel"
            className="grid h-6 w-6 place-items-center rounded text-slate-400 hover:bg-slate-100 hover:text-violet-600"
          >
            <IconCopy className="h-3.5 w-3.5" />
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
// --------------------------------------------------------------- explorer
// Menyalin ke papan klip. navigator.clipboard butuh konteks aman (https); di
// http/dev dipakai cadangan textarea supaya fitur "salin path" tetap jalan.
async function salinTeks(teks: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(teks)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = teks
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

type MenuItem = { label: string; onClick: () => void; danger?: boolean } | 'pisah'

function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number
  y: number
  items: MenuItem[]
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x, y })

  // Jangan sampai menu terpotong tepi layar (sering terjadi di baris paling bawah).
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setPos({
      x: Math.min(x, window.innerWidth - r.width - 8),
      y: Math.min(y, window.innerHeight - r.height - 8),
    })
  }, [x, y])

  useEffect(() => {
    const tutup = (e: Event) => {
      if (e.type === 'keydown' && (e as KeyboardEvent).key !== 'Escape') return
      onClose()
    }
    window.addEventListener('pointerdown', tutup)
    window.addEventListener('keydown', tutup)
    window.addEventListener('resize', tutup)
    return () => {
      window.removeEventListener('pointerdown', tutup)
      window.removeEventListener('keydown', tutup)
      window.removeEventListener('resize', tutup)
    }
  }, [onClose])

  return createPortal(
    <div
      ref={ref}
      style={{ left: pos.x, top: pos.y }}
      onPointerDown={(e) => e.stopPropagation()}
      className="fixed z-[60] min-w-[13rem] overflow-hidden rounded-lg bg-white py-1 shadow-xl ring-1 ring-slate-200"
    >
      {items.map((it, i) =>
        it === 'pisah' ? (
          <div key={i} className="my-1 border-t border-slate-100" />
        ) : (
          <button
            key={i}
            onClick={() => {
              onClose()
              it.onClick()
            }}
            className={cn(
              'block w-full px-3 py-1.5 text-left text-xs transition',
              it.danger
                ? 'text-rose-600 hover:bg-rose-50'
                : 'text-slate-700 hover:bg-brand-50 hover:text-brand-700',
            )}
          >
            {it.label}
          </button>
        ),
      )}
    </div>,
    document.body,
  )
}

function FileExplorer({
  tree,
  busy,
  mode,
  cwd,
  activePath,
  onOpen,
  onRefresh,
  onNewFile,
  onNewFolder,
  onRename,
  onDelete,
  onMove,
  onUpload,
  onDownload,
  onPush,
  onChangeProject,
}: {
  tree: FileNode
  busy: boolean
  mode: NotebookMode
  cwd: string
  activePath: string | null
  onOpen: (path: string, name: string) => void
  onRefresh: () => void
  onNewFile: (dir: string) => void
  onNewFolder: (dir: string) => void
  onRename: (path: string, name: string) => void
  onDelete: (path: string) => void
  onMove: (src: string, destDir: string) => void
  onUpload: (destDir: string, files: File[]) => void
  onDownload: () => void
  onPush: () => void
  onChangeProject: () => void
}) {
  const [menu, setMenu] = useState<{ x: number; y: number; node: FileNode | null } | null>(null)
  const [pesan, setPesan] = useState<string | null>(null)
  const [dropRoot, setDropRoot] = useState(false)
  // Satu <input type=file> dipakai ulang; `dirTujuan` mengingat folder sasarannya.
  const inputRef = useRef<HTMLInputElement>(null)
  const dirTujuan = useRef('')

  const pilihUnggahan = (dir: string, folder: boolean) => {
    const el = inputRef.current
    if (!el) return
    dirTujuan.current = dir
    el.value = ''
    // webkitdirectory tak ada di tipe React -> diset lewat atribut DOM.
    if (folder) el.setAttribute('webkitdirectory', '')
    else el.removeAttribute('webkitdirectory')
    el.click()
  }

  const salin = async (teks: string, label: string) => {
    setPesan((await salinTeks(teks)) ? `${label} disalin` : 'Gagal menyalin')
    window.setTimeout(() => setPesan(null), 1800)
  }

  // Menu untuk berkas, folder, atau area kosong (node = null -> root project).
  const itemMenu = (node: FileNode | null): MenuItem[] => {
    const dir = node ? (node.type === 'dir' ? node.path : indukDari(node.path)) : ''
    const umum: MenuItem[] = [
      { label: 'Berkas baru…', onClick: () => onNewFile(dir) },
      { label: 'Folder baru…', onClick: () => onNewFolder(dir) },
      { label: 'Unggah berkas…', onClick: () => pilihUnggahan(dir, false) },
      { label: 'Unggah folder…', onClick: () => pilihUnggahan(dir, true) },
    ]
    if (!node) return umum
    const absolut = cwd ? `${cwd}/${node.path}` : node.path
    return [
      ...(node.type === 'file'
        ? [{ label: 'Buka', onClick: () => onOpen(node.path, node.name) } as MenuItem, 'pisah' as const]
        : []),
      ...umum,
      'pisah',
      { label: 'Salin path', onClick: () => void salin(absolut, 'Path') },
      { label: 'Salin path relatif', onClick: () => void salin(node.path, 'Path relatif') },
      'pisah',
      { label: 'Ganti nama…', onClick: () => onRename(node.path, node.name) },
      { label: 'Hapus', danger: true, onClick: () => onDelete(node.path) },
    ]
  }

  // Lepasan dari luar (Finder/Explorer) diunggah; lepasan dari dalam = pindah.
  const terimaLepasan = (e: React.DragEvent, dir: string) => {
    const berkas = Array.from(e.dataTransfer.files ?? [])
    if (berkas.length) {
      onUpload(dir, berkas)
      return
    }
    const src = e.dataTransfer.getData('text/ch-path')
    if (src) onMove(src, dir)
  }

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
          title="Berkas baru di root project"
          className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
        >
          + File
        </button>
        <button
          onClick={() => onNewFolder('')}
          title="Folder baru di root project"
          className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
        >
          + Folder
        </button>
        <span className="flex-1" />
        <button
          onClick={() => pilihUnggahan('', false)}
          title="Unggah berkas dari komputer"
          className="rounded p-1 text-slate-400 hover:bg-brand-50 hover:text-brand-700"
        >
          <IconUpload className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => pilihUnggahan('', true)}
          title="Unggah folder dari komputer"
          className="rounded p-1 text-slate-400 hover:bg-brand-50 hover:text-brand-700"
        >
          <IconFolder className="h-3.5 w-3.5" />
        </button>
      </div>
      <div
        onContextMenu={(e) => {
          e.preventDefault()
          setMenu({ x: e.clientX, y: e.clientY, node: null })
        }}
        onDragOver={(e) => {
          e.preventDefault()
          // Hanya area kosong yang disorot; kalau kursor sedang di atas sebuah
          // baris, biar baris itu saja yang menandai dirinya sebagai tujuan.
          setDropRoot(!(e.target as HTMLElement).closest('[data-baris]'))
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropRoot(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          setDropRoot(false)
          terimaLepasan(e, '')
        }}
        className={cn(
          'max-h-[28rem] overflow-auto p-1.5 transition',
          dropRoot && 'bg-brand-50 ring-1 ring-inset ring-brand-400',
        )}
      >
        {tree.children && tree.children.length > 0 ? (
          tree.children.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              activePath={activePath}
              onOpen={onOpen}
              onMove={onMove}
              onUpload={onUpload}
              onMenu={(x, y, n) => setMenu({ x, y, node: n })}
            />
          ))
        ) : (
          <p className="px-2 py-3 text-xs text-slate-400">
            Project kosong — klik kanan di sini untuk membuat atau mengunggah berkas.
          </p>
        )}
      </div>
      <p className="border-t border-slate-100 px-3 py-1.5 text-[10px] text-slate-400">
        {pesan ?? 'Klik kanan untuk menu · seret untuk memindahkan'}
      </p>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          const berkas = Array.from(e.target.files ?? [])
          if (berkas.length) onUpload(dirTujuan.current, berkas)
          e.target.value = ''
        }}
      />
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={itemMenu(menu.node)}
          onClose={() => setMenu(null)}
        />
      )}
    </aside>
  )
}

function indukDari(path: string): string {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
}

function TreeNode({
  node,
  depth,
  activePath,
  onOpen,
  onMove,
  onUpload,
  onMenu,
}: {
  node: FileNode
  depth: number
  activePath: string | null
  onOpen: (path: string, name: string) => void
  onMove: (src: string, destDir: string) => void
  onUpload: (destDir: string, files: File[]) => void
  onMenu: (x: number, y: number, node: FileNode) => void
}) {
  const [open, setOpen] = useState(depth < 1)
  const [dropSini, setDropSini] = useState(false)
  const pad = { paddingLeft: `${depth * 12 + 8}px` }

  const mulaiSeret = (e: React.DragEvent) => {
    e.dataTransfer.setData('text/ch-path', node.path)
    e.dataTransfer.effectAllowed = 'move'
  }
  const bukaMenu = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    onMenu(e.clientX, e.clientY, node)
  }

  if (node.type === 'file') {
    const aktif = activePath === node.path
    const induk = indukDari(node.path)
    return (
      <div
        draggable
        data-baris
        onDragStart={mulaiSeret}
        onContextMenu={bukaMenu}
        onDragOver={(e) => {
          // Dibiarkan menggelembung supaya panel induk tahu kursor sedang di baris
          // ini. Berkas bukan wadah -> tujuannya folder induk berkas ini.
          e.preventDefault()
          setDropSini(true)
        }}
        onDragLeave={() => setDropSini(false)}
        onDrop={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setDropSini(false)
          const berkas = Array.from(e.dataTransfer.files ?? [])
          if (berkas.length) {
            onUpload(induk, berkas)
            return
          }
          const src = e.dataTransfer.getData('text/ch-path')
          if (src) onMove(src, induk)
        }}
        style={pad}
        className={cn(
          'group flex items-center rounded-md',
          dropSini
            ? 'bg-brand-100'
            : aktif
              ? 'bg-brand-50'
              : 'hover:bg-brand-50',
        )}
      >
        <button
          onClick={() => onOpen(node.path, node.name)}
          title={node.path}
          className={cn(
            'flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-xs',
            aktif ? 'font-medium text-brand-700' : 'text-slate-600 group-hover:text-brand-700',
          )}
        >
          <IconFile className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate">{node.name}</span>
        </button>
        <button
          onClick={bukaMenu}
          title="Menu"
          className="shrink-0 px-1 text-slate-400 opacity-0 hover:text-brand-600 group-hover:opacity-100"
        >
          ⋯
        </button>
      </div>
    )
  }

  return (
    <div>
      <div
        draggable
        data-baris
        onDragStart={mulaiSeret}
        onContextMenu={bukaMenu}
        onDragOver={(e) => {
          e.preventDefault()
          setDropSini(true)
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropSini(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setDropSini(false)
          setOpen(true)
          const berkas = Array.from(e.dataTransfer.files ?? [])
          if (berkas.length) {
            onUpload(node.path, berkas)
            return
          }
          const src = e.dataTransfer.getData('text/ch-path')
          if (src) onMove(src, node.path)
        }}
        style={pad}
        className={cn(
          'group flex items-center rounded-md',
          dropSini ? 'bg-brand-100 ring-1 ring-inset ring-brand-400' : 'hover:bg-slate-100',
        )}
      >
        <button
          onClick={() => setOpen((o) => !o)}
          title={node.path}
          className="flex min-w-0 flex-1 items-center gap-1 py-1 text-left text-xs font-medium text-slate-700"
        >
          <IconChevron className={cn('h-3 w-3 shrink-0 text-slate-400 transition', open && 'rotate-90')} />
          <IconFolder className="h-3.5 w-3.5 shrink-0 text-amber-500" />
          <span className="truncate">{node.name}</span>
        </button>
        <button
          onClick={bukaMenu}
          title="Menu"
          className="shrink-0 px-1 text-slate-400 opacity-0 hover:text-brand-600 group-hover:opacity-100"
        >
          ⋯
        </button>
      </div>
      {open &&
        node.children?.map((child) => (
          <TreeNode
            key={child.path}
            node={child}
            depth={depth + 1}
            activePath={activePath}
            onOpen={onOpen}
            onMove={onMove}
            onUpload={onUpload}
            onMenu={onMenu}
          />
        ))}
    </div>
  )
}

// ------------------------------------------------------------------ tab bar
// Deret tab ala VS Code: klik untuk pindah, klik tengah atau silang untuk tutup.
function TabBar({
  tabs,
  active,
  onSelect,
  onClose,
}: {
  tabs: OpenTab[]
  active: string | null
  onSelect: (tab: OpenTab) => void
  onClose: (path: string) => void
}) {
  if (tabs.length === 0) return null
  return (
    <div className="flex items-stretch gap-0.5 overflow-x-auto rounded-xl bg-slate-100 p-1">
      {tabs.map((t) => {
        const aktif = t.path === active
        return (
          <div
            key={t.path}
            title={t.path}
            className={cn(
              'group flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs transition',
              aktif
                ? 'bg-white font-medium text-slate-800 shadow-sm'
                : 'text-slate-500 hover:bg-white hover:text-slate-700',
            )}
          >
            <button
              onClick={() => onSelect(t)}
              onAuxClick={(e) => {
                if (e.button === 1) onClose(t.path) // klik tengah = tutup, seperti VS Code
              }}
              className="flex min-w-0 items-center gap-1.5"
            >
              {t.kind === 'image' ? (
                <IconImage className="h-3.5 w-3.5 shrink-0 text-violet-400" />
              ) : (
                <IconFile
                  className={cn(
                    'h-3.5 w-3.5 shrink-0',
                    t.kind === 'notebook' ? 'text-amber-500' : 'text-slate-400',
                  )}
                />
              )}
              <span className="max-w-[10rem] truncate">{t.name}</span>
            </button>
            <button
              onClick={() => onClose(t.path)}
              title="Tutup tab"
              className="rounded p-0.5 text-slate-400 opacity-0 transition hover:bg-slate-200 hover:text-slate-700 group-hover:opacity-100"
            >
              <IconX className="h-3 w-3" />
            </button>
          </div>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------- panel gambar
function ImagePane({ name, url }: { name: string; url: string }) {
  return (
    <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
        <IconImage className="h-4 w-4 text-slate-400" />
        <span className="flex-1 truncate font-mono text-xs text-slate-600">{name}</span>
        <a
          href={url}
          download={name}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 transition hover:bg-slate-100"
        >
          <IconDownload className="h-3.5 w-3.5" /> Unduh
        </a>
      </div>
      <div className="flex max-h-[70vh] justify-center overflow-auto bg-slate-50 p-4">
        <img src={url} alt={name} className="max-w-full object-contain" />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- panel file
function FilePane({
  file,
  onLoadToCell,
  onSave,
}: {
  file: InteractiveFile
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
    <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2.5">
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
        {file.truncated && (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">
            dipotong (tak bisa edit)
          </span>
        )}
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
      </div>
      <div className="min-h-0">
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
            theme={ONE_DARK_PRO_DARKER}
            value={content}
            beforeMount={defineOneDarkProDarker}
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
