// Ruang Kelas A4: "Ruang kerja kelas" (mahasiswa) + "Pantau Kelas" (pengajar/asisten).
// Pengajar HANYA melihat isi folder Kelas/<nama>/ milik mahasiswa, baca-saja — bukan layar,
// jendela lain, atau berkas di luar folder kelas.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import CodeEditor from './CodeEditor'
import NotebookPreview from './NotebookPreview'
import Spinner from './Spinner'
import { IconCode, IconEye, IconFile, IconFolder, IconX } from './icons'
import { api, ApiError } from '../lib/api'
import { cn, formatBytes, timeAgo } from '../lib/format'
import type { ClassMonitorStudent, DevboxStatus } from '../lib/types'

const POLL_GRID_MS = 5000
const POLL_FILE_MS = 3000
const DEVBOX_WAIT_MS = 4 * 60 * 1000

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError || e instanceof Error ? e.message : fallback

const ago = (epoch: number | null | undefined) =>
  epoch ? timeAgo(new Date(epoch * 1000).toISOString()) : '-'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function tulisTab(tab: Window | null, pesan: string) {
  try {
    tab?.document.write(
      `<p style="font-family:sans-serif;padding:2rem;color:#334155">${pesan}</p>`,
    )
  } catch {
    /* tab lintas-origin: abaikan */
  }
}

/** Nyalakan Devbox bila perlu (aturan & kuota biasa), tunggu IDE siap, lalu buka
 *  VS Code langsung di folder kelas. Tab dibuka SINKRON saat klik (lolos pemblokir pop-up). */
async function bukaDevboxKelas(classId: number) {
  const tab = window.open('', '_blank')
  tulisTab(tab, 'Menyiapkan Devbox dan folder kelas Anda&hellip;')
  try {
    const ws = await api.getClassWorkspace(classId)
    let st: DevboxStatus = await api.getDevbox()
    if (st.web_enabled === false) throw new Error('IDE web Devbox sedang nonaktif.')
    if (st.state === 'stopped' || st.state === 'error') st = await api.startDevbox()
    const batas = Date.now() + DEVBOX_WAIT_MS
    while (!(st.state === 'running' && st.web_url)) {
      if (st.state === 'queued')
        throw new Error('Devbox sedang mengantre. Pantau di halaman Devbox lalu coba lagi.')
      if (st.state === 'stopped' || st.state === 'error')
        throw new Error('Devbox gagal menyala. Buka halaman Devbox untuk detailnya.')
      if (Date.now() > batas) throw new Error('Devbox belum siap. Coba lagi sebentar lagi.')
      await sleep(3000)
      st = await api.getDevbox()
    }
    const t = await api.devboxWebTicket()
    const url = `${t.url}&folder=${encodeURIComponent(`/persist/${ws.path}`)}`
    if (tab) tab.location.href = url
    else window.location.assign(url)
  } catch (e) {
    tab?.close()
    throw e
  }
}

