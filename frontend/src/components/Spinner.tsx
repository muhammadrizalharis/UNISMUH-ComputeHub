import { cn } from '../lib/format'

export default function Spinner({
  className,
  label,
}: {
  className?: string
  label?: string
}) {
  return (
    <div className={cn('flex items-center gap-3 text-slate-500', className)}>
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  )
}

export function FullScreenSpinner({ label = 'Memuat…' }: { label?: string }) {
  return (
    <div className="flex h-screen w-full items-center justify-center bg-slate-100">
      <Spinner label={label} />
    </div>
  )
}
