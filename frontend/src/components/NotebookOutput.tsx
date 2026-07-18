// Komponen presentasi OUTPUT sel notebook (stream/hasil/gambar/HTML/error) —
// dipakai bersama oleh Notebook Interaktif (live) DAN NotebookPreview (baca .ipynb
// di detail job). Termasuk tombol Salin/Unduh ala VS Code + pemendekan teks panjang.
import { useState, type ReactNode } from 'react'

import { cn } from '../lib/format'
import { type CellOutput, stripAnsi } from '../lib/ipynb'

// Teks panjang dipangkas (20 baris awal + 20 baris akhir) dengan tombol "Tampilkan
// semua" -> kotak bergulir. Menjaga output ribuan baris tetap ringan di layar.
export function LongText({ text, className }: { text: string; className: string }) {
  const [expanded, setExpanded] = useState(false)
  const HEAD = 20
  const TAIL = 20
  const lines = text.split('\n')
  const long = lines.length > HEAD + TAIL + 10
  if (!long) return <pre className={className}>{text}</pre>
  if (expanded) {
    return (
      <div>
        <div className="mx-3 mt-1.5 mb-1 flex items-center gap-2">
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200 hover:bg-slate-200"
          >
            ▴ Tampilkan ringkas
          </button>
          <span className="text-xs text-slate-400">
            {lines.length.toLocaleString('id-ID')} baris · gulir di dalam kotak untuk lihat semua
          </span>
        </div>
        <pre className={cn(className, 'max-h-[70vh] overflow-auto rounded-md ring-1 ring-slate-200')}>
          {text}
        </pre>
      </div>
    )
  }
  const hidden = lines.length - HEAD - TAIL
  return (
    <div>
      <pre className={cn(className, 'pb-0')}>{lines.slice(0, HEAD).join('\n')}</pre>
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="mx-3 my-1.5 flex w-[calc(100%-1.5rem)] items-center justify-center gap-1.5 rounded-md bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 ring-1 ring-brand-200 transition hover:bg-brand-100"
      >
        ▾ Tampilkan semua {lines.length.toLocaleString('id-ID')} baris ·{' '}
        {hidden.toLocaleString('id-ID')} baris tengah disembunyikan
      </button>
      <pre className={cn(className, 'pt-0')}>{lines.slice(-TAIL).join('\n')}</pre>
    </div>
  )
}

export function OutputView({ out }: { out: CellOutput }) {
  let copyText: string | null = null
  let imgSrc: string | null = null
  let imgName = 'output.png'
  let body: ReactNode = null

  if (out.kind === 'stream') {
    copyText = out.text
    body = (
      <LongText
        text={out.text}
        className={cn(
          'overflow-x-auto whitespace-pre-wrap break-words px-3 py-1.5 font-mono text-xs',
          out.name === 'stderr' ? 'text-rose-600' : 'text-slate-700',
        )}
      />
    )
  } else if (out.kind === 'error') {
    const tb = out.traceback.length
      ? out.traceback.map(stripAnsi).join('\n')
      : `${out.ename}: ${out.evalue}`
    copyText = tb
    body = (
      <pre className="overflow-x-auto whitespace-pre-wrap break-words bg-rose-50 px-3 py-2 font-mono text-xs text-rose-700">
        {tb}
      </pre>
    )
  } else {
    const d = out.data
    if (d['image/png']) {
      imgSrc = `data:image/png;base64,${d['image/png']}`
      imgName = 'output.png'
      body = <img alt="output" className="max-w-full px-3 py-2" src={imgSrc} />
    } else if (d['image/jpeg']) {
      imgSrc = `data:image/jpeg;base64,${d['image/jpeg']}`
      imgName = 'output.jpg'
      body = <img alt="output" className="max-w-full px-3 py-2" src={imgSrc} />
    } else if (d['text/html']) {
      body = (
        <div
          className="max-w-none overflow-x-auto px-3 py-2 text-xs"
          // Output HTML berasal dari kode milik pengguna sendiri.
          dangerouslySetInnerHTML={{ __html: d['text/html'] }}
        />
      )
    } else if (d['text/plain']) {
      copyText = d['text/plain']
      body = (
        <LongText
          text={d['text/plain']}
          className="overflow-x-auto whitespace-pre-wrap break-words px-3 py-1.5 font-mono text-xs text-slate-800"
        />
      )
    } else {
      return null
    }
  }

  return (
    <div className="group/out relative">
      {body}
      <OutputActions copyText={copyText} imgSrc={imgSrc} imgName={imgName} />
    </div>
  )
}

