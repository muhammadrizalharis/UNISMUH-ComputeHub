import { useId } from 'react'

/** Gauge melingkar (SVG) dengan gradient + glow, beranimasi saat nilai berubah. */
export default function RadialGauge({
  value,
  size = 96,
  stroke = 9,
  label,
}: {
  value: number
  size?: number
  stroke?: number
  label?: string
}) {
  const id = useId().replace(/:/g, '')
  const v = Math.min(100, Math.max(0, value))
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const offset = c * (1 - v / 100)
  const hot = v > 85 ? '#f43f5e' : v > 60 ? '#f59e0b' : '#3385fc'

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={`g-${id}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#3385fc" />
            <stop offset="55%" stopColor="#7c3aed" />
            <stop offset="100%" stopColor="#06b6d4" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(148,163,184,0.22)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`url(#g-${id})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          style={{
            transition: 'stroke-dashoffset 0.8s cubic-bezier(.22,1,.36,1)',
            filter: `drop-shadow(0 0 6px ${hot}66)`,
          }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="text-xl font-bold text-slate-800">
            {v.toFixed(0)}
            <span className="text-xs text-slate-400">%</span>
          </p>
          {label && (
            <p className="text-[10px] uppercase tracking-wide text-slate-400">
              {label}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
