import { timeAgo } from '../lib/format'
import { cn } from '../lib/format'

// Tab ComputeHub yang terbuka mengirim /auth/heartbeat tiap ±60 dtk (tab latar bisa
// diperlambat browser ke ±1 mnt), jadi "Online" = sinyal dalam 3 menit terakhir.
const ONLINE_SECONDS = 3 * 60
const RECENT_SECONDS = 30 * 60

export type PresenceKind = 'online' | 'recent' | 'offline' | 'unknown'

export function presenceOf(lastSeen: string | null | undefined): PresenceKind {
  if (!lastSeen) return 'unknown'
  const t = Date.parse(lastSeen)
  if (Number.isNaN(t)) return 'unknown'
  const diff = (Date.now() - t) / 1000
  if (diff <= ONLINE_SECONDS) return 'online'
  if (diff <= RECENT_SECONDS) return 'recent'
  return 'offline'
}

export function presenceLabel(lastSeen: string | null | undefined): string {
  switch (presenceOf(lastSeen)) {
    case 'online':
      return 'Online'
    case 'recent':
      return `Aktif ${timeAgo(lastSeen)}`
    case 'offline':
      return `Offline · terakhir ${timeAgo(lastSeen)}`
    default:
      return 'Belum tercatat'
  }
}

const DOT: Record<PresenceKind, string> = {
  online: 'bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.18)]',
  recent: 'bg-amber-400',
  offline: 'bg-slate-300',
  unknown: 'bg-slate-200',
}

const TEXT: Record<PresenceKind, string> = {
  online: 'text-emerald-600 font-semibold',
  recent: 'text-amber-600',
  offline: 'text-slate-400',
  unknown: 'text-slate-400',
}

export function PresenceBadge({
  lastSeen,
  className,
}: {
  lastSeen: string | null | undefined
  className?: string
}) {
  const kind = presenceOf(lastSeen)
  const title =
    kind === 'unknown'
      ? 'Belum ada catatan membuka web ComputeHub sejak fitur status online aktif'
      : `Terakhir membuka web ComputeHub: ${new Date(lastSeen as string).toLocaleString('id-ID')}`
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 text-xs', TEXT[kind], className)}
      title={title}
      data-testid="presence-badge"
    >
      <span className={cn('h-2 w-2 shrink-0 rounded-full', DOT[kind])} />
      {presenceLabel(lastSeen)}
    </span>
  )
}
