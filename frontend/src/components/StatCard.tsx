import type { ReactNode } from 'react'
import { cn } from '../lib/format'

export default function StatCard({
  label,
  value,
  sub,
  icon,
  accent = 'text-brand-600 bg-brand-50',
  delay = 0,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: ReactNode
  accent?: string
  delay?: number
}) {
  return (
    <div
      className="card-pad hover-lift animate-fade-in flex items-center gap-4"
      style={{ animationDelay: `${delay}ms` }}
    >
      {icon && (
        <span
          className={cn(
            'grid h-12 w-12 place-items-center rounded-2xl shadow-sm ring-1 ring-inset ring-white/50',
            accent,
          )}
        >
          {icon}
        </span>
      )}
      <div className="min-w-0">
        <p className="text-sm text-slate-500">{label}</p>
        <p className="truncate text-2xl font-bold text-slate-800">{value}</p>
        {sub && <p className="text-xs text-slate-400">{sub}</p>}
      </div>
    </div>
  )
}
