import { useId } from 'react'

import { cn } from '../lib/format'

/**
 * Grafik area besar berbasis SVG (tanpa library), responsif penuh.
 * Cocok untuk time-series CPU/GPU/RAM. Garis + isian gradien + grid halus.
 */
export default function AreaChart({
  data,
  max = 100,
  height = 200,
  color = '#3b82f6',
  gridLines = 4,
  autoScale = false,
  formatValue,
  className,
}: {
  data: number[]
  max?: number
  height?: number
  color?: string
  gridLines?: number
  autoScale?: boolean
  formatValue?: (v: number) => string
  className?: string
}) {
  const rawId = useId()
  const gid = `area-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`

  const w = 100
  const h = 100
  const latest = data.length ? data[data.length - 1] : 0

  // Rentang sumbu-Y. Default: [0, max]. autoScale: ikuti min/max data (+ padding)
  // supaya gerakan kecil (mis. CPU 2%) tetap terlihat; tetap di-clamp ke [0, max].
  let lo = 0
  let hi = Math.max(max, ...data) || 1
  if (autoScale && data.length) {
    const dMin = Math.min(...data)
    const dMax = Math.max(...data)
    const pad = Math.max((dMax - dMin) * 0.25, dMax * 0.05)
    lo = Math.max(0, dMin - pad)
    hi = Math.min(max, dMax + pad)
    if (hi - lo < 1e-6) {
      // data nyaris konstan -> beri pita kecil supaya tak datar/0-bagi.
      lo = Math.max(0, dMax - 1)
      hi = Math.min(max, dMax + 1)
      if (hi <= lo) hi = lo + 1
    }
  }
  const span = hi - lo || 1
  const norm = (v: number) => (Math.min(Math.max(v, lo), hi) - lo) / span

  const coords =
    data.length >= 2
      ? data.map((v, i) => {
          const x = (i / (data.length - 1)) * w
          const y = h - norm(v) * h
          return [x, y] as const
        })
      : []

  const line = coords.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ')
  const area = coords.length ? `0,${h} ${line} ${w},${h}` : ''
  const dotTop = `${((1 - norm(latest)) * 100).toFixed(2)}%`
  const fmt = formatValue ?? ((v: number) => v.toFixed(1))

  return (
    <div className={cn('relative w-full', className)} style={{ height }}>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full overflow-visible"
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.4} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>

        {/* Grid horizontal */}
        {Array.from({ length: gridLines + 1 }).map((_, i) => {
          const y = (i / gridLines) * h
          return (
            <line
              key={i}
              x1="0"
              y1={y}
              x2={w}
              y2={y}
              className="text-slate-300/50"
              stroke="currentColor"
              strokeWidth={1}
              strokeDasharray="2 4"
              vectorEffect="non-scaling-stroke"
            />
          )
        })}

        {area && <polygon points={area} fill={`url(#${gid})`} />}
        {line && (
          <polyline
            points={line}
            fill="none"
            stroke={color}
            strokeWidth={2.4}
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      {/* Titik nilai terkini (HTML overlay agar tidak ikut terdistorsi) */}
      {data.length >= 2 && (
        <span
          className="absolute h-3 w-3 -translate-y-1/2 rounded-full ring-2 ring-white"
          style={{
            top: dotTop,
            right: 0,
            background: color,
            boxShadow: `0 0 0 4px ${color}26`,
          }}
        />
      )}

      {/* Angka sumbu-Y (rentang yang sedang ditampilkan) + nilai terkini -> presisi */}
      <span className="pointer-events-none absolute left-1.5 top-1 rounded bg-white/70 px-1 text-[10px] font-semibold tabular-nums text-slate-500">
        {fmt(hi)}
      </span>
      <span className="pointer-events-none absolute bottom-1 left-1.5 rounded bg-white/70 px-1 text-[10px] font-semibold tabular-nums text-slate-500">
        {fmt(lo)}
      </span>
      {data.length >= 2 && (
        <span
          className="pointer-events-none absolute -translate-y-1/2 rounded-md bg-white/90 px-1.5 py-0.5 text-[11px] font-bold tabular-nums shadow-sm ring-1 ring-slate-900/5"
          style={{ top: dotTop, right: 14, color }}
        >
          {fmt(latest)}
        </span>
      )}
    </div>
  )
}
