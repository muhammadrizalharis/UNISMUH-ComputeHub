// Halaman PENYIMPANAN — file browser workspace persisten per-user (/persist), ala Colab Drive.
// File yang dibuat dari notebook/job (mis. dataset, checkpoint model) + paket `pip --user`
// tetap tersimpan di sini antar-sesi. Bisa lihat isi, unduh, dan hapus file.

import { useEffect, useRef, useState, type CSSProperties, type DragEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import CodeEditor from '../components/CodeEditor'
import NotebookPreview from '../components/NotebookPreview'
import Spinner from '../components/Spinner'
import WorkspaceDirectory from '../components/WorkspaceDirectory'
import {
  IconChevron,
  IconDownload,
  IconFile,
  IconFolder,
  IconPencil,
  IconRefresh,
  IconTrash,
  IconUpload,
} from '../components/icons'
import { ApiError, api } from '../lib/api'
import { cn } from '../lib/format'
import type { FileNode, WorkspaceTrashItem } from '../lib/types'
import { readWorkspaceDrop, workspaceFileSelection, type WorkspaceUploadItems } from '../lib/workspaceDrop'

const TREE_WIDTH_KEY = 'ch_storage_tree_width'
const TREE_MIN_WIDTH = 220
const TREE_DEFAULT_WIDTH = 300

function savedTreeWidth(): number {
  try {
    const value = Number(localStorage.getItem(TREE_WIDTH_KEY))
    return Number.isFinite(value) && value >= TREE_MIN_WIDTH ? Math.min(value, 800) : TREE_DEFAULT_WIDTH
  } catch {
    return TREE_DEFAULT_WIDTH
  }
}

function droppedDirectory(target: EventTarget | null): string {
  return target instanceof Element
    ? target.closest<HTMLElement>('[data-storage-drop-dir]')?.dataset.storageDropDir ?? ''
    : ''
}

function fmtBytes(n: number): string {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

/** "3 menit lalu" / "2 hari lalu" — kapan item dibuang ke tempat sampah. */
function fmtWaktuHapus(epochDetik: number): string {
  const lalu = Math.max(0, Date.now() / 1000 - epochDetik)
  if (lalu < 60) return 'baru saja'
  if (lalu < 3600) return `${Math.floor(lalu / 60)} menit lalu`
  if (lalu < 86400) return `${Math.floor(lalu / 3600)} jam lalu`
  return `${Math.floor(lalu / 86400)} hari lalu`
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function downloadFileBlob(path: string) {
  const blob = await api.downloadWorkspaceFile(path)
  saveBlob(blob, path.split('/').pop() || 'file')
}

async function downloadFolderZip(path: string, name: string) {
  const blob = await api.downloadWorkspaceFolder(path)
  saveBlob(blob, `${name || 'workspace'}.zip`)
}

function TreeRow({
  node,
  depth,
  expanded,
  toggle,
  selected,
  onSelect,
  onDownload,
  onDownloadFolder,
  onRename,
  onDelete,
  dropDir,
  uploading,
}: {
  node: FileNode
  depth: number
  expanded: Set<string>
  toggle: (p: string) => void
  selected: string | null
  onSelect: (p: string) => void
  onDownload: (p: string) => void
  onDownloadFolder: (n: FileNode) => void
  onRename: (n: FileNode) => void
  onDelete: (n: FileNode) => void
  dropDir: string | null
  uploading: boolean
}) {
  const isDir = node.type === 'dir'
  const open = expanded.has(node.path)
  const isSel = selected === node.path && !isDir
  return (
    <>
      <div
        data-storage-drop-dir={isDir ? node.path : node.path.includes('/') ? node.path.slice(0, node.path.lastIndexOf('/')) : ''}
        className={cn(
          'group flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm transition',
          isSel ? 'bg-brand-500/15 text-brand-700' : 'hover:bg-slate-500/10',
          isDir && dropDir === node.path && 'bg-brand-500/15 ring-1 ring-inset ring-brand-400',
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <button
          type="button"
          onClick={() => (isDir ? toggle(node.path) : onSelect(node.path))}
          title={node.path}
          aria-expanded={isDir ? open : undefined}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        >
          {isDir ? (
            <IconChevron
              className={cn('h-3.5 w-3.5 shrink-0 transition', open && 'rotate-90')}
            />
          ) : (
            <span className="w-3.5 shrink-0" />
          )}
          {isDir ? (
            <IconFolder className="h-4 w-4 shrink-0 text-amber-500" />
          ) : (
            <IconFile className="h-4 w-4 shrink-0 text-slate-400" />
          )}
          <span className="truncate">{node.name}</span>
          {!isDir && node.size != null && (
            <span className="ml-auto shrink-0 pl-2 text-[11px] text-slate-400">
              {fmtBytes(node.size)}
            </span>
          )}
        </button>
        <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
          <button
            type="button"
            title={isDir ? 'Unduh folder (.zip)' : 'Unduh'}
            onClick={() => (isDir ? onDownloadFolder(node) : onDownload(node.path))}
            className="rounded p-1 text-slate-500 hover:bg-slate-500/15 hover:text-brand-600"
          >
            <IconDownload className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Ubah nama"
            onClick={() => onRename(node)}
            disabled={uploading}
            className="rounded p-1 text-slate-500 hover:bg-slate-500/15 hover:text-brand-600"
          >
            <IconPencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title={isDir ? 'Hapus folder beserta isinya' : 'Hapus'}
            onClick={() => onDelete(node)}
            disabled={uploading}
            className="rounded p-1 text-slate-500 hover:bg-rose-500/15 hover:text-rose-600"
          >
            <IconTrash className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
      {isDir && open && (
        <WorkspaceDirectory path={node.path}>
          {(child) => (
            <TreeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
              selected={selected}
              onSelect={onSelect}
              onDownload={onDownload}
              onDownloadFolder={onDownloadFolder}
              onRename={onRename}
              onDelete={onDelete}
              dropDir={dropDir}
              uploading={uploading}
            />
          )}
        </WorkspaceDirectory>
      )}
    </>
  )
}

export default function Storage() {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [dropDir, setDropDir] = useState<string | null>(null)
  const panelsRef = useRef<HTMLDivElement>(null)
  const resizeRef = useRef<{ startX: number; width: number } | null>(null)
  const [panelWidth, setPanelWidth] = useState(savedTreeWidth)
  const [availableWidth, setAvailableWidth] = useState(1024)
  const [resizing, setResizing] = useState(false)
  const maxTreeWidth = Math.max(TREE_MIN_WIDTH, Math.min(800, availableWidth - 340 - 12))
  const treeWidth = Math.min(maxTreeWidth, Math.max(TREE_MIN_WIDTH, panelWidth))
  const setTreeWidth = (value: number) =>
    setPanelWidth(Math.round(Math.min(maxTreeWidth, Math.max(TREE_MIN_WIDTH, value))))

  useEffect(() => {
    const panels = panelsRef.current
    if (!panels) return
    const measure = () => setAvailableWidth(panels.getBoundingClientRect().width)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(panels)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(TREE_WIDTH_KEY, String(panelWidth))
    } catch {
      return
    }
  }, [panelWidth])

  useEffect(() => {
    const preventFileNavigation = (event: globalThis.DragEvent) => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault()
    }
    window.addEventListener('dragover', preventFileNavigation)
    window.addEventListener('drop', preventFileNavigation)
    return () => {
      window.removeEventListener('dragover', preventFileNavigation)
      window.removeEventListener('drop', preventFileNavigation)
    }
  }, [])
  // Notebook (.ipynb) tampil TER-RENDER; toggle 'Kode mentah' utk lihat JSON.
  const [rawView, setRawView] = useState(false)
  // Kembali ke tampilan notebook saat pindah file.
  useEffect(() => setRawView(false), [selected])

  const wsQ = useQuery({
    queryKey: ['workspace'],
    queryFn: () => api.getWorkspace(),
    refetchInterval: 30000,
  })

  const fileQ = useQuery({
    queryKey: ['wsfile', selected],
    queryFn: () => api.readWorkspaceFile(selected as string),
    enabled: !!selected,
    retry: false,
  })

  const delMut = useMutation({
    mutationFn: (path: string) => api.deleteWorkspaceFile(path),
    onSuccess: (_d, path) => {
      if (selected === path) setSelected(null)
      segarkanSemua()
    },
    onError: (e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal menghapus file.'),
  })

  const renameMut = useMutation({
    mutationFn: (v: { path: string; name: string }) =>
      api.renameWorkspaceEntry(v.path, v.name),
    onSuccess: (r, v) => {
      setBanner(null)
      if (selected === v.path) setSelected(r.path)
      qc.invalidateQueries({ queryKey: ['workspace'] })
    },
    onError: (e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal mengganti nama.'),
  })

  // ----- Tempat sampah: menghapus bisa dibatalkan selama belum dibersihkan -----
  const [trashOpen, setTrashOpen] = useState(false)
  const trashQ = useQuery({
    queryKey: ['workspace-trash'],
    queryFn: () => api.getWorkspaceTrash(),
  })
  const segarkanSemua = () => {
    qc.invalidateQueries({ queryKey: ['workspace'] })
    qc.invalidateQueries({ queryKey: ['workspace-trash'] })
  }
  const restoreMut = useMutation({
    mutationFn: (token: string) => api.restoreWorkspaceTrash(token),
    onSuccess: (r) => {
      setBanner(null)
      segarkanSemua()
      if (r.name !== r.path.split('/').pop())
        setBanner(`Dipulihkan sebagai "${r.path}" karena sudah ada file bernama sama.`)
    },
    onError: (e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal memulihkan.'),
  })
  const purgeMut = useMutation({
    mutationFn: (token?: string) => api.deleteWorkspaceTrash(token),
    onSuccess: () => {
      setBanner(null)
      segarkanSemua()
    },
    onError: (e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal menghapus permanen.'),
  })

  const fileRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const uploadBusy = useRef(false)
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const [uploadStatus, setUploadStatus] = useState('')
  const uploading = uploadPct != null

  useEffect(() => {
    if (!uploading) return
    const confirmLeave = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', confirmLeave)
    return () => window.removeEventListener('beforeunload', confirmLeave)
  }, [uploading])

  const uploadItems = async (selection: WorkspaceUploadItems | Promise<WorkspaceUploadItems>, destination = '') => {
    if (uploadBusy.current) return
    uploadBusy.current = true
    const CHUNK = 24 * 1024 * 1024
    let sent = 0
    let reset = true
    setUploadPct(0)
    setUploadStatus('Membaca berkas...')
    setBanner(null)
    try {
      const items = await selection
      if (items.files.length === 0 && items.directories.length === 0)
        throw new Error('Tidak ada file atau folder yang dapat diunggah.')
      const oversized = items.files.find((item) => item.file.size > 256 * 1024 * 1024)
      if (oversized) throw new Error(`"${oversized.path}" melebihi batas 256 MB per file.`)
      const total = items.files.reduce((sum, item) => sum + item.file.size, 0) || 1
      const targetPath = (path: string) => destination ? `${destination}/${path}` : path
      for (const directory of items.directories) {
        setUploadStatus(targetPath(directory))
        await api.mkdirWorkspace(targetPath(directory))
      }
      for (const item of items.files) {
        const rel = targetPath(item.path)
        setUploadStatus(rel)
        let off = 0
        let first = true
        do {
          const slice = item.file.slice(off, off + CHUNK)
          await api.uploadWorkspaceFolderChunk(rel, first, reset, slice)
          reset = false
          first = false
          off += CHUNK
          sent += slice.size
          setUploadPct(Math.min(100, Math.round((sent / total) * 100)))
        } while (off < item.file.size)
      }
      setExpanded((previous) => {
        const next = new Set(previous)
        for (const item of [...items.directories, ...items.files.map((entry) => entry.path)]) {
          const fullPath = targetPath(item)
          const slash = fullPath.indexOf('/')
          if (slash >= 0) next.add(fullPath.slice(0, slash))
        }
        if (destination) next.add(destination)
        return next
      })
      if (items.files.length === 1 && items.directories.length === 0)
        setSelected(targetPath(items.files[0].path))
    } catch (error) {
      setBanner(error instanceof Error ? error.message : 'Gagal mengunggah berkas.')
    } finally {
      void qc.invalidateQueries({ queryKey: ['workspace'] })
      void qc.invalidateQueries({ queryKey: ['wsfile'] })
      uploadBusy.current = false
      setUploadPct(null)
      setUploadStatus('')
    }
  }

  const dragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    event.dataTransfer.dropEffect = uploadBusy.current ? 'none' : 'copy'
    setDropDir(uploadBusy.current ? null : droppedDirectory(event.target))
  }

  const dropFiles = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    setDropDir(null)
    if (uploadBusy.current) return
    const destination = droppedDirectory(event.target)
    void uploadItems(readWorkspaceDrop(event.dataTransfer), destination)
  }

  const toggle = (p: string) =>
    setExpanded((s) => {
      const n = new Set(s)
      n.has(p) ? n.delete(p) : n.add(p)
      return n
    })

  const onDelete = (node: FileNode) => {
    const pesan =
      node.type === 'dir'
        ? `Pindahkan folder "${node.name}" beserta seluruh isinya ke tempat sampah?`
        : `Pindahkan "${node.name}" ke tempat sampah?`
    if (window.confirm(pesan)) delMut.mutate(node.path)
  }
  const onRename = (node: FileNode) => {
    const nama = window.prompt(
      `Nama baru untuk ${node.type === 'dir' ? 'folder' : 'file'} ini:`,
      node.name,
    )
    if (nama == null) return
    const bersih = nama.trim()
    if (!bersih || bersih === node.name) return
    renameMut.mutate({ path: node.path, name: bersih })
  }
  const onDownload = (p: string) =>
    downloadFileBlob(p).catch((e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal mengunduh.'),
    )
  const onDownloadFolder = (node: FileNode) =>
    downloadFolderZip(node.path, node.name).catch((e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal mengunduh folder.'),
    )

  const tree = wsQ.data?.tree
  const usage = wsQ.data?.usage
  const quotaMb = wsQ.data?.quota_mb ?? 0
  const jumlahSampah = trashQ.data?.items.length ?? 0
  const retensiHari = trashQ.data?.retention_days ?? 0
  const overQuota = quotaMb > 0 && !!usage && usage.bytes > quotaMb * 1024 * 1024
  const empty = tree && (tree.children ?? []).length === 0
  const fileErr = fileQ.error instanceof ApiError ? fileQ.error.message : null
  const isNotebook = !!selected && selected.toLowerCase().endsWith('.ipynb')

  return (
    <div
      className="relative space-y-5"
      data-testid="storage-dropzone"
      onDragEnter={dragOver}
      onDragOver={dragOver}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropDir(null)
      }}
      onDrop={dropFiles}
    >
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">Penyimpanan</h1>
          <p className="mt-1 text-sm text-slate-500">
            Penyimpanan pribadi Anda — file &amp; paket <code className="text-slate-400">pip
            --user</code> tetap tersimpan antar-sesi notebook &amp; job. Di notebook, tulis
            path apa adanya seperti di sini, mis.{' '}
            <code className="text-slate-400">data/berkas.csv</code>.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 sm:gap-3">
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            multiple
            onChange={(e) => {
              const files = Array.from(e.target.files ?? [])
              if (files.length) void uploadItems(workspaceFileSelection(files))
              e.target.value = ''
            }}
          />
          <input
            ref={folderRef}
            type="file"
            className="hidden"
            // @ts-expect-error webkitdirectory: pemilih FOLDER (Chrome/Edge/Firefox)
            webkitdirectory=""
            multiple
            onChange={(e) => {
              const fs = Array.from(e.target.files ?? [])
              if (fs.length) void uploadItems(workspaceFileSelection(fs))
              e.target.value = ''
            }}
          />
          <button
            type="button"
            onClick={() => onDownloadFolder({ name: 'workspace', path: '', type: 'dir' })}
            disabled={!!empty}
            className="btn-ghost"
            title="Unduh seluruh workspace sebagai arsip .zip"
          >
            <IconDownload className="h-4 w-4" />
            Unduh semua
          </button>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="btn-ghost"
            title="Unggah file ke workspace (maks 256 MB)"
          >
            <IconUpload className="h-4 w-4" />
            {uploading ? 'Mengunggah…' : 'Unggah'}
          </button>
          <button
            type="button"
            onClick={() => folderRef.current?.click()}
            disabled={uploading}
            className="btn-ghost"
            title="Unggah satu folder utuh — struktur subfolder dipertahankan"
          >
            <IconFolder className="h-4 w-4" />
            Unggah Folder
          </button>
          <button
            type="button"
            onClick={() => setTrashOpen((v) => !v)}
            className={cn('btn-ghost', trashOpen && 'ring-1 ring-brand-400')}
            title="Item yang dihapus masih bisa dipulihkan dari sini"
          >
            <IconTrash className="h-4 w-4" />
            Tempat sampah
            {jumlahSampah > 0 && (
              <span className="ml-1 rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-700">
                {jumlahSampah}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={segarkanSemua}
            className="btn-ghost"
            title="Segarkan"
          >
            <IconRefresh className="h-4 w-4" />
            Segarkan
          </button>
        </div>
      </div>

      {/* Kartu pemakaian penyimpanan — bar visual ala Google Drive */}
      {usage && (
        <div className="card card-pad space-y-2.5">
          {(() => {
            const quotaBytes = quotaMb * 1024 * 1024
            const pct = quotaBytes > 0 ? Math.min(100, (usage.bytes / quotaBytes) * 100) : 0
            const sisa = Math.max(0, quotaBytes - usage.bytes)
            const warna =
              pct >= 90 ? 'bg-rose-500' : pct >= 70 ? 'bg-amber-500' : 'bg-emerald-500'
            return (
              <>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                    Pemakaian penyimpanan
                  </p>
                  <p className="text-sm text-slate-500">
                    <b
                      className={cn(
                        pct >= 90 ? 'text-rose-600' : 'text-slate-700 dark:text-slate-200',
                      )}
                    >
                      {fmtBytes(usage.bytes)}
                    </b>
                    {quotaMb > 0 ? (
                      <>
                        {' '}
                        dari {fmtBytes(quotaBytes)} ({pct.toFixed(pct >= 10 ? 0 : 1)}%)
                      </>
                    ) : (
                      ' — tanpa batas kuota'
                    )}
                    {' · '}
                    {usage.files} file
                  </p>
                </div>
                {quotaMb > 0 && (
                  <>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200/70 dark:bg-slate-700/60">
                      <div
                        className={cn('h-full rounded-full transition-all', warna)}
                        style={{ width: `${Math.max(pct, 1)}%` }}
                      />
                    </div>
                    <p className="text-xs text-slate-400">
                      {overQuota ? (
                        <span className="font-medium text-rose-500">
                          Kuota terlampaui — hapus file yang tak terpakai agar sesi/job baru
                          tidak ditolak.
                        </span>
                      ) : (
                        <>Sisa ruang: {fmtBytes(sisa)}. File pip install juga terhitung di sini.</>
                      )}
                    </p>
                  </>
                )}
              </>
            )
          })()}
        </div>
      )}

      {banner && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-300/50 bg-rose-50/70 px-4 py-2 text-sm text-rose-700">
          <span className="min-w-0 break-words">{banner}</span>
          <button type="button" onClick={() => setBanner(null)} className="text-rose-500">
            Tutup
          </button>
        </div>
      )}

      {uploading && (
        <div className="space-y-2" role="status">
          <div className="flex min-w-0 items-center gap-2 text-xs text-slate-500">
            <IconUpload className="h-4 w-4 shrink-0" />
            <span className="min-w-0 flex-1 truncate" title={uploadStatus}>{uploadStatus}</span>
            <span className="shrink-0 tabular-nums">{uploadPct}%</span>
          </div>
          <progress aria-label="Progres unggahan" value={uploadPct ?? 0} max={100} className="h-2 w-full accent-brand-500" />
        </div>
      )}

      {trashOpen && (
        <div className="card card-pad space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                Tempat sampah
              </p>
              <p className="text-xs text-slate-500">
                Item yang dihapus disimpan di sini{' '}
                {retensiHari > 0 ? <>selama {retensiHari} hari</> : 'sampai Anda kosongkan'}, lalu
                dibuang otomatis. Selama masih di sini, isinya <b>tetap terhitung kuota</b>{' '}
                penyimpanan Anda.
              </p>
            </div>
            {jumlahSampah > 0 && (
              <button
                type="button"
                onClick={() => {
                  if (window.confirm(`Kosongkan tempat sampah (${jumlahSampah} item)? Tindakan ini permanen.`))
                    purgeMut.mutate(undefined)
                }}
                className="btn-ghost text-rose-600"
              >
                <IconTrash className="h-4 w-4" />
                Kosongkan semua
              </button>
            )}
          </div>

          {trashQ.isLoading ? (
            <div className="grid place-items-center py-6">
              <Spinner label="Memuat…" />
            </div>
          ) : jumlahSampah === 0 ? (
            <p className="py-4 text-center text-sm text-slate-400">
              Tempat sampah kosong.
            </p>
          ) : (
            <ul className="divide-y divide-slate-500/10">
              {(trashQ.data?.items ?? []).map((it: WorkspaceTrashItem) => (
                <li key={it.token} className="flex flex-wrap items-center gap-2 py-2">
                  {it.type === 'dir' ? (
                    <IconFolder className="h-4 w-4 shrink-0 text-slate-400" />
                  ) : (
                    <IconFile className="h-4 w-4 shrink-0 text-slate-400" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-sm text-slate-600 dark:text-slate-300">
                      {it.path}
                    </span>
                    <span className="text-xs text-slate-400">
                      {fmtBytes(it.size)} · dihapus {fmtWaktuHapus(it.deleted_at)}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => restoreMut.mutate(it.token)}
                    disabled={restoreMut.isPending}
                    className="btn-ghost px-2 py-1 text-xs"
                    title="Kembalikan ke lokasi asalnya"
                  >
                    <IconRefresh className="h-3.5 w-3.5" />
                    Pulihkan
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Hapus "${it.name}" PERMANEN? Tidak bisa dibatalkan.`))
                        purgeMut.mutate(it.token)
                    }}
                    className="btn-ghost px-2 py-1 text-xs text-rose-600"
                    title="Hapus permanen"
                  >
                    <IconTrash className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div
        ref={panelsRef}
        data-testid="storage-panels"
        className={cn(
          'relative grid min-w-0 grid-cols-1 gap-y-5 lg:grid-cols-[var(--storage-tree-width)_12px_minmax(0,1fr)] lg:gap-y-0',
          resizing && 'select-none',
        )}
        style={{ '--storage-tree-width': `${treeWidth}px` } as CSSProperties}
      >
        {dropDir !== null && (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-start justify-center rounded-lg border-2 border-dashed border-brand-400 bg-brand-500/10 p-4">
            <div role="status" className="flex max-w-full items-center gap-2 rounded-md bg-white px-3 py-2 text-sm font-semibold text-brand-700 shadow-sm dark:bg-slate-900 dark:text-brand-300">
              <IconUpload className="h-5 w-5 shrink-0" />
              <span className="min-w-0 break-all">Unggah ke {dropDir || 'Penyimpanan'}</span>
            </div>
          </div>
        )}
        {/* Pohon file */}
        <div id="storage-tree" className="card min-w-0 max-h-[72vh] overflow-auto p-2">
          <WorkspaceDirectory path="">
            {(child) => (
              <TreeRow
                key={child.path}
                node={child}
                depth={0}
                expanded={expanded}
                toggle={toggle}
                selected={selected}
                onSelect={setSelected}
                onDownload={onDownload}
                onDownloadFolder={onDownloadFolder}
                onRename={onRename}
                onDelete={onDelete}
                dropDir={dropDir}
                uploading={uploading}
              />
            )}
          </WorkspaceDirectory>
        </div>

        <div
          role="separator"
          tabIndex={0}
          aria-label="Lebar panel folder"
          aria-orientation="vertical"
          aria-controls="storage-tree"
          aria-valuemin={TREE_MIN_WIDTH}
          aria-valuemax={Math.floor(maxTreeWidth)}
          aria-valuenow={Math.round(treeWidth)}
          title="Atur lebar panel folder"
          className="group hidden touch-none cursor-col-resize items-center justify-center rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 lg:flex"
          onPointerDown={(event) => {
            if (event.button !== 0) return
            event.preventDefault()
            resizeRef.current = { startX: event.clientX, width: treeWidth }
            event.currentTarget.setPointerCapture(event.pointerId)
            setResizing(true)
          }}
          onPointerMove={(event) => {
            if (resizeRef.current && event.currentTarget.hasPointerCapture(event.pointerId))
              setTreeWidth(resizeRef.current.width + event.clientX - resizeRef.current.startX)
          }}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              event.currentTarget.releasePointerCapture(event.pointerId)
          }}
          onLostPointerCapture={() => {
            resizeRef.current = null
            setResizing(false)
          }}
          onDoubleClick={() => setTreeWidth(TREE_DEFAULT_WIDTH)}
          onKeyDown={(event) => {
            const step = event.shiftKey ? 50 : 20
            const next = event.key === 'ArrowLeft' ? treeWidth - step
              : event.key === 'ArrowRight' ? treeWidth + step
                : event.key === 'Home' ? TREE_MIN_WIDTH
                  : event.key === 'End' ? maxTreeWidth : null
            if (next !== null) {
              event.preventDefault()
              setTreeWidth(next)
            }
          }}
        >
          <span className={cn('h-12 w-1 rounded bg-slate-300 transition group-hover:bg-brand-400 group-focus-visible:bg-brand-400 dark:bg-slate-600', resizing && 'bg-brand-500')} />
        </div>

        {/* Pratinjau file */}
        <div id="storage-preview" className="card flex min-h-[50vh] min-w-0 flex-col overflow-hidden">
          {!selected ? (
            <div className="grid flex-1 place-items-center px-4 text-center text-sm text-slate-400">
              <div>
                <IconFile className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                Pilih file di kiri untuk melihat isinya.
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-500/10 px-4 py-2.5">
                <span className="min-w-0 truncate font-mono text-sm text-slate-600">
                  {selected}
                </span>
                <span className="flex max-w-full flex-wrap items-center gap-1.5">
                  {isNotebook && (
                    <span className="mr-1 flex overflow-hidden rounded-md ring-1 ring-slate-300/60">
                      <button
                        type="button"
                        onClick={() => setRawView(false)}
                        className={cn(
                          'px-2 py-1 text-[11px] font-medium transition',
                          !rawView ? 'bg-brand-600 text-white' : 'text-slate-500 hover:bg-slate-500/10',
                        )}
                      >
                        Notebook
                      </button>
                      <button
                        type="button"
                        onClick={() => setRawView(true)}
                        className={cn(
                          'px-2 py-1 text-[11px] font-medium transition',
                          rawView ? 'bg-brand-600 text-white' : 'text-slate-500 hover:bg-slate-500/10',
                        )}
                      >
                        Kode mentah
                      </button>
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => onDownload(selected)}
                    className="btn-ghost px-2 py-1 text-xs"
                  >
                    <IconDownload className="h-3.5 w-3.5" />
                    Unduh
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      onDelete({ name: selected.split('/').pop() || selected, path: selected, type: 'file' })
                    }
                    className="btn-ghost px-2 py-1 text-xs text-rose-600 hover:bg-rose-500/10"
                    disabled={uploading}
                  >
                    <IconTrash className="h-3.5 w-3.5" />
                    Hapus
                  </button>
                </span>
              </div>
              <div className="flex-1 overflow-hidden">
                {fileQ.isLoading ? (
                  <div className="grid h-full place-items-center">
                    <Spinner label="Memuat file…" />
                  </div>
                ) : fileErr ? (
                  <div className="grid h-full place-items-center px-4 text-center text-sm text-slate-500">
                    <div>
                      <p className="mb-3">{fileErr}</p>
                      <button
                        type="button"
                        onClick={() => onDownload(selected)}
                        className="btn"
                      >
                        <IconDownload className="h-4 w-4" />
                        Unduh file
                      </button>
                    </div>
                  </div>
                ) : fileQ.data ? (
                  <>
                    {fileQ.data.truncated && (
                      <div className="bg-amber-50 px-4 py-1.5 text-xs text-amber-700">
                        File besar — hanya sebagian awal yang ditampilkan. Unduh untuk isi penuh.
                      </div>
                    )}
                    {isNotebook && !rawView ? (
                      <div className="h-[62vh] overflow-auto">
                        <NotebookPreview content={fileQ.data.content} />
                      </div>
                    ) : (
                      <CodeEditor
                        value={fileQ.data.content}
                        onChange={() => {}}
                        language={fileQ.data.language}
                        readOnly
                        lint={false}
                        summaryMode="hidden"
                        height="62vh"
                      />
                    )}
                  </>
                ) : null}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
