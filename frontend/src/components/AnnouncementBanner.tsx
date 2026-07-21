// Banner pengumuman platform (diatur super admin di Pengaturan). Tampil untuk
// semua user; bisa ditutup — muncul lagi hanya bila isi pengumuman berubah.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../lib/api'
import { cn } from '../lib/format'
import { IconBell, IconX } from './icons'

const TONES: Record<string, string> = {
  info: 'bg-brand-50 text-brand-800 ring-brand-600/20',
  warning: 'bg-amber-50 text-amber-800 ring-amber-600/20',
  danger: 'bg-rose-50 text-rose-800 ring-rose-600/20',
}

const LS_KEY = 'ch_announcement_dismissed'

export default function AnnouncementBanner() {
  const q = useQuery({
    queryKey: ['announcement'],
    queryFn: api.getAnnouncement,
    refetchInterval: 60000,
    staleTime: 30000,
  })
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(LS_KEY) ?? '',
  )
  const ann = q.data
  if (!ann?.text || dismissed === ann.text) return null
  return (
    <div
      className={cn(
        'mb-4 flex items-start gap-2.5 rounded-xl px-4 py-3 text-sm ring-1 ring-inset',
        TONES[ann.level] ?? TONES.info,
      )}
    >
      <IconBell className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1 whitespace-pre-wrap">{ann.text}</p>
      <button
        onClick={() => {
          localStorage.setItem(LS_KEY, ann.text)
          setDismissed(ann.text)
        }}
        className="shrink-0 opacity-60 transition hover:opacity-100"
        aria-label="Tutup pengumuman"
      >
        <IconX className="h-4 w-4" />
      </button>
    </div>
  )
}
