// Explorer + editor project job (halaman detail job). Gaya VS Code seperti Notebook
// Interaktif: buka/edit/simpan file, tambah file/folder, rename, hapus, refresh.
// CRUD hanya aktif saat job SUDAH SELESAI (editable); backend juga menegakkannya.
// Bila job tak punya folder project (tempel kode / notebook) -> panel menyembunyikan diri.
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import Editor from '@monaco-editor/react'

import { ApiError, api } from '../lib/api'
import { cn } from '../lib/format'
import type { FileNode, InteractiveFile } from '../lib/types'
import { IconChevron, IconFile, IconFolder, IconRefresh, IconX } from './icons'
import ImagePreview, { isImagePath } from './ImagePreview'
import NotebookPreview from './NotebookPreview'

export default function JobProjectPanel({
  jobId,
  editable,
}: {
  jobId: number
  editable: boolean
}) {
  const qc = useQueryClient()
  const [openFile, setOpenFile] = useState<InteractiveFile | null>(null)
  // Pratinjau GAMBAR (objectURL blob terautentikasi) -> di-revoke saat ditutup.
  const [openImg, setOpenImg] = useState<{ name: string; url: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // Revoke object URL gambar saat ganti/tutup/unmount (cegah bocor memori blob).
  useEffect(
    () => () => {
      if (openImg) URL.revokeObjectURL(openImg.url)
    },
    [openImg],
  )

  const treeQ = useQuery({
    queryKey: ['job-files', jobId],
    queryFn: () => api.jobFiles(jobId),
    retry: false,
  })

  const refresh = () => qc.invalidateQueries({ queryKey: ['job-files', jobId] })
  const run = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try {
      await fn()
      refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Operasi gagal.')
    }
  }

  const doOpen = async (path: string) => {
    setErr(null)
    // Gambar -> pratinjau visual (byte mentah sebagai blob).
    const name = path.split('/').pop() || path
    if (isImagePath(name)) {
      try {
        const blob = await api.jobReadFileRaw(jobId, path)
        setOpenImg({ name, url: URL.createObjectURL(blob) })
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : 'Gagal membuka gambar.')
      }
      return
    }
    try {
      setOpenFile(await api.jobReadFile(jobId, path))
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Gagal membuka file.')
    }
  }
  const newFile = (dir: string) => {
    const name = window.prompt('Nama file baru:', dir ? `${dir}/baru.py` : 'baru.py')
    if (name) void run(() => api.jobWriteFile(jobId, name, ''))
  }
  const newFolder = (dir: string) => {
    const name = window.prompt('Nama folder baru:', dir ? `${dir}/folder` : 'folder')
    if (name) void run(() => api.jobMkdir(jobId, name))
  }
  const rename = (path: string, cur: string) => {
    const to = window.prompt(`Ganti nama "${cur}" menjadi (path relatif):`, path)
    if (to && to !== path) void run(() => api.jobRenameItem(jobId, path, to))
  }
  const del = (path: string) => {
    if (window.confirm(`Hapus "${path}"? Tindakan ini tidak bisa dibatalkan.`))
      void run(() => api.jobDeleteItem(jobId, path))
  }
  const save = async (content: string) => {
    if (!openFile) return
    await run(() => api.jobWriteFile(jobId, openFile.path, content))
  }

  if (treeQ.isLoading)
    return <p className="card-pad text-xs text-slate-400">Memuat file project…</p>
  // Job tanpa folder project (tempel kode / notebook) -> backend 400 -> sembunyikan.
  if (treeQ.isError || !treeQ.data) return null
  const tree = treeQ.data.tree

  return (
    <div className="card-pad">
      <div className="mb-2 flex items-center gap-2">
        <IconFolder className="h-4 w-4 text-amber-500" />
        <h3 className="flex-1 text-sm font-semibold text-slate-700">
          File project{' '}
          <span className="font-normal text-slate-400">
            {editable ? '· bisa diedit (klik file)' : '· hanya baca (job belum selesai)'}
          </span>
        </h3>
        {editable && (
          <>
            <button
              onClick={() => newFile('')}
              className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
            >
              + File
            </button>
            <button
              onClick={() => newFolder('')}
              className="rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-brand-50 hover:text-brand-700"
            >
              + Folder
            </button>
          </>
        )}
        <button
          onClick={refresh}
          title="Muat ulang"
          className="text-slate-400 hover:text-brand-600"
        >
          <IconRefresh className={cn('h-3.5 w-3.5', treeQ.isFetching && 'animate-spin')} />
        </button>
      </div>
      {err && (
        <p className="mb-2 rounded-lg bg-rose-50 px-3 py-1.5 text-xs text-rose-600">{err}</p>
      )}
      <div className="max-h-[28rem] overflow-auto rounded-lg p-1.5 ring-1 ring-slate-100">
        {tree.children && tree.children.length ? (
          tree.children.map((n) => (
            <JobTreeNode
              key={n.path}
              node={n}
              depth={0}
              editable={editable}
              onOpen={doOpen}
              onNewFile={newFile}
              onNewFolder={newFolder}
              onRename={rename}
              onDelete={del}
            />
          ))
        ) : (
          <p className="px-2 py-3 text-xs text-slate-400">Project kosong.</p>
        )}
      </div>
      {openFile && (
        <JobFileModal
          file={openFile}
          editable={editable}
          onClose={() => setOpenFile(null)}
          onSave={save}
        />
      )}
      {openImg && (
        <ImagePreview
          name={openImg.name}
          url={openImg.url}
          onClose={() => {
            URL.revokeObjectURL(openImg.url)
            setOpenImg(null)
          }}
        />
      )}
    </div>
  )
}

