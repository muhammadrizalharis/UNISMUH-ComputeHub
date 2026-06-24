import type { JobStatus } from '../lib/types'
import { cn } from '../lib/format'

const STYLES: Record<JobStatus, string> = {
  queued: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  running: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  succeeded: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  failed: 'bg-rose-50 text-rose-700 ring-rose-600/20',
  cancelled: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

const LABELS: Record<JobStatus, string> = {
  queued: 'Antri',
  running: 'Berjalan',
  succeeded: 'Sukses',
  failed: 'Gagal',
  cancelled: 'Dibatalkan',
}

export default function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={cn('badge', STYLES[status])}>
      {status === 'running' && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-600" />
      )}
      {LABELS[status]}
    </span>
  )
}
