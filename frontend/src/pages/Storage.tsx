// Halaman PENYIMPANAN — file browser workspace persisten per-user (/persist), ala Colab Drive.
// File yang dibuat dari notebook/job (mis. dataset, checkpoint model) + paket `pip --user`
// tetap tersimpan di sini antar-sesi. Bisa lihat isi, unduh, dan hapus file.

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import CodeEditor from '../components/CodeEditor'
import NotebookPreview from '../components/NotebookPreview'
import Spinner from '../components/Spinner'
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
}) {
  const isDir = node.type === 'dir'
  const open = expanded.has(node.path)
  const isSel = selected === node.path && !isDir
  return (
    <>
      <div
        className={cn(
          'group flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm transition',
          isSel ? 'bg-brand-500/15 text-brand-700' : 'hover:bg-slate-500/10',
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <button
          type="button"
          onClick={() => (isDir ? toggle(node.path) : onSelect(node.path))}
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
            className="rounded p-1 text-slate-500 hover:bg-slate-500/15 hover:text-brand-600"
          >
            <IconPencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title={isDir ? 'Hapus folder beserta isinya' : 'Hapus'}
            onClick={() => onDelete(node)}
            className="rounded p-1 text-slate-500 hover:bg-rose-500/15 hover:text-rose-600"
          >
            <IconTrash className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
      {isDir && open &&
        (node.children ?? []).map((c) => (
          <TreeRow
            key={c.path}
            node={c}
            depth={depth + 1}
            expanded={expanded}
            toggle={toggle}
            selected={selected}
            onSelect={onSelect}
            onDownload={onDownload}
            onDownloadFolder={onDownloadFolder}
            onRename={onRename}
            onDelete={onDelete}
          />
        ))}
    </>
  )
}

export default function Storage() {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
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
  const [uploading, setUploading] = useState(false)
  const uploadMut = useMutation({
    mutationFn: (file: File) => api.uploadWorkspaceFile(file),
    onMutate: () => setUploading(true),
    onSettled: () => setUploading(false),
    onSuccess: (r) => {
      setBanner(null)
      setSelected(r.path)
      qc.invalidateQueries({ queryKey: ['workspace'] })
    },
    onError: (e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal mengunggah file.'),
  })

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
    <div className="space-y-5">
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
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) uploadMut.mutate(f)
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
        <div className="flex items-center justify-between rounded-xl border border-rose-300/50 bg-rose-50/70 px-4 py-2 text-sm text-rose-700">
          <span>{banner}</span>
          <button type="button" onClick={() => setBanner(null)} className="text-rose-500">
            Tutup
          </button>
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

      <div className="grid gap-5 lg:grid-cols-[300px,1fr]">
        {/* Pohon file */}
        <div className="card max-h-[72vh] overflow-auto p-2">
          {wsQ.isLoading ? (
            <div className="grid place-items-center py-12">
              <Spinner label="Memuat…" />
            </div>
          ) : empty ? (
            <div className="px-3 py-10 text-center text-sm text-slate-500">
              <IconFolder className="mx-auto mb-2 h-8 w-8 text-slate-300" />
              Penyimpanan masih kosong. File yang Anda unggah atau yang dibuat dari
              notebook/job akan muncul di sini.
            </div>
          ) : (
            (tree?.children ?? []).map((c) => (
              <TreeRow
                key={c.path}
                node={c}
                depth={0}
                expanded={expanded}
                toggle={toggle}
                selected={selected}
                onSelect={setSelected}
                onDownload={onDownload}
                onDownloadFolder={onDownloadFolder}
                onRename={onRename}
                onDelete={onDelete}
              />
            ))
          )}
        </div>

        {/* Pratinjau file */}
        <div className="card flex min-h-[50vh] flex-col overflow-hidden">
          {!selected ? (
            <div className="grid flex-1 place-items-center px-4 text-center text-sm text-slate-400">
              <div>
                <IconFile className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                Pilih file di kiri untuk melihat isinya.
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3 border-b border-slate-500/10 px-4 py-2.5">
                <span className="truncate font-mono text-sm text-slate-600">
                  {selected}
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
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
