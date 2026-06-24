import { cn } from '../lib/format'

export default function ProgressBar({
  value,
  color,
  className,
}: {
  value: number
  color?: string
  className?: string
}) {
  const v = Math.min(100, Math.max(0, value))
  const auto =
    v > 85
      ? 'from-rose-500 to-rose-400'
      : v > 60
        ? 'from-amber-500 to-amber-400'
        : 'from-brand-500 to-indigo-500'
  return (
    <div
      className={cn(
        'h-2.5 w-full overflow-hidden rounded-full bg-slate-200/70',
        className,
      )}
    >
      <div
        className={cn(
          'shimmer h-full rounded-full bg-gradient-to-r transition-all duration-500',
          color ?? auto,
        )}
        style={{ width: `${v}%` }}
      />
    </div>
  )
}
