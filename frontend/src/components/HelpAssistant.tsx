// Asisten Panduan — chat kecil di halaman Bantuan, sandbox ketat ke topik cara
// pakai platform (backend /assistant/help: system prompt basis pengetahuan panduan
// + guardrail tolak di luar topik). Model sama dgn asisten coding (tak menambah VRAM).
// Mendukung SCREENSHOT: user bisa lampir/tempel/seret gambar layar yang membingungkan
// -> model vision menjelaskan layar apa itu, artinya, dan langkah berikutnya.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import { fileToChatImageDataUrl } from '../lib/avatar'
import { renderMarkdown } from '../lib/markdown'
import { IconImage, IconSend, IconSparkles, IconX } from './icons'

type Msg = { role: 'user' | 'assistant'; content: string; images?: string[] }

const MAX_IMAGES = 2

const SARAN = [
  'Bagaimana cara push ke GitHub?',
  'Berapa kuota GPU saya per hari?',
  'Cara pakai versi Python 3.13?',
  'File saya hilang setelah sesi berakhir — kenapa?',
]

export default function HelpAssistant() {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [pendingImages, setPendingImages] = useState<string[]>([])
  const boxRef = useRef<HTMLDivElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight })
  }, [msgs])
  useEffect(() => () => abortRef.current?.abort(), [])

  const addImages = useCallback(async (files: File[]) => {
    const imgs = files.filter((f) => f.type.startsWith('image/'))
    if (!imgs.length) return
    try {
      const urls = await Promise.all(imgs.slice(0, MAX_IMAGES).map((f) => fileToChatImageDataUrl(f)))
      setPendingImages((prev) => [...prev, ...urls].slice(0, MAX_IMAGES))
    } catch {
      /* gambar gagal dimuat -> abaikan */
    }
  }, [])

  const send = useCallback(
    async (teks: string) => {
      const q = teks.trim()
      const imgs = pendingImages
      if ((!q && imgs.length === 0) || busy) return
      setInput('')
      setPendingImages([])
      setBusy(true)
      const riwayat: Msg[] = [
        ...msgs,
        { role: 'user', content: q || 'Tolong jelaskan screenshot ini.', images: imgs },
      ]
      setMsgs([...riwayat, { role: 'assistant', content: '' }])
      const ac = new AbortController()
      abortRef.current = ac
      try {
        await api.helpChatStream(
          riwayat.map((m) => ({ role: m.role, content: m.content, images: m.images ?? [] })),
          (delta) =>
            setMsgs((cur) => {
              const next = [...cur]
              next[next.length - 1] = {
                role: 'assistant',
                content: next[next.length - 1].content + delta,
              }
              return next
            }),
          ac.signal,
        )
      } catch (e) {
        setMsgs((cur) => {
          const next = [...cur]
          const last = next[next.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            next[next.length - 1] = {
              role: 'assistant',
              content: `⚠️ ${(e as Error).message || 'Gagal menghubungi asisten.'}`,
            }
          }
          return next
        })
      } finally {
        setBusy(false)
      }
    },
    [busy, msgs, pendingImages],
  )

  return (
    <section className="card overflow-hidden">
      <div className="flex items-center gap-2 border-b border-slate-100 bg-gradient-to-r from-violet-50 to-sky-50 px-4 py-3">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white">
          <IconSparkles className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-slate-800">Tanya Asisten Panduan</h2>
          <p className="text-xs text-slate-500">
            Khusus soal cara pakai ComputeHub — bingung dengan suatu layar? Tempel
            screenshot-nya (Ctrl+V), aku jelaskan. Bantuan koding: Asisten AI di notebook.
          </p>
        </div>
      </div>

      {msgs.length === 0 ? (
        <div className="flex flex-wrap gap-2 px-4 py-3">
          {SARAN.map((s) => (
            <button
              key={s}
              onClick={() => void send(s)}
              className="rounded-full bg-slate-100 px-3 py-1.5 text-xs text-slate-600 transition hover:bg-brand-50 hover:text-brand-700"
            >
              {s}
            </button>
          ))}
        </div>
      ) : (
        <div ref={boxRef} className="max-h-80 space-y-3 overflow-y-auto px-4 py-3">
          {msgs.map((m, i) => (
            <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex'}>
              {m.role === 'user' ? (
                <div className="max-w-[85%] space-y-1.5 rounded-2xl rounded-br-sm bg-brand-600 px-3 py-2 text-sm text-white">
                  {m.images && m.images.length > 0 && (
                    <div className="flex gap-1.5">
                      {m.images.map((im, j) => (
                        <img key={j} src={im} alt="lampiran" className="h-16 w-16 rounded-lg object-cover ring-1 ring-white/30" />
                      ))}
                    </div>
                  )}
                  {m.content}
                </div>
              ) : (
                <div
                  className="prose prose-sm max-w-[92%] rounded-2xl rounded-bl-sm bg-slate-50 px-3 py-2 text-sm text-slate-700 prose-code:text-[12px]"
                  dangerouslySetInnerHTML={{
                    __html: renderMarkdown(m.content || (busy && i === msgs.length - 1 ? '…' : '')),
                  }}
                />
              )}
            </div>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void send(input)
        }}
        className="border-t border-slate-100 px-3 py-2.5"
        onDragOver={(e) => {
          if (Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault()
        }}
        onDrop={(e) => {
          e.preventDefault()
          void addImages(Array.from(e.dataTransfer.files))
        }}
      >
        {pendingImages.length > 0 && (
          <div className="mb-2 flex gap-2">
            {pendingImages.map((im, i) => (
              <span key={i} className="relative">
                <img src={im} alt="pratinjau" className="h-14 w-14 rounded-lg object-cover ring-1 ring-slate-200" />
                <button
                  type="button"
                  onClick={() => setPendingImages((prev) => prev.filter((_, j) => j !== i))}
                  className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-slate-700 text-white hover:bg-rose-600"
                  title="Hapus gambar"
                >
                  <IconX className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
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
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={busy || pendingImages.length >= MAX_IMAGES}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500 transition hover:bg-slate-200 hover:text-slate-700 disabled:opacity-40"
            title="Lampirkan screenshot (bisa juga tempel Ctrl+V atau seret ke sini)"
          >
            <IconImage className="h-4 w-4" />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={(e) => {
              const files = Array.from(e.clipboardData.items)
                .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
                .map((it) => it.getAsFile())
                .filter((f): f is File => !!f)
              if (files.length > 0) {
                e.preventDefault()
                void addImages(files)
              }
            }}
            placeholder="Tulis pertanyaan / tempel screenshot (Ctrl+V)…"
            disabled={busy}
            className="min-w-0 flex-1 rounded-lg border-0 bg-slate-100 px-3 py-2 text-sm text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-400 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={busy || (!input.trim() && pendingImages.length === 0)}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-600 text-white transition hover:bg-brand-500 disabled:opacity-40"
            title="Kirim"
          >
            <IconSend className="h-4 w-4" />
          </button>
        </div>
      </form>
    </section>
  )
}
