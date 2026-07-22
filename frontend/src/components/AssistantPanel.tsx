// Panel asisten AI notebook (chat ala Copilot) — tampil di sisi kanan notebook.
// Streaming jawaban via SSE, render markdown aman, dan tombol "Sisipkan ke sel"
// untuk tiap blok kode. Riwayat percakapan disimpan per-user di memori modul
// supaya tidak hilang saat panel diciutkan/dilebarkan.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import { fileToChatImageDataUrl } from '../lib/avatar'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import { renderMarkdown } from '../lib/markdown'
import type { AssistantMessage, AssistantStatus } from '../lib/types'
import {
  IconCheck,
  IconChevron,
  IconCode,
  IconImage,
  IconRefresh,
  IconSend,
  IconSparkles,
  IconStop,
  IconX,
} from './icons'

// ---- Store + STREAM asisten di level MODUL (bertahan lintas navigasi) ----
// Riwayat + eksekusi stream disimpan di sini (BUKAN di komponen) supaya respons AI
// TETAP BERJALAN saat user pindah menu / panel diciutkan. Komponen hanya mirror +
// berlangganan perubahan; saat kembali, state terkini (termasuk stream berjalan)
// langsung tampil.
const chatStore = new Map<number, AssistantMessage[]>()
const chatStreaming = new Map<number, boolean>()
const chatError = new Map<number, string | null>()
const chatAbort = new Map<number, AbortController>()
const chatListeners = new Map<number, Set<() => void>>()

function chatSubscribe(uid: number, fn: () => void): () => void {
  let set = chatListeners.get(uid)
  if (!set) {
    set = new Set()
    chatListeners.set(uid, set)
  }
  set.add(fn)
  return () => {
    set!.delete(fn)
  }
}
function chatEmit(uid: number): void {
  chatListeners.get(uid)?.forEach((fn) => fn())
}

// Jalankan 1 permintaan asisten (streaming) di level modul. Aman dipanggil lalu
// "ditinggal" -> tidak terikat siklus hidup komponen (tetap jalan saat pindah menu).
async function runAssistant(
  uid: number,
  history: AssistantMessage[],
  context: string,
  pythonVersion?: string,
): Promise<void> {
  if (chatStreaming.get(uid)) return
  chatStore.set(uid, [...history, { role: 'assistant', content: '' }])
  chatStreaming.set(uid, true)
  chatError.set(uid, null)
  chatEmit(uid)
  const ctrl = new AbortController()
  chatAbort.set(uid, ctrl)
  const onDelta = (t: string): void => {
    const ms = chatStore.get(uid) ?? []
    const copy = ms.slice()
    const last = copy[copy.length - 1]
    if (last && last.role === 'assistant') {
      copy[copy.length - 1] = { ...last, content: last.content + t }
    }
    chatStore.set(uid, copy)
    chatEmit(uid)
  }
  try {
    await api.assistantChatStream(
      {
        messages: history,
        notebook_context: context,
        python_version: pythonVersion || undefined,
      },
      onDelta,
      ctrl.signal,
    )
  } catch (e) {
    const err = e as Error
    if (err.name !== 'AbortError') {
      chatError.set(uid, err.message || 'Gagal menghubungi asisten.')
    }
  } finally {
    chatStreaming.set(uid, false)
    chatAbort.delete(uid)
    chatEmit(uid)
  }
}
function stopAssistant(uid: number): void {
  chatAbort.get(uid)?.abort()
}
function clearAssistantChat(uid: number): void {
  chatAbort.get(uid)?.abort()
  chatStore.set(uid, [])
  chatError.set(uid, null)
  chatEmit(uid)
}

type Segment = { type: 'text' | 'code'; text: string; lang?: string }

// Pisahkan teks markdown menjadi segmen teks & blok kode berpagar (```).
function splitSegments(src: string): Segment[] {
  const out: Segment[] = []
  const re = /```([\w+-]*)\n?([\s\S]*?)```/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) out.push({ type: 'text', text: src.slice(last, m.index) })
    out.push({ type: 'code', lang: m[1] || '', text: m[2].replace(/\n$/, '') })
    last = re.lastIndex
  }
  if (last < src.length) out.push({ type: 'text', text: src.slice(last) })
  return out
}