export function ClassWorkspaceCard({ classId }: { classId: number }) {
  const q = useQuery({
    queryKey: ['class-workspace', classId],
    queryFn: () => api.getClassWorkspace(classId),
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const buka = async () => {
    setErr(null)
    setBusy(true)
    try {
      await bukaDevboxKelas(classId)
    } catch (e) {
      setErr(errText(e, 'Gagal membuka Devbox.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card p-5">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-bold text-slate-800">
        <IconCode className="h-4 w-4 text-brand-600" /> Ruang kerja kelas
      </h2>
      {q.isLoading ? (
        <Spinner />
      ) : q.isError ? (
        <p className="text-sm text-rose-600">{errText(q.error, 'Gagal memuat ruang kerja.')}</p>
      ) : q.data ? (
        <>
          <p className="text-sm text-slate-600">
            Kerjakan tugas kelas di folder{' '}
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{q.data.path}/</code>. Folder
            ini memakai kuota penyimpanan Anda dan tetap milik Anda walau keluar dari kelas.
          </p>
          {q.data.monitored && (
            <p className="mt-2 flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <IconEye className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                Pengajar dapat <b>melihat (baca-saja)</b> isi folder ini selama Anda anggota kelas.
                Berkas lain, layar, dan aplikasi lain di perangkat Anda <b>tidak</b> terlihat.
              </span>
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={busy} onClick={() => void buka()}>
              {busy ? 'Menyiapkan Devbox...' : 'Buka di Devbox'}
            </button>
            <Link to={`/storage?dir=${encodeURIComponent(q.data.path)}`} className="btn-ghost">
              Buka di Penyimpanan
            </Link>
          </div>
          {err && <p className="mt-2 text-sm text-rose-600">{err}</p>}
        </>
      ) : null}
    </div>
  )
}

const DEVBOX_LABEL: Record<string, [string, string]> = {
  running: ['Devbox menyala', 'bg-emerald-100 text-emerald-700'],
  starting: ['Devbox menyala...', 'bg-amber-100 text-amber-700'],
  queued: ['Devbox antre', 'bg-amber-100 text-amber-700'],
}

function Tile({ s, onOpen }: { s: ClassMonitorStudent; onOpen: () => void }) {
  const [label, cls] = DEVBOX_LABEL[s.devbox_state] ?? ['Devbox mati', 'bg-slate-100 text-slate-500']
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!s.exists}
      className="flex flex-col rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:border-brand-300 hover:shadow disabled:cursor-default disabled:opacity-70 disabled:hover:shadow-none"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-slate-800">{s.name}</span>
        <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold', cls)}>{label}</span>
      </div>
      {s.exists ? (
        <>
          <p className="mt-1 truncate text-xs text-slate-500">
            {s.last_file ? (
              <>
                <b className="text-slate-700">{s.last_file}</b> · disimpan {ago(s.last_modified)}
              </>
            ) : (
              'Folder masih kosong'
            )}
          </p>
          <p className="text-[11px] text-slate-400">
            {s.file_count}
            {s.truncated ? '+' : ''} berkas · {formatBytes(s.total_bytes)}
          </p>
          <pre className="mt-2 h-28 overflow-hidden whitespace-pre-wrap break-all rounded-lg bg-slate-900 p-2 font-mono text-[10px] leading-snug text-slate-200">
            {s.snippet?.split('\n').slice(0, 12).join('\n') || ' '}
          </pre>
        </>
      ) : (
        <p className="mt-1 text-xs text-slate-400">Belum membuka ruang kerja kelas.</p>
      )}
    </button>
  )
}

export function MonitorPanel({ classId }: { classId: number }) {
  const [aktif, setAktif] = useState(false)
  const [viewing, setViewing] = useState<ClassMonitorStudent | null>(null)
  const q = useQuery({
    queryKey: ['class-monitor', classId],
    queryFn: () => api.monitorClass(classId),
    enabled: aktif,
    refetchInterval: aktif && !viewing ? POLL_GRID_MS : false,
  })

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-slate-800">
            <IconEye className="h-4 w-4 text-brand-600" /> Pantau Kelas
          </h2>
          <p className="text-xs text-slate-500">
            Isi folder kelas tiap mahasiswa, baca-saja, diperbarui tiap 5 detik. Hanya folder kelas —
            bukan layar atau berkas lain mahasiswa.
          </p>
        </div>
        <button type="button" className={aktif ? 'btn-ghost' : 'btn-primary'} onClick={() => setAktif((v) => !v)}>
          {aktif ? 'Berhenti memantau' : 'Mulai pantau'}
        </button>
      </div>
      {aktif && (
        <div className="mt-4">
          {q.isLoading ? (
            <Spinner />
          ) : q.isError ? (
            <p className="text-sm text-rose-600">{errText(q.error, 'Gagal memuat pantauan.')}</p>
          ) : !q.data?.length ? (
            <p className="text-sm text-slate-500">Belum ada mahasiswa di kelas ini.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {q.data.map((s) => (
                <Tile key={s.user_id} s={s} onOpen={() => setViewing(s)} />
              ))}
            </div>
          )}
        </div>
      )}
      {viewing && <Viewer classId={classId} student={viewing} onClose={() => setViewing(null)} />}
    </div>
  )
}

function TreeDir({
  classId,
  uid,
  path,
  depth,
  selected,
  onOpen,
}: {
  classId: number
  uid: number
  path: string
  depth: number
  selected: string | null
  onOpen: (p: string) => void
}) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const q = useQuery({
    queryKey: ['class-monitor-tree', classId, uid, path],
    queryFn: () => api.monitorClassTree(classId, uid, path),
    refetchInterval: POLL_GRID_MS,
  })
  if (q.isLoading) return <div className="px-2 py-1 text-xs text-slate-400">Memuat...</div>
  if (q.isError) return <div className="px-2 py-1 text-xs text-rose-600">{errText(q.error, 'Gagal memuat.')}</div>
  if (!q.data?.length && depth === 0) return <div className="px-2 py-1 text-xs text-slate-400">Folder kosong.</div>
  return (
    <ul>
      {q.data?.map((e) => {
        const p = path ? `${path}/${e.name}` : e.name
        const pad = { paddingLeft: `${depth * 12 + 8}px` }
        if (e.type === 'dir') {
          const isOpen = open.has(p)
          return (
            <li key={p}>
              <button
                type="button"
                style={pad}
                className="flex w-full items-center gap-1.5 py-1 pr-2 text-left text-xs text-slate-700 hover:bg-slate-100"
                onClick={() =>
                  setOpen((s) => {
                    const n = new Set(s)
                    n.has(p) ? n.delete(p) : n.add(p)
                    return n
                  })
                }
              >
                <IconFolder className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                <span className="truncate">{e.name}</span>
              </button>
              {isOpen && (
                <TreeDir classId={classId} uid={uid} path={p} depth={depth + 1} selected={selected} onOpen={onOpen} />
              )}
            </li>
          )
        }
        return (
          <li key={p}>
            <button
              type="button"
              style={pad}
              className={cn(
                'flex w-full items-center gap-1.5 py-1 pr-2 text-left text-xs hover:bg-slate-100',
                selected === p ? 'bg-brand-50 font-semibold text-brand-700' : 'text-slate-600',
              )}
              onClick={() => onOpen(p)}
            >
              <IconFile className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              <span className="truncate">{e.name}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function Viewer({
  classId,
  student,
  onClose,
}: {
  classId: number
  student: ClassMonitorStudent
  onClose: () => void
}) {
  const [file, setFile] = useState<string | null>(student.last_file)
  const fq = useQuery({
    queryKey: ['class-monitor-file', classId, student.user_id, file],
    queryFn: () => api.monitorClassFile(classId, student.user_id, file as string),
    enabled: !!file,
    refetchInterval: POLL_FILE_MS,
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const d = fq.data

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-bold text-slate-800">Ruang kerja {student.name}</h3>
            <p className="text-xs text-slate-500">Baca-saja · hanya folder kelas · diperbarui otomatis</p>
          </div>
          <button type="button" className="btn-ghost p-2" onClick={onClose} aria-label="Tutup">
            <IconX className="h-4 w-4" />
          </button>
        </div>
        <div className="flex min-h-0 flex-1">
          <div className="w-64 shrink-0 overflow-y-auto border-r border-slate-200 py-2">
            <TreeDir classId={classId} uid={student.user_id} path="" depth={0} selected={file} onOpen={setFile} />
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            {!file ? (
              <p className="m-auto text-sm text-slate-400">Pilih berkas di kiri.</p>
            ) : fq.isLoading ? (
              <div className="m-auto">
                <Spinner />
              </div>
            ) : fq.isError ? (
              <p className="m-auto text-sm text-rose-600">{errText(fq.error, 'Gagal membuka berkas.')}</p>
            ) : d ? (
              <>
                <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
                  <span className="truncate font-mono text-slate-700">{d.path}</span>
                  <span className="shrink-0">
                    {formatBytes(d.size)} · disimpan {ago(d.modified)}
                  </span>
                </div>
                <div className="min-h-0 flex-1 overflow-auto">
                  {d.content == null ? (
                    <p className="p-6 text-sm text-slate-500">
                      {d.reason === 'too_large'
                        ? 'Berkas terlalu besar untuk ditampilkan (maks 2 MB).'
                        : 'Berkas biner tidak dapat ditampilkan.'}
                    </p>
                  ) : d.path.toLowerCase().endsWith('.ipynb') ? (
                    <div className="p-4">
                      <NotebookPreview content={d.content} />
                    </div>
                  ) : (
                    <CodeEditor value={d.content} onChange={() => {}} language={d.language} height="100%" readOnly lint={false} />
                  )}
                </div>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
