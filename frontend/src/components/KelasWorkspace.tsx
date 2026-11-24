// Ruang Kelas A4: "Ruang kerja kelas" (mahasiswa) + "Pantau Kelas" (pengajar/asisten).
// Pengajar HANYA melihat isi folder Kelas/<nama>/ milik mahasiswa, baca-saja — bukan layar,
// jendela lain, atau berkas di luar folder kelas.
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import CodeEditor from './CodeEditor'
import NotebookPreview from './NotebookPreview'
import { PresenceBadge, presenceOf } from './Presence'
import Spinner from './Spinner'
import { IconCode, IconEye, IconFile, IconFolder, IconTerminal, IconX } from './icons'
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
      <PresenceBadge lastSeen={s.last_seen_at} className="mt-0.5" />
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

export function MonitorPanel({ classId, className }: { classId: number; className: string }) {
  const [aktif, setAktif] = useState(false)
  const [viewing, setViewing] = useState<number | null>(null)
  const q = useQuery({
    queryKey: ['class-monitor', classId],
    queryFn: () => api.monitorClass(classId),
    enabled: aktif,
    // Saat penampil terbuka, tetap dipantau lebih rapat agar mode "Ikuti" cepat berpindah berkas.
    refetchInterval: aktif ? (viewing ? POLL_FILE_MS : POLL_GRID_MS) : false,
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
            <>
            <p className="mb-2 text-xs text-slate-500" data-testid="class-presence-summary">
              <b className="text-emerald-600">
                {q.data.filter((s) => presenceOf(s.last_seen_at) === 'online').length}
              </b>{' '}
              dari {q.data.length} mahasiswa sedang membuka ComputeHub.
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {q.data.map((s) => (
                <Tile key={s.user_id} s={s} onOpen={() => setViewing(s.user_id)} />
              ))}
            </div>
            </>
          )}
        </div>
      )}
      {viewing != null &&
        (() => {
          const s = q.data?.find((x) => x.user_id === viewing)
          return s ? (
            <Viewer classId={classId} className={className} student={s} onClose={() => setViewing(null)} />
          ) : null
        })()}
    </div>
  )
}


// ------------------------------------------------------------------ Penampil ala VS Code
// Meniru layar VS Code mahasiswa (explorer, tab, editor, status bar) tetapi BACA-SAJA dan
// hanya berisi folder kelas. Mode "Ikuti" otomatis membuka berkas yang terakhir disimpan
// mahasiswa — terasa seperti melihat layarnya, tanpa merekam layar/jendela lain.

const VS = {
  bg: 'bg-[#1e1e1e]',
  side: 'bg-[#252526]',
  bar: 'bg-[#333333]',
  title: 'bg-[#3c3c3c]',
}