const SUGGESTIONS = [
  'Jelaskan kode di notebook ini',
  'Perbaiki error pada kode saya',
  'Contoh training model sederhana di GPU',
]

const MAX_IMAGES = 4

export default function AssistantPanel({
  onCollapse,
  getContext,
  onInsertCode,
  onApplyCode,
  pythonVersion,
}: {
  onCollapse: () => void
  getContext: () => string
  onInsertCode: (code: string) => void
  onApplyCode: (code: string) => void
  // Versi Python sesi notebook -> asisten tahu library image mana yang terpasang.
  pythonVersion?: string
}) {
  const { user } = useAuth()
  const uid = user?.id ?? 0

  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [messages, setMessages] = useState<AssistantMessage[]>(() => chatStore.get(uid) ?? [])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState<boolean>(() => !!chatStreaming.get(uid))
  const [error, setError] = useState<string | null>(() => chatError.get(uid) ?? null)
  const [pendingImages, setPendingImages] = useState<string[]>([])
  const [dragOver, setDragOver] = useState(false)

  const pendingImagesRef = useRef<string[]>(pendingImages)
  pendingImagesRef.current = pendingImages
  const scrollRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Ambil status (aktif/terkonfigurasi) sekali saat mount.
  useEffect(() => {
    let alive = true
    api
      .assistantStatus()
      .then((s) => alive && setStatus(s))
      .catch(() => alive && setStatus(null))
    return () => {
      alive = false
    }
  }, [])

  // Berlangganan store asisten (module-level). Store MENJALANKAN stream secara
  // mandiri -> respons AI TETAP berjalan walau panel di-unmount (pindah menu /
  // diciutkan). Komponen hanya mirror state terkini. TIDAK abort saat unmount.
  useEffect(() => {
    const sync = () => {
      setMessages(chatStore.get(uid) ?? [])
      setStreaming(!!chatStreaming.get(uid))
      setError(chatError.get(uid) ?? null)
    }
    sync()
    return chatSubscribe(uid, sync)
  }, [uid])

  // Auto-scroll ke bawah saat pesan bertambah.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  const send = useCallback(
    (text: string) => {
      const content = text.trim()
      const imgs = pendingImagesRef.current
      if ((!content && imgs.length === 0) || chatStreaming.get(uid)) return
      const userMsg: AssistantMessage =
        imgs.length > 0 ? { role: 'user', content, images: imgs } : { role: 'user', content }
      const history: AssistantMessage[] = [...(chatStore.get(uid) ?? []), userMsg]
      setInput('')
      setPendingImages([])
      // Stream dijalankan di level MODUL -> TETAP berjalan walau user pindah menu.
      void runAssistant(uid, history, getContext(), pythonVersion)
    },
    [uid, getContext, pythonVersion],
  )

  const stop = useCallback(() => stopAssistant(uid), [uid])

  const addImages = useCallback(async (files: File[]) => {
    const imgs = files.filter((f) => f.type.startsWith('image/'))
    if (imgs.length === 0) return
    setError(null)
    const room = MAX_IMAGES - pendingImagesRef.current.length
    if (room <= 0) {
      setError(`Maksimal ${MAX_IMAGES} gambar per pesan.`)
      return
    }
    try {
      const urls = await Promise.all(
        imgs.slice(0, room).map((f) => fileToChatImageDataUrl(f)),
      )
      setPendingImages((prev) => [...prev, ...urls].slice(0, MAX_IMAGES))
    } catch (e) {
      setError((e as Error).message || 'Gagal memuat gambar.')
    }
  }, [])

  const clearChat = useCallback(() => clearAssistantChat(uid), [uid])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send(input)
    }
  }

  const configured = status?.configured ?? false
  const visionOK = !!status?.vision_model

  // Tempel gambar dari clipboard (Ctrl+V) langsung di kotak pesan.
  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!visionOK) return
    const files = Array.from(e.clipboardData.items)
      .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
      .map((it) => it.getAsFile())
      .filter((f): f is File => !!f)
    if (files.length > 0) {
      e.preventDefault()
      void addImages(files)
    }
  }
  // Seret & lepas gambar ke panel.
  const onDragOver = (e: React.DragEvent) => {
    if (!visionOK || !Array.from(e.dataTransfer.types).includes('Files')) return
    e.preventDefault()
    setDragOver(true)
  }
  const onDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false)
  }
  const onDrop = (e: React.DragEvent) => {
    if (!visionOK) return
    e.preventDefault()
    setDragOver(false)
    void addImages(Array.from(e.dataTransfer.files ?? []))
  }

  return (
    <div
      className="relative flex h-full flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {dragOver && (
        <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center rounded-xl border-2 border-dashed border-brand-400 bg-brand-50/85">
          <div className="flex flex-col items-center gap-1.5 text-brand-700">
            <IconImage className="h-8 w-8" />
            <span className="text-sm font-semibold">Lepas gambar untuk dilampirkan</span>
          </div>
        </div>
      )}
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50/80 px-3 py-2">
        <IconSparkles className="h-4 w-4 text-brand-600" />
        <span className="text-sm font-semibold text-slate-800">Asisten AI</span>
        <span
          title={
            configured
              ? `${status?.provider} · ${status?.model}`
              : 'Belum dikonfigurasi — jawaban memakai mode contoh. Isi ASSISTANT_API_KEY di backend/.env.'
          }
          className={cn(
            'badge text-[10px]',
            configured ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700',
          )}
        >
          {configured ? status?.provider : 'mode contoh'}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={clearChat}
            disabled={messages.length === 0}
            title="Bersihkan percakapan"
            className="rounded-md p-1 text-slate-400 transition hover:bg-slate-200/70 hover:text-slate-600 disabled:opacity-40"
          >
            <IconRefresh className="h-4 w-4" />
          </button>
          <button
            onClick={onCollapse}
            title="Ciutkan panel"
            className="rounded-md p-1 text-slate-400 transition hover:bg-slate-200/70 hover:text-slate-600"
          >
            <IconChevron className="h-4 w-4 -rotate-90" />
          </button>
        </div>
      </div>

      {/* Pesan */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 ? (
          <div className="space-y-3 pt-2 text-center">
            <IconSparkles className="mx-auto h-8 w-8 text-brand-300" />
            <p className="text-sm font-medium text-slate-600">Tanya apa saja soal kodemu</p>
            <p className="text-xs text-slate-400">
              Asisten melihat isi notebook untuk memberi jawaban yang relevan.
            </p>
            {visionOK && (
              <p className="text-xs text-slate-400">
                Bisa lampirkan gambar (tombol gambar, tempel, atau seret) — mis. plot, pesan
                error, atau diagram.
              </p>
            )}
            <div className="flex flex-col gap-1.5 pt-1">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => void send(s)}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-left text-xs text-slate-600 transition hover:border-brand-300 hover:bg-brand-50/50 hover:text-brand-700"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <MessageBubble
              key={i}
              message={m}
              streaming={streaming && i === messages.length - 1 && m.role === 'assistant'}
              onInsertCode={onInsertCode}
              onApplyCode={onApplyCode}
            />
          ))
        )}
        {error && (
          <div className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-inset ring-rose-600/20">
            {error}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 p-2">
        {pendingImages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {pendingImages.map((src, i) => (
              <div key={i} className="relative">
                <img
                  src={src}
                  alt={`lampiran ${i + 1}`}
                  className="h-14 w-14 rounded-lg object-cover ring-1 ring-slate-200"
                />
                <button
                  onClick={() => setPendingImages((p) => p.filter((_, j) => j !== i))}
                  title="Hapus gambar"
                  className="absolute -right-1.5 -top-1.5 rounded-full bg-slate-800 p-0.5 text-white shadow transition hover:bg-slate-700"
                >
                  <IconX className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-slate-200 bg-white px-2 py-1.5 focus-within:border-brand-400 focus-within:ring-1 focus-within:ring-brand-200">
          {visionOK && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => {
                  void addImages(Array.from(e.target.files ?? []))
                  e.target.value = ''
                }}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                title="Lampirkan gambar (AI bisa melihatnya)"
                className="shrink-0 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-brand-600"
              >
                <IconImage className="h-4 w-4" />
              </button>
            </>
          )}
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            rows={1}
            placeholder="Tulis pesan… (Enter kirim, Shift+Enter baris baru)"
            className="max-h-32 min-h-[1.5rem] flex-1 resize-none bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400"
          />
          {streaming ? (
            <button
              onClick={stop}
              title="Hentikan"
              className="shrink-0 rounded-lg bg-rose-100 p-1.5 text-rose-600 transition hover:bg-rose-200"
            >
              <IconStop className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={() => void send(input)}
              disabled={!input.trim()}
              title="Kirim"
              className="shrink-0 rounded-lg bg-brand-600 p-1.5 text-white transition hover:bg-brand-500 disabled:opacity-40"
            >
              <IconSend className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------- gelembung pesan
function MessageBubble({
  message,
  streaming,
  onInsertCode,
  onApplyCode,
}: {
  message: AssistantMessage
  streaming: boolean
  onInsertCode: (code: string) => void
  onApplyCode: (code: string) => void
}) {
  const isUser = message.role === 'user'
  if (isUser) {
    return (
      <div className="flex flex-col items-end gap-1.5">
        {message.images && message.images.length > 0 && (
          <div className="flex max-w-[85%] flex-wrap justify-end gap-1.5">
            {message.images.map((src, i) => (
              <img
                key={i}
                src={src}
                alt={`lampiran ${i + 1}`}
                className="max-h-40 rounded-xl ring-1 ring-slate-200"
              />
            ))}
          </div>
        )}
        {message.content && (
          <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-brand-600 px-3 py-2 text-sm text-white">
            {message.content}
          </div>
        )}
      </div>
    )
  }
  const segments = splitSegments(message.content)
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-full space-y-2">
        {message.content.trim() === '' && streaming ? (
          <div className="flex items-center gap-1.5 px-1 text-slate-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400 [animation-delay:150ms]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400 [animation-delay:300ms]" />
          </div>
        ) : (
          segments.map((seg, i) =>
            seg.type === 'code' ? (
              <CodeBlock
                key={i}
                code={seg.text}
                onInsert={() => onInsertCode(seg.text)}
                onApply={() => onApplyCode(seg.text)}
              />
            ) : (
              <div
                key={i}
                className="assistant-md text-sm leading-relaxed text-slate-700"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(seg.text) }}
              />
            ),
          )
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------- blok kode
function CodeBlock({
  code,
  onInsert,
  onApply,
}: {
  code: string
  onInsert: () => void
  onApply: () => void
}) {
  const [done, setDone] = useState<'' | 'apply' | 'insert'>('')
  const flash = (which: 'apply' | 'insert') => {
    setDone(which)
    window.setTimeout(() => setDone(''), 1500)
  }
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-900">
      <div className="flex items-center justify-between border-b border-white/10 px-2 py-1">
        <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">python</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => {
              onApply()
              flash('apply')
            }}
            title="Timpa isi sel yang sedang aktif dengan kode ini"
            className="inline-flex items-center gap-1 rounded bg-brand-600/80 px-1.5 py-0.5 text-[11px] font-medium text-white transition hover:bg-brand-500"
          >
            {done === 'apply' ? (
              <IconCheck className="h-3 w-3 text-emerald-300" />
            ) : (
              <IconSparkles className="h-3 w-3" />
            )}
            {done === 'apply' ? 'Diterapkan' : 'Terapkan'}
          </button>
          <button
            onClick={() => {
              onInsert()
              flash('insert')
            }}
            title="Sisipkan sebagai sel baru di bawah"
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
          >
            {done === 'insert' ? (
              <IconCheck className="h-3 w-3 text-emerald-400" />
            ) : (
              <IconCode className="h-3 w-3" />
            )}
            {done === 'insert' ? 'Disisipkan' : 'Sel baru'}
          </button>
        </div>
      </div>
      <pre className="overflow-x-auto px-3 py-2 text-xs leading-relaxed text-slate-100">
        <code>{code}</code>
      </pre>
    </div>
  )
}
