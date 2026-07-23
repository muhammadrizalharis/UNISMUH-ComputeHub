// Galeri Template Notebook — contoh siap-jalan (Whisper, OCR, IndoBERT, YOLO,
// forecasting, statistik). Klik kartu -> /submit/notebook?template=<id> dan sel
// template langsung dimuat ke editor interaktif (parse .ipynb di klien).
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { IconNotebook, IconSparkles } from '../components/icons'

type TemplateMeta = {
  id: string
  judul: string
  desc: string
  tags: string[]
  level: string
  gradien: string
  emoji: string
}

export default function Templates() {
  const [items, setItems] = useState<TemplateMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/templates/index.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: TemplateMeta[]) => setItems(data))
      .catch(() => setError('Gagal memuat katalog template.'))
  }, [])

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-fuchsia-500 to-violet-600 text-white shadow">
          <IconSparkles className="h-6 w-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-bold leading-tight text-slate-800">
            Galeri Template Notebook
          </h1>
          <p className="text-sm text-slate-500">
            Contoh siap-jalan: klik, buka, langsung Run — tanpa setup. Semua model &
            library sudah disediakan server.
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/15">
          {error}
        </div>
      )}

      {!items && !error && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card h-52 animate-pulse bg-slate-100" />
          ))}
        </div>
      )}

      {items && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((t) => (
            <Link
              key={t.id}
              to={`/submit/notebook?template=${encodeURIComponent(t.id)}`}
              className="card group flex flex-col overflow-hidden transition hover:-translate-y-0.5 hover:shadow-lg"
            >
              <div
                className={`flex items-center justify-between bg-gradient-to-br ${t.gradien} px-5 py-4`}
              >
                <span className="text-3xl drop-shadow" aria-hidden>
                  {t.emoji}
                </span>
                <span className="rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">
                  {t.level}
                </span>
              </div>
              <div className="flex flex-1 flex-col gap-2 p-5">
                <h2 className="text-sm font-bold text-slate-800 group-hover:text-brand-700">
                  {t.judul}
                </h2>
                <p className="flex-1 text-[13px] leading-relaxed text-slate-500">{t.desc}</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  {t.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
                <span className="mt-2 inline-flex items-center gap-1.5 text-[13px] font-semibold text-brand-600 group-hover:underline">
                  <IconNotebook className="h-4 w-4" /> Buka di notebook →
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}

      <p className="text-xs text-slate-400">
        Semua template <i>self-contained</i> (punya data contoh sendiri) — tinggal ganti
        dengan data/filemu. Model besar (Whisper, IndoBERT, YOLO) dimuat dari folder
        bersama server tanpa perlu download.
      </p>
    </div>
  )
}
