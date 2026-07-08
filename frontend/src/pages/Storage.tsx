// Halaman PENYIMPANAN — file browser workspace persisten per-user (/persist), ala Colab Drive.
// File yang dibuat dari notebook/job (mis. dataset, checkpoint model) + paket `pip --user`
// tetap tersimpan di sini antar-sesi. Bisa lihat isi, unduh, dan hapus file.

import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import CodeEditor from '../components/CodeEditor'
import Spinner from '../components/Spinner'
import {
  IconChevron,
  IconDownload,
  IconFile,
  IconFolder,
  IconRefresh,
  IconTrash,
  IconUpload,
} from '../components/icons'
import { ApiError, api } from '../lib/api'
import { cn } from '../lib/format'
import type { FileNode } from '../lib/types'

function fmtBytes(n: number): string {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
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
        {isDir ? (
          <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
            <button
              type="button"
              title="Unduh folder (.zip)"
              onClick={() => onDownloadFolder(node)}
              className="rounded p-1 text-slate-500 hover:bg-slate-500/15 hover:text-brand-600"
            >
              <IconDownload className="h-3.5 w-3.5" />
            </button>
          </span>
        ) : (
          <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
            <button
              type="button"
              title="Unduh"
              onClick={() => onDownload(node.path)}
              className="rounded p-1 text-slate-500 hover:bg-slate-500/15 hover:text-brand-600"
            >
              <IconDownload className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Hapus"
              onClick={() => onDelete(node)}
              className="rounded p-1 text-slate-500 hover:bg-rose-500/15 hover:text-rose-600"
            >
              <IconTrash className="h-3.5 w-3.5" />
            </button>
          </span>
        )}
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
      qc.invalidateQueries({ queryKey: ['workspace'] })
    },
    onError: (e) =>
      setBanner(e instanceof ApiError ? e.message : 'Gagal menghapus file.'),
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
    if (window.confirm(`Hapus "${node.name}" dari workspace? Tindakan ini permanen.`))
      delMut.mutate(node.path)
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
  const overQuota = quotaMb > 0 && !!usage && usage.bytes > quotaMb * 1024 * 1024
  const empty = tree && (tree.children ?? []).length === 0
  const fileErr = fileQ.error instanceof ApiError ? fileQ.error.message : null

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">Penyimpanan</h1>
          <p className="mt-1 text-sm text-slate-500">
            Workspace persisten Anda (<code className="text-slate-400">/persist</code>) —
            file & paket <code className="text-slate-400">pip --user</code> tetap tersimpan
            antar-sesi notebook & job.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {usage && (
            <span
              className={cn(
                'rounded-full px-3 py-1.5 text-xs font-medium',
                overQuota
                  ? 'bg-rose-500/15 text-rose-600'
                  : 'bg-slate-500/10 text-slate-500',
              )}
              title={quotaMb > 0 ? `Kuota penyimpanan ${quotaMb} MB` : 'Tanpa batas kuota'}
            >
              {usage.files} file · {fmtBytes(usage.bytes)}
              {quotaMb > 0 ? ` / ${quotaMb} MB` : ''}
            </span>
          )}
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
            onClick={() => qc.invalidateQueries({ queryKey: ['workspace'] })}
            className="btn-ghost"
            title="Segarkan"
          >
            <IconRefresh className="h-4 w-4" />
            Segarkan
          </button>
        </div>
      </div>

      {banner && (
        <div className="flex items-center justify-between rounded-xl border border-rose-300/50 bg-rose-50/70 px-4 py-2 text-sm text-rose-700">
          <span>{banner}</span>
          <button type="button" onClick={() => setBanner(null)} className="text-rose-500">
            Tutup
          </button>
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
              Workspace masih kosong. File yang Anda buat dari notebook/job (mis. ke
              <code className="px-1 text-slate-400">/persist</code>) akan muncul di sini.
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
                    <CodeEditor
                      value={fileQ.data.content}
                      onChange={() => {}}
                      language={fileQ.data.language}
                      readOnly
                      lint={false}
                      summaryMode="hidden"
                      height="62vh"
                    />
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
