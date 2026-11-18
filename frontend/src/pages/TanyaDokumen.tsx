// Tanya Dokumen — pustaka dokumen pribadi (disimpan di /persist/Dokumen-AI milik
// pengguna) + chat yang menjawab HANYA dari isi dokumen itu, lengkap dengan kutipan
// [D1], [D2], ... Indeks dibangun di server (Qdrant) dan terpisah per pengguna.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatBytes, timeAgo } from '../lib/format'
import { renderMarkdown } from '../lib/markdown'
import { registerLogoutCleanup } from '../lib/notebookDrafts'
import type { LibraryDoc, LibrarySource } from '../lib/types'
import { useStickyScroll } from '../lib/useStickyScroll'
import Spinner from '../components/Spinner'
import {
  IconDownload,
  IconFile,
  IconRefresh,
  IconSend,
  IconSparkles,
  IconTrash,
  IconUpload,
  IconX,
} from '../components/icons'

type Msg = {
  role: 'user' | 'assistant'
  content: string
  sources?: LibrarySource[]
  status?: string
}

type UploadItem = {
  key: string
  name: string
  progress: number
  error?: string
}

const ACCEPT =
  '.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.odt,.ods,.odp,.rtf,.txt,.md,.csv,.tsv,.json,.html,.htm,.tex'
const INPUT_MAX_HEIGHT = 200