// Tombol Salin / Unduh output (muncul saat hover) — mirip VS Code. Gambar bisa disalin
// ke clipboard & diunduh sbg PNG/JPG; teks (stdout/hasil/error) bisa disalin.
function OutputActions({
  copyText,
  imgSrc,
  imgName,
}: {
  copyText: string | null
  imgSrc: string | null
  imgName: string
}) {
  const [ok, setOk] = useState(false)
  const [failed, setFailed] = useState(false)
  if (!copyText && !imgSrc) return null

  // Re-encode gambar ke PNG lewat <canvas> -> DIJAMIN image/png (format yang diterima
  // clipboard Chrome/Edge & bisa di-paste ke Word), apa pun sumbernya (png/jpeg).
  const toPngBlob = (src: string): Promise<Blob> =>
    new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => {
        const c = document.createElement('canvas')
        c.width = img.naturalWidth || img.width
        c.height = img.naturalHeight || img.height
        const ctx = c.getContext('2d')
        if (!ctx) return reject(new Error('no-ctx'))
        ctx.drawImage(img, 0, 0)
        c.toBlob((b) => (b ? resolve(b) : reject(new Error('no-blob'))), 'image/png')
      }
      img.onerror = () => reject(new Error('img-load'))
      img.src = src
    })

  const copy = async () => {
    setFailed(false)
    try {
      if (imgSrc) {
        // ClipboardItem dengan PROMISE blob -> panggilan write() TETAP di dalam gesture
        // user (andal di Chrome/Edge); blob PNG di-resolve setelahnya. Kunci MIME
        // di-hardcode 'image/png' (bukan blob.type yang bisa kosong -> ditolak).
        await navigator.clipboard.write([
          new ClipboardItem({ 'image/png': toPngBlob(imgSrc) }),
        ])
      } else if (copyText != null) {
        await navigator.clipboard.writeText(copyText)
      }
      setOk(true)
      setTimeout(() => setOk(false), 1400)
    } catch {
      // Clipboard diblokir/tak didukung -> beri tahu user (bisa pakai tombol Unduh).
      setFailed(true)
      setTimeout(() => setFailed(false), 2500)
    }
  }
  const download = () => {
    if (!imgSrc) return
    const a = document.createElement('a')
    a.href = imgSrc
    a.download = imgName
    document.body.appendChild(a)
    a.click()
    a.remove()
  }
  return (
    <div className="absolute right-1.5 top-1.5 flex gap-1 opacity-0 transition group-hover/out:opacity-100">
      <button
        onClick={copy}
        title={
          failed
            ? 'Gagal menyalin — pakai Chrome/Edge (https), atau klik Unduh lalu sisipkan di Word'
            : imgSrc
              ? 'Salin gambar (bisa di-paste ke Word)'
              : 'Salin teks'
        }
        className={cn(
          'rounded bg-white/90 px-1.5 py-0.5 text-[11px] font-medium shadow-sm ring-1 transition',
          failed
            ? 'text-rose-600 ring-rose-200'
            : 'text-slate-500 ring-slate-200 hover:text-brand-600',
        )}
      >
        {failed ? '⚠ Gagal' : ok ? '✓ Tersalin' : 'Salin'}
      </button>
      {imgSrc && (
        <button
          onClick={download}
          title="Unduh gambar"
          className="rounded bg-white/90 px-1.5 py-0.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200 hover:text-brand-600"
        >
          Unduh
        </button>
      )}
    </div>
  )
}
