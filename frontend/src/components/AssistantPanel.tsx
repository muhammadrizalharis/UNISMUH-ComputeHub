// Panel asisten AI notebook (chat ala Copilot) — tampil di sisi kanan notebook.
// Streaming jawaban via SSE, render markdown aman, dan tombol "Sisipkan ke sel"
// untuk tiap blok kode. Riwayat percakapan disimpan per-user di memori modul
// supaya tidak hilang saat panel diciutkan/dilebarkan.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import { renderMarkdown } from '../lib/markdown'
import type { AssistantMessage, AssistantStatus } from '../lib/types'
import {
  IconCheck,
  IconChevron,
  IconCode,
  IconRefresh,
  IconSend,
  IconSparkles,
  IconStop,
} from './icons'

// Simpan percakapan per-user (tahan saat panel unmount karena diciutkan).
const chatStore = new Map<number, AssistantMessage[]>()

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

export default function AssistantPanel({
  onCollapse,
  getContext,
  onInsertCode,
  onApplyCode,
}: {
  onCollapse: () => void
  getContext: () => string
  onInsertCode: (code: string) => void
  onApplyCode: (code: string) => void
}) {
  const { user } = useAuth()
  const uid = user?.id ?? 0

  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [messages, setMessages] = useState<AssistantMessage[]>(() => chatStore.get(uid) ?? [])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const messagesRef = useRef<AssistantMessage[]>(messages)
  messagesRef.current = messages
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

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

  // Sinkronkan riwayat ke store per-user + auto-scroll ke bawah.
  useEffect(() => {
    chatStore.set(uid, messages)
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, uid])

  // Batalkan stream yang berjalan saat komponen dilepas.
  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const onDelta = useCallback((t: string) => {
    setMessages((ms) => {
      const copy = ms.slice()
      const last = copy[copy.length - 1]
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, content: last.content + t }
      }
      return copy
    })
  }, [])

  const send = useCallback(
    async (text: string) => {
      const content = text.trim()
      if (!content || streaming) return
      setError(null)
      const history: AssistantMessage[] = [...messagesRef.current, { role: 'user', content }]
      setMessages([...history, { role: 'assistant', content: '' }])
      setInput('')
      setStreaming(true)
      const ctrl = new AbortController()
      abortRef.current = ctrl
      try {
        await api.assistantChatStream(
          { messages: history, notebook_context: getContext() },
          onDelta,
          ctrl.signal,
        )
      } catch (e) {
        const err = e as Error
        if (err.name !== 'AbortError') {
          setError(err.message || 'Gagal menghubungi asisten.')
        }
      } finally {
        setStreaming(false)
        abortRef.current = null
      }
    },
    [streaming, getContext, onDelta],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const clearChat = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setError(null)
  }, [])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send(input)
    }
  }

  const configured = status?.configured ?? false

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
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
        <div className="flex items-end gap-2 rounded-xl border border-slate-200 bg-white px-2 py-1.5 focus-within:border-brand-400 focus-within:ring-1 focus-within:ring-brand-200">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
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
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-brand-600 px-3 py-2 text-sm text-white">
          {message.content}
        </div>
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