const STATUS_META: Record<LibraryDoc['status'], { label: string; cls: string }> = {
  antre: { label: 'Antre', cls: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300' },
  proses: { label: 'Diproses…', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300' },
  siap: { label: 'Siap', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300' },
  gagal: { label: 'Gagal', cls: 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300' },
}

const SARAN = [
  'Ringkas isi dokumen saya dalam 5 poin.',
  'Apa metode penelitian yang dipakai?',
  'Apa kesimpulan utamanya?',
]

// Riwayat chat per-USER di memori modul: bertahan saat pindah menu, dibersihkan saat logout.
const chatStore = new Map<number, Msg[]>()
registerLogoutCleanup(() => chatStore.clear())

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError || e instanceof Error ? e.message || fallback : fallback
}

export default function TanyaDokumen() {
  const { user } = useAuth()
  const uid = user?.id ?? 0
  const qc = useQueryClient()

  const listQ = useQuery({
    queryKey: ['doc-library'],
    queryFn: () => api.libraryList(),
    refetchInterval: (q) =>
      q.state.data?.docs.some((d) => d.status === 'antre' || d.status === 'proses') ? 3000 : false,
  })
  const docs = useMemo(() => listQ.data?.docs ?? [], [listQ.data])
  const enabled = listQ.data?.enabled ?? true
  const refresh = useCallback(() => qc.invalidateQueries({ queryKey: ['doc-library'] }), [qc])

  // ----------------------------------------------------------------- unggah
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const uploadingRef = useRef(false)
  const queueRef = useRef<{ key: string; file: File }[]>([])

  const pump = useCallback(async () => {
    if (uploadingRef.current) return
    uploadingRef.current = true
    try {
      for (;;) {
        const next = queueRef.current.shift()
        if (!next) break
        try {
          await api.libraryUpload(next.file, (p) =>
            setUploads((cur) => cur.map((u) => (u.key === next.key ? { ...u, progress: p } : u))),
          )
          setUploads((cur) => cur.filter((u) => u.key !== next.key))
          void refresh()
        } catch (e) {
          setUploads((cur) =>
            cur.map((u) => (u.key === next.key ? { ...u, error: errText(e, 'Gagal mengunggah.') } : u)),
          )
        }
      }
    } finally {
      uploadingRef.current = false
    }
  }, [refresh])

  const addFiles = useCallback(
    (files: File[]) => {
      if (!files.length) return
      const items = files.map((f, i) => ({ key: `${Date.now()}-${i}-${f.name}`, file: f }))
      queueRef.current.push(...items)
      setUploads((cur) => [...cur, ...items.map((x) => ({ key: x.key, name: x.file.name, progress: 0 }))])
      void pump()
    },
    [pump],
  )

  // ----------------------------------------------------------- aksi dokumen
  const [actionError, setActionError] = useState<string | null>(null)
  const delMut = useMutation({
    mutationFn: (id: number) => api.libraryDelete(id),
    onSuccess: (_d, id) => {
      setSelected((cur) => cur.filter((x) => x !== id))
      void refresh()
    },
    onError: (e) => setActionError(errText(e, 'Gagal menghapus dokumen.')),
  })
  const reMut = useMutation({
    mutationFn: (id: number) => api.libraryReindex(id),
    onSuccess: () => void refresh(),
    onError: (e) => setActionError(errText(e, 'Gagal memproses ulang.')),
  })
  const download = async (d: LibraryDoc) => {
    try {
      const blob = await api.libraryDownload(d.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = d.name
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (e) {
      setActionError(errText(e, 'Gagal mengunduh.'))
    }
  }

  // Pilih dokumen tertentu (kosong = semua dokumen yang siap).
  const [selected, setSelected] = useState<number[]>([])
  const readyCount = docs.filter((d) => d.status === 'siap').length
  useEffect(() => {
    const ok = new Set(docs.filter((d) => d.status === 'siap').map((d) => d.id))
    setSelected((cur) => (cur.every((x) => ok.has(x)) ? cur : cur.filter((x) => ok.has(x))))
  }, [docs])
  const toggle = (id: number) =>
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))

  // ------------------------------------------------------------------- chat
  const [msgs, setMsgs] = useState<Msg[]>(() => chatStore.get(uid) ?? [])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const { ref: boxRef, onScroll, diAtas, keBawah } = useStickyScroll<HTMLDivElement>(msgs)

  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, INPUT_MAX_HEIGHT)}px`
  }, [input])
  useEffect(() => {
    chatStore.set(uid, msgs)
  }, [uid, msgs])
  useEffect(() => () => abortRef.current?.abort(), [])

  const patchLast = (fn: (m: Msg) => Msg) =>
    setMsgs((cur) => {
      const next = [...cur]
      next[next.length - 1] = fn(next[next.length - 1])
      return next
    })

  const send = useCallback(
    async (teks: string) => {
      const q = teks.trim()
      if (!q || busy) return
      setInput('')
      setBusy(true)
      keBawah()
      const riwayat: Msg[] = [...msgs, { role: 'user', content: q }]
      setMsgs([...riwayat, { role: 'assistant', content: '' }])
      const ac = new AbortController()
      abortRef.current = ac
      try {
        await api.libraryChatStream(
          {
            messages: riwayat.slice(-20).map((m) => ({ role: m.role, content: m.content })),
            doc_ids: selected.length ? selected : null,
          },
          (delta) => patchLast((m) => ({ ...m, content: m.content + delta, status: undefined })),
          ac.signal,
          (ev) =>
            patchLast((m) => ({
              ...m,
              ...(ev.status !== undefined ? { status: ev.status } : {}),
              ...(ev.doc_sources !== undefined ? { sources: ev.doc_sources } : {}),
            })),
        )
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          patchLast((m) =>
            m.content ? m : { ...m, content: `⚠️ ${errText(e, 'Gagal menghubungi asisten.')}` },
          )
        }
      } finally {
        patchLast((m) => ({ ...m, status: undefined }))
        setBusy(false)
      }
    },
    [busy, msgs, selected, keBawah],
  )

  const stop = () => abortRef.current?.abort()

  // ------------------------------------------------------------------- render
  if (listQ.isLoading) {
    return (
      <div className="grid place-items-center py-20">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-600 text-white shadow">
          <IconFile className="h-6 w-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-bold leading-tight text-slate-800 dark:text-slate-100">
            Tanya Dokumen
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Unggah skripsi, jurnal, modul, atau catatan Anda, lalu tanyakan isinya. Jawaban
            hanya diambil dari dokumen Anda sendiri dan menyertakan sumber [D1], [D2], …
          </p>
        </div>
      </div>

      {listQ.isError && (
        <div className="card p-4 text-sm text-rose-600">
          {errText(listQ.error, 'Gagal memuat daftar dokumen.')}
        </div>
      )}

      {!enabled ? (
        <div className="card p-6 text-sm text-slate-600 dark:text-slate-300">
          Fitur Tanya Dokumen belum diaktifkan di server ini. Hubungi admin bila Anda
          membutuhkannya.
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          {/* ------------------------------------------------ pustaka dokumen */}
          <section className="card flex min-h-0 flex-col overflow-hidden">
            <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-700/60">
              <div className="min-w-0">
                <h2 className="text-sm font-bold text-slate-800 dark:text-slate-100">Dokumen Saya</h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Tersimpan di folder <code>/persist/{listQ.data?.folder ?? 'Dokumen-AI'}</code> —
                  memakai kuota penyimpanan Anda.
                </p>
              </div>
              <button
                type="button"
                onClick={() => void refresh()}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
                title="Muat ulang daftar"
              >
                <IconRefresh className="h-4 w-4" />
              </button>
            </div>

            <div
              onDragOver={(e) => {
                if (Array.from(e.dataTransfer.types).includes('Files')) {
                  e.preventDefault()
                  setDragOver(true)
                }
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                addFiles(Array.from(e.dataTransfer.files))
              }}
              onClick={() => fileRef.current?.click()}
              className={cn(
                'm-3 cursor-pointer rounded-xl border-2 border-dashed px-4 py-5 text-center text-sm transition',
                dragOver
                  ? 'border-brand-400 bg-brand-50 dark:bg-brand-500/10'
                  : 'border-slate-200 hover:border-brand-300 hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800',
              )}
            >
              <IconUpload className="mx-auto mb-1.5 h-6 w-6 text-slate-400" />
              <div className="font-medium text-slate-700 dark:text-slate-200">
                Seret berkas ke sini atau klik untuk memilih
              </div>
              <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                PDF, Word, PowerPoint, Excel, OpenDocument, TXT/MD/CSV/JSON/HTML/TeX
              </div>
              <input
                ref={fileRef}
                type="file"
                multiple
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => {
                  addFiles(Array.from(e.target.files ?? []))
                  e.target.value = ''
                }}
              />
            </div>

            {uploads.length > 0 && (
              <ul className="space-y-1.5 px-3 pb-2">
                {uploads.map((u) => (
                  <li key={u.key} className="rounded-lg bg-slate-50 px-3 py-2 text-xs dark:bg-slate-800">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium text-slate-700 dark:text-slate-200">
                        {u.name}
                      </span>
                      {u.error ? (
                        <button
                          type="button"
                          onClick={() => setUploads((cur) => cur.filter((x) => x.key !== u.key))}
                          className="text-slate-400 hover:text-rose-600"
                          title="Tutup"
                        >
                          <IconX className="h-3.5 w-3.5" />
                        </button>
                      ) : (
                        <span className="tabular-nums text-slate-500">{Math.round(u.progress * 100)}%</span>
                      )}
                    </div>
                    {u.error ? (
                      <div className="mt-1 text-rose-600">{u.error}</div>
                    ) : (
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                        <div
                          className="h-full rounded-full bg-brand-500 transition-all"
                          style={{ width: `${Math.max(3, u.progress * 100)}%` }}
                        />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {actionError && (
              <div className="mx-3 mb-2 flex items-start gap-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-500/15 dark:text-rose-300">
                <span className="flex-1">{actionError}</span>
                <button type="button" onClick={() => setActionError(null)}>
                  <IconX className="h-3.5 w-3.5" />
                </button>
              </div>
            )}

            <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3 lg:max-h-[60vh]">
              {docs.length === 0 ? (
                <p className="px-1 py-6 text-center text-sm text-slate-500 dark:text-slate-400">
                  Belum ada dokumen. Unggah satu untuk mulai bertanya.
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {docs.map((d) => {
                    const meta = STATUS_META[d.status]
                    const ready = d.status === 'siap'
                    return (
                      <li
                        key={d.id}
                        className={cn(
                          'rounded-lg px-3 py-2 ring-1 ring-inset',
                          selected.includes(d.id)
                            ? 'bg-brand-50 ring-brand-200 dark:bg-brand-500/10 dark:ring-brand-500/40'
                            : 'ring-slate-100 dark:ring-slate-700/60',
                        )}
                      >
                        <div className="flex items-start gap-2">
                          <input
                            type="checkbox"
                            className="mt-1"
                            checked={selected.includes(d.id)}
                            disabled={!ready}
                            onChange={() => toggle(d.id)}
                            title={ready ? 'Batasi pertanyaan ke dokumen ini' : 'Dokumen belum siap'}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100" title={d.name}>
                              {d.name}
                            </div>
                            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
                              <span className={cn('rounded-full px-2 py-0.5 font-medium', meta.cls)}>
                                {meta.label}
                              </span>
                              <span>{formatBytes(d.size_bytes)}</span>
                              {ready && <span>{d.chunks} bagian</span>}
                              {ready && d.truncated && (
                                <span className="text-amber-600" title="Dokumen sangat panjang; hanya bagian awal yang diindeks.">
                                  sebagian
                                </span>
                              )}
                              <span>{timeAgo(d.indexed_at ?? d.created_at)}</span>
                            </div>
                            {d.status === 'gagal' && d.error && (
                              <div className="mt-1 text-xs text-rose-600">{d.error}</div>
                            )}
                          </div>
                          <div className="flex shrink-0 items-center gap-0.5">
                            <button
                              type="button"
                              onClick={() => void download(d)}
                              className="grid h-7 w-7 place-items-center rounded-md text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
                              title="Unduh berkas asli"
                            >
                              <IconDownload className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => reMut.mutate(d.id)}
                              disabled={d.status === 'antre' || d.status === 'proses'}
                              className="grid h-7 w-7 place-items-center rounded-md text-slate-500 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-slate-700"
                              title="Proses ulang"
                            >
                              <IconRefresh className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (
                                  window.confirm(
                                    `Hapus “${d.name}”? Berkas dipindah ke Tempat Sampah (bisa dipulihkan 7 hari).`,
                                  )
                                )
                                  delMut.mutate(d.id)
                              }}
                              className="grid h-7 w-7 place-items-center rounded-md text-slate-500 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-500/15"
                              title="Hapus"
                            >
                              <IconTrash className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </section>

          {/* ------------------------------------------------------------ chat */}
          <section className="card flex min-h-[28rem] flex-col overflow-hidden">
            <div className="flex items-center gap-2 border-b border-slate-100 bg-gradient-to-r from-violet-50 to-sky-50 px-4 py-3 dark:border-slate-700/60 dark:from-violet-500/15 dark:to-sky-500/15">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white">
                <IconSparkles className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-bold text-slate-800 dark:text-slate-100">Tanya isi dokumen</h2>
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                  {selected.length
                    ? `Hanya dari ${selected.length} dokumen yang dicentang`
                    : `Dari semua dokumen siap (${readyCount})`}
                </p>
              </div>
              {selected.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSelected([])}
                  className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-white/70 dark:hover:bg-slate-700"
                >
                  Semua dokumen
                </button>
              )}
              {msgs.length > 0 && !busy && (
                <button
                  type="button"
                  onClick={() => setMsgs([])}
                  className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-white/70 dark:hover:bg-slate-700"
                >
                  Percakapan baru
                </button>
              )}
            </div>

            {msgs.length === 0 ? (
              <div className="flex flex-1 flex-col justify-center gap-3 px-4 py-6">
                <p className="text-center text-sm text-slate-500 dark:text-slate-400">
                  {readyCount
                    ? 'Tanyakan apa saja tentang isi dokumen Anda.'
                    : 'Unggah dokumen dan tunggu statusnya “Siap” sebelum bertanya.'}
                </p>
                {readyCount > 0 && (
                  <div className="flex flex-wrap justify-center gap-2">
                    {SARAN.map((s) => (
                      <button
                        key={s}
                        onClick={() => void send(s)}
                        className="rounded-full bg-slate-100 px-3 py-1.5 text-xs text-slate-600 transition hover:bg-brand-50 hover:text-brand-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="relative min-h-0 flex-1">
                <div
                  ref={boxRef}
                  onScroll={onScroll}
                  className="max-h-[60vh] min-h-[18rem] space-y-3 overflow-y-auto overscroll-y-contain px-4 py-3 [overflow-anchor:none]"
                >
                  {msgs.map((m, i) => (
                    <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex flex-col items-start'}>
                      {m.role === 'user' ? (
                        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-brand-600 px-3 py-2 text-sm text-white">
                          {m.content}
                        </div>
                      ) : (
                        <>
                          <div
                            className="prose prose-sm max-w-[95%] rounded-2xl rounded-bl-sm bg-slate-50 px-3 py-2 text-sm text-slate-700 prose-code:text-[12px] dark:bg-slate-800 dark:prose-invert dark:text-slate-200"
                            dangerouslySetInnerHTML={{
                              __html: renderMarkdown(
                                m.content || (busy && i === msgs.length - 1 ? m.status ?? '…' : ''),
                              ),
                            }}
                          />
                          {m.sources && m.sources.length > 0 && (
                            <div className="mt-1.5 flex max-w-[95%] flex-wrap gap-1.5">
                              {m.sources.map((s) => (
                                <span
                                  key={s.n}
                                  className="inline-flex max-w-full items-center gap-1 rounded-full bg-violet-50 px-2 py-0.5 text-[11px] text-violet-700 ring-1 ring-inset ring-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/30"
                                  title={s.section ? `${s.name} › ${s.section}` : s.name}
                                >
                                  <b>D{s.n}</b>
                                  <span className="truncate">
                                    {s.name}
                                    {s.section ? ` › ${s.section}` : ''}
                                  </span>
                                </span>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
                {diAtas && (
                  <button
                    type="button"
                    onClick={keBawah}
                    className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-slate-900/85 px-3 py-1.5 text-xs font-medium text-white shadow-lg backdrop-blur transition hover:bg-slate-900"
                  >
                    ↓ Jawaban terbaru
                  </button>
                )}
              </div>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault()
                void send(input)
              }}
              className="border-t border-slate-100 px-3 py-2.5 dark:border-slate-700/60"
            >
              <div className="flex items-end gap-2">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      void send(input)
                    }
                  }}
                  rows={1}
                  placeholder={
                    readyCount
                      ? 'Tanyakan isi dokumen… (Enter kirim, Shift+Enter baris baru)'
                      : 'Belum ada dokumen yang siap'
                  }
                  disabled={busy || readyCount === 0}
                  style={{ maxHeight: INPUT_MAX_HEIGHT }}
                  className="min-w-0 flex-1 resize-none overflow-y-auto rounded-lg border-0 bg-slate-100 px-3 py-2 text-sm leading-5 text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-400 disabled:opacity-60 dark:bg-slate-800 dark:text-slate-200 dark:placeholder:text-slate-500"
                />
                {busy ? (
                  <button
                    type="button"
                    onClick={stop}
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-700 text-white transition hover:bg-slate-600"
                    title="Hentikan"
                  >
                    <IconX className="h-4 w-4" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim() || readyCount === 0}
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-600 text-white transition hover:bg-brand-500 disabled:opacity-40"
                    title="Kirim"
                  >
                    <IconSend className="h-4 w-4" />
                  </button>
                )}
              </div>
              <p className="mt-1.5 px-1 text-[11px] text-slate-400">
                Jawaban AI bisa keliru — cek kembali ke dokumen asli lewat sumber [D…].
              </p>
            </form>
          </section>
        </div>
      )}
    </div>
  )
}
