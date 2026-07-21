// Pusat notifikasi in-app (ikon lonceng): job selesai/gagal, kuota, dsb.
// Poll ringan 30 dtk; badge angka = belum dibaca. Panel via portal (fixed).

import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { api } from '../lib/api'
import { cn, timeAgo } from '../lib/format'
import type { NotificationItem } from '../lib/types'
import { IconBell, IconCheck, IconClock, IconX } from './icons'

const TYPE_DOT: Record<string, string> = {
  job_succeeded: 'bg-emerald-500',
  job_failed: 'bg-rose-500',
  quota_warning: 'bg-amber-500',
  info: 'bg-brand-500',
}

export default function NotificationsBell({
  variant = 'sidebar',
  collapsed = false,
}: {
  // sidebar = tombol lebar di sidebar gelap; top = ikon kecil di header mobile
  variant?: 'sidebar' | 'top'
  collapsed?: boolean
}) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const q = useQuery({
    queryKey: ['notifications'],
    queryFn: api.listNotifications,
    refetchInterval: 30000,
  })
  const items = q.data ?? []
  const unread = items.filter((n) => !n.read).length

  const readAll = useMutation({
    mutationFn: api.markAllNotificationsRead,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['notifications'] }),
  })

  const openItem = (n: NotificationItem) => {
    if (!n.read) {
      void api
        .markNotificationRead(n.id)
        .then(() => qc.invalidateQueries({ queryKey: ['notifications'] }))
    }
    setOpen(false)
    if (n.link) navigate(n.link)
  }

  const badge =
    unread > 0 ? (
      <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
        {unread > 9 ? '9+' : unread}
      </span>
    ) : null

  return (
    <>
      {variant === 'sidebar' ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title="Notifikasi"
          className={cn(
            'relative mb-2 flex w-full items-center rounded-2xl bg-white/5 text-left text-sm text-slate-200 ring-1 ring-white/10 transition hover:bg-white/10',
            collapsed ? 'justify-center p-2' : 'gap-3 px-3 py-2.5',
          )}
        >
          <span className="relative">
            <IconBell className="h-4 w-4 text-brand-300" />
            {badge}
          </span>
          {!collapsed && (
            <>
              Notifikasi
              {unread > 0 && (
                <span className="ml-auto rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-bold text-rose-300 ring-1 ring-inset ring-rose-400/30">
                  {unread} baru
                </span>
              )}
            </>
          )}
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title="Notifikasi"
          className="relative grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-white transition hover:bg-white/20"
        >
          <IconBell className="h-4 w-4" />
          {badge}
        </button>
      )}

      {open &&
        createPortal(
          <div className="fixed inset-0 z-[90]" onClick={() => setOpen(false)}>
            <div className="absolute inset-0 bg-slate-950/30 backdrop-blur-[2px]" />
            <div
              onClick={(e) => e.stopPropagation()}
              className={cn(
                'absolute flex max-h-[70vh] w-[22rem] max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200',
                variant === 'sidebar'
                  ? 'bottom-6 left-4'
                  : 'right-3 top-14',
              )}
            >
              <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
                <IconBell className="h-4 w-4 text-brand-600" />
                <span className="text-sm font-semibold text-slate-800">
                  Notifikasi
                </span>
                {unread > 0 && (
                  <button
                    onClick={() => readAll.mutate()}
                    className="ml-auto flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
                  >
                    <IconCheck className="h-3.5 w-3.5" /> Tandai semua dibaca
                  </button>
                )}
                <button
                  onClick={() => setOpen(false)}
                  className={cn('text-slate-400 hover:text-slate-600', unread === 0 && 'ml-auto')}
                  aria-label="Tutup"
                >
                  <IconX className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 divide-y divide-slate-100 overflow-y-auto">
                {items.length === 0 && (
                  <p className="px-4 py-8 text-center text-sm text-slate-400">
                    Belum ada notifikasi.
                  </p>
                )}
                {items.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => openItem(n)}
                    className={cn(
                      'flex w-full items-start gap-2.5 px-4 py-3 text-left transition hover:bg-slate-50',
                      !n.read && 'bg-brand-50/50',
                    )}
                  >
                    <span
                      className={cn(
                        'mt-1.5 h-2 w-2 shrink-0 rounded-full',
                        TYPE_DOT[n.type] ?? TYPE_DOT.info,
                        n.read && 'opacity-30',
                      )}
                    />
                    <span className="min-w-0">
                      <span
                        className={cn(
                          'block truncate text-sm',
                          n.read ? 'text-slate-600' : 'font-semibold text-slate-800',
                        )}
                      >
                        {n.title}
                      </span>
                      {n.body && (
                        <span className="mt-0.5 block truncate text-xs text-slate-500">
                          {n.body}
                        </span>
                      )}
                      <span className="mt-1 flex items-center gap-1 text-[11px] text-slate-400">
                        <IconClock className="h-3 w-3" /> {timeAgo(n.created_at)}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
