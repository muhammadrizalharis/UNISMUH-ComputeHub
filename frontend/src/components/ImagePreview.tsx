// Modal pratinjau GAMBAR (PNG/JPG/GIF/WebP/BMP/SVG) — dipakai explorer Notebook
// Interaktif & detail Job. Gambar diambil sebagai blob TERAUTENTIKASI lalu ditampilkan
// lewat object URL (di-revoke saat ditutup). Tersedia tombol unduh.
import { createPortal } from 'react-dom'

import { IconDownload, IconImage, IconX } from './icons'

// Ekstensi gambar RASTER yang didukung pratinjau inline. SVG SENGAJA dikecualikan
// (bisa berisi <script>) -> dibuka sebagai teks di editor, bukan <img>.
const IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.avif']

export function isImagePath(name: string): boolean {
  const n = name.toLowerCase()
  return IMAGE_EXT.some((e) => n.endsWith(e))
}

export default function ImagePreview({
  name,
  url,
  onClose,
}: {
  name: string
  url: string
  onClose: () => void
}) {
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
          <IconImage className="h-4 w-4 text-slate-400" />
          <span className="flex-1 truncate font-mono text-xs text-slate-600">{name}</span>
          <a
            href={url}
            download={name}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-brand-500"
          >
            <IconDownload className="h-3.5 w-3.5" /> Unduh
          </a>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-slate-100 p-4">
          <img
            src={url}
            alt={name}
            className="max-h-[75vh] max-w-full rounded object-contain shadow-lg"
          />
        </div>
      </div>
    </div>,
    document.body,
  )
}