function TreeDir({
  classId,
  uid,
  path,
  depth,
  selected,
  onOpen,
  expanded,
  toggle,
}: {
  classId: number
  uid: number
  path: string
  depth: number
  selected: string | null
  onOpen: (p: string) => void
  expanded: Set<string>
  toggle: (p: string) => void
}) {
  const q = useQuery({
    queryKey: ['class-monitor-tree', classId, uid, path],
    queryFn: () => api.monitorClassTree(classId, uid, path),
    refetchInterval: POLL_GRID_MS,
  })
  const pad = (d: number) => ({ paddingLeft: `${d * 10 + 12}px` })
  if (q.isLoading) return <div style={pad(depth)} className="py-0.5 text-[12px] text-slate-500">Memuat...</div>
  if (q.isError)
    return <div style={pad(depth)} className="py-0.5 text-[12px] text-rose-400">{errText(q.error, 'Gagal memuat.')}</div>
  if (!q.data?.length && depth === 0)
    return <div style={pad(depth)} className="py-1 text-[12px] text-slate-500">Folder masih kosong.</div>
  return (
    <ul>
      {q.data?.map((e) => {
        const p = path ? `${path}/${e.name}` : e.name
        if (e.type === 'dir') {
          const open = expanded.has(p)
          return (
            <li key={p}>
              <button
                type="button"
                style={pad(depth)}
                className="flex w-full items-center gap-1 py-[3px] pr-2 text-left text-[13px] text-[#cccccc] hover:bg-[#2a2d2e]"
                onClick={() => toggle(p)}
              >
                <span className="w-3 text-[10px] text-slate-400">{open ? '▾' : '▸'}</span>
                <IconFolder className="h-3.5 w-3.5 shrink-0 text-[#dcb67a]" />
                <span className="truncate">{e.name}</span>
              </button>
              {open && (
                <TreeDir
                  classId={classId}
                  uid={uid}
                  path={p}
                  depth={depth + 1}
                  selected={selected}
                  onOpen={onOpen}
                  expanded={expanded}
                  toggle={toggle}
                />
              )}
            </li>
          )
        }
        return (
          <li key={p}>
            <button
              type="button"
              style={pad(depth)}
              className={cn(
                'flex w-full items-center gap-1 py-[3px] pr-2 text-left text-[13px] hover:bg-[#2a2d2e]',
                selected === p ? 'bg-[#37373d] text-white' : 'text-[#cccccc]',
              )}
              onClick={() => onOpen(p)}
            >
              <span className="w-3" />
              <IconFile className="h-3.5 w-3.5 shrink-0 text-[#519aba]" />
              <span className="truncate">{e.name}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

const LANG_LABEL: Record<string, string> = {
  python: 'Python', javascript: 'JavaScript', typescript: 'TypeScript', json: 'JSON',
  markdown: 'Markdown', html: 'HTML', css: 'CSS', shell: 'Shell', yaml: 'YAML', plaintext: 'Teks',
}

function Viewer({
  classId,
  className,
  student,
  onClose,
}: {
  classId: number
  className: string
  student: ClassMonitorStudent
  onClose: () => void
}) {
  const [follow, setFollow] = useState(true)
  const [tabs, setTabs] = useState<string[]>(student.last_file ? [student.last_file] : [])
  const [file, setFile] = useState<string | null>(student.last_file)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const buka = (p: string, manual = true) => {
    if (manual) setFollow(false)
    setTabs((t) => (t.includes(p) ? t : [...t, p]))
    setFile(p)
    // Pastikan folder induk berkas terbuka di explorer.
    const parts = p.split('/').slice(0, -1)
    if (parts.length)
      setExpanded((s) => {
        const n = new Set(s)
        parts.forEach((_, i) => n.add(parts.slice(0, i + 1).join('/')))
        return n
      })
  }
  const tutupTab = (p: string) => {
    setTabs((t) => {
      const n = t.filter((x) => x !== p)
      if (file === p) setFile(n[n.length - 1] ?? null)
      return n
    })
  }

  useEffect(() => {
    if (follow && student.last_file && student.last_file !== file) buka(student.last_file, false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [follow, student.last_file])

  const fq = useQuery({
    queryKey: ['class-monitor-file', classId, student.user_id, file],
    queryFn: () => api.monitorClassFile(classId, student.user_id, file as string),
    enabled: !!file,
    refetchInterval: POLL_FILE_MS,
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])
  const d = fq.data
  const isNb = !!d && d.path.toLowerCase().endsWith('.ipynb')
  const running = student.devbox_state === 'running'

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-3 backdrop-blur-sm" onClick={onClose}>
      <div
        className={cn('flex h-full max-h-[94vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-lg border border-black shadow-2xl', VS.bg)}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Title bar */}
        <div className={cn('relative flex h-9 shrink-0 items-center px-3 text-[12px] text-[#cccccc]', VS.title)}>
          <IconCode className="h-4 w-4 text-[#3ea6ff]" />
          <div className="absolute left-1/2 w-[50%] -translate-x-1/2 truncate rounded bg-[#2b2b2b] px-3 py-1 text-center text-[12px] text-[#bbbbbb]">
            {className} — {student.name}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <label className="flex cursor-pointer items-center gap-1.5 select-none" title="Otomatis membuka berkas yang terakhir disimpan mahasiswa">
              <input type="checkbox" className="accent-[#3ea6ff]" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
              Ikuti mahasiswa
            </label>
            <button type="button" className="rounded p-1 hover:bg-white/10" onClick={onClose} aria-label="Tutup">
              <IconX className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          {/* Activity bar */}
          <div className={cn('flex w-12 shrink-0 flex-col items-center gap-4 pt-3 text-[#858585]', VS.bar)}>
            <IconFile className="h-6 w-6 text-white" />
            <IconTerminal className="h-6 w-6" />
            <IconEye className="h-6 w-6" />
          </div>
          {/* Explorer */}
          <div className={cn('flex w-64 shrink-0 flex-col overflow-hidden', VS.side)}>
            <div className="px-5 py-2.5 text-[11px] uppercase tracking-wide text-[#bbbbbb]">Explorer</div>
            <div className="px-2 pb-1 text-[11px] font-bold uppercase text-[#cccccc]">▾ {className}</div>
            <div className="min-h-0 flex-1 overflow-y-auto pb-3">
              <TreeDir
                classId={classId}
                uid={student.user_id}
                path=""
                depth={0}
                selected={file}
                onOpen={(p) => buka(p)}
                expanded={expanded}
                toggle={(p) =>
                  setExpanded((s) => {
                    const n = new Set(s)
                    n.has(p) ? n.delete(p) : n.add(p)
                    return n
                  })
                }
              />
            </div>
          </div>
          {/* Editor */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-9 shrink-0 overflow-x-auto bg-[#252526]">
              {tabs.map((t) => (
                <div
                  key={t}
                  className={cn(
                    'group flex shrink-0 cursor-pointer items-center gap-2 border-r border-[#252526] px-3 text-[13px]',
                    t === file ? 'bg-[#1e1e1e] text-white' : 'bg-[#2d2d2d] text-[#969696]',
                  )}
                  onClick={() => buka(t)}
                  title={t}
                >
                  <IconFile className="h-3.5 w-3.5 text-[#519aba]" />
                  {t.split('/').pop()}
                  <button
                    type="button"
                    className="rounded p-0.5 opacity-60 hover:bg-white/10 hover:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation()
                      tutupTab(t)
                    }}
                    aria-label="Tutup tab"
                  >
                    <IconX className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
            {file && (
              <div className="shrink-0 px-4 py-1 text-[12px] text-[#a9a9a9]">
                {className} › {file.split('/').join(' › ')}
              </div>
            )}
            <div className="relative min-h-0 flex-1">
              {!file ? (
                <div className="absolute inset-0 grid place-items-center text-center text-[13px] text-[#6b6b6b]">
                  <div>
                    <IconCode className="mx-auto mb-3 h-16 w-16 opacity-30" />
                    {student.exists ? 'Belum ada berkas yang disimpan. Pilih berkas di Explorer.' : 'Mahasiswa belum membuka ruang kerja kelas.'}
                  </div>
                </div>
              ) : fq.isLoading ? (
                <div className="absolute inset-0 grid place-items-center"><Spinner /></div>
              ) : fq.isError ? (
                <p className="p-6 text-[13px] text-rose-400">{errText(fq.error, 'Gagal membuka berkas.')}</p>
              ) : d?.content == null ? (
                <p className="p-6 text-[13px] text-[#a9a9a9]">
                  {d?.reason === 'too_large'
                    ? 'Berkas terlalu besar untuk ditampilkan (maks 2 MB).'
                    : 'Berkas biner tidak dapat ditampilkan.'}
                </p>
              ) : isNb ? (
                <div className="absolute inset-0 overflow-auto p-4">
                  <NotebookPreview content={d.content} />
                </div>
              ) : (
                <div className="absolute inset-0">
                  <CodeEditor
                    value={d.content}
                    onChange={() => {}}
                    language={d.language}
                    height="100%"
                    readOnly
                    lint={false}
                    summaryMode="hidden"
                  />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Status bar */}
        <div className="flex h-6 shrink-0 items-center gap-4 bg-[#007acc] px-3 text-[12px] text-white">
          <span className="flex items-center gap-1.5">
            <span className={cn('h-2 w-2 rounded-full', running ? 'bg-emerald-300' : 'bg-slate-300')} />
            {running ? 'Devbox menyala' : 'Devbox mati'}
          </span>
          <span>Baca-saja</span>
          {follow && <span>● Mengikuti mahasiswa</span>}
          <span className="ml-auto">
            {d ? `disimpan ${ago(d.modified)} · ${formatBytes(d.size)} · ${LANG_LABEL[d.language] ?? d.language}` : `${student.file_count} berkas`}
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}