function JobTreeNode({
  node,
  depth,
  editable,
  onOpen,
  onNewFile,
  onNewFolder,
  onRename,
  onDelete,
}: {
  node: FileNode
  depth: number
  editable: boolean
  onOpen: (p: string) => void
  onNewFile: (d: string) => void
  onNewFolder: (d: string) => void
  onRename: (p: string, n: string) => void
  onDelete: (p: string) => void
}) {
  const [open, setOpen] = useState(depth < 1)
  const pad = { paddingLeft: `${depth * 12 + 8}px` }

  if (node.type === 'file') {
    return (
      <div className="group flex items-center rounded-md hover:bg-brand-50" style={pad}>
        <button
          onClick={() => onOpen(node.path)}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-xs text-slate-600 group-hover:text-brand-700"
        >
          <IconFile className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate">{node.name}</span>
        </button>
        {editable && (
          <span className="flex shrink-0 items-center pr-1 opacity-0 group-hover:opacity-100">
            <button onClick={() => onRename(node.path, node.name)} title="Ganti nama" className="px-1 text-[11px] text-slate-400 hover:text-brand-600">✎</button>
            <button onClick={() => onDelete(node.path)} title="Hapus" className="text-slate-400 hover:text-rose-600"><IconX className="h-3 w-3" /></button>
          </span>
        )}
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
        {editable && (
          <span className="flex shrink-0 items-center pr-1 opacity-0 group-hover:opacity-100">
            <button onClick={() => onNewFile(node.path)} title="File baru di sini" className="text-slate-400 hover:text-brand-600"><IconFile className="h-3 w-3" /></button>
            <button onClick={() => onNewFolder(node.path)} title="Folder baru di sini" className="ml-0.5 text-slate-400 hover:text-brand-600"><IconFolder className="h-3 w-3" /></button>
            <button onClick={() => onRename(node.path, node.name)} title="Ganti nama" className="ml-0.5 px-0.5 text-[11px] text-slate-400 hover:text-brand-600">✎</button>
            <button onClick={() => onDelete(node.path)} title="Hapus" className="text-slate-400 hover:text-rose-600"><IconX className="h-3 w-3" /></button>
          </span>
        )}
      </div>
      {open &&
        node.children?.map((c) => (
          <JobTreeNode
            key={c.path}
            node={c}
            depth={depth + 1}
            editable={editable}
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

function JobFileModal({
  file,
  editable,
  onClose,
  onSave,
}: {
  file: InteractiveFile
  editable: boolean
  onClose: () => void
  onSave: (content: string) => void
}) {
  const [content, setContent] = useState(file.content)
  const [dirty, setDirty] = useState(false)
  const isNotebook = file.path.toLowerCase().endsWith('.ipynb')
  // Notebook -> default tampilan ter-render; berkas lain selalu "mentah" (editor).
  const [raw, setRaw] = useState(!isNotebook)
  const canEdit = editable && !file.truncated
  return createPortal(
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
          {file.truncated && (
            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">dipotong (tak bisa edit)</span>
          )}
          {canEdit && raw && (
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
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {isNotebook && !raw ? (
            <NotebookPreview
              content={content}
              editable={canEdit}
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
                if (!canEdit) return
                setContent(v ?? '')
                setDirty(true)
              }}
              options={{
                readOnly: !canEdit,
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
    </div>,
    document.body,
  )
}
