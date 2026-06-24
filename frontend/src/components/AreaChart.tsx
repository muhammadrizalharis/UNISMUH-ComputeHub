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
  className,
}: {
  data: number[]
  max?: number
  height?: number
  color?: string
  gridLines?: number
  className?: string
}) {
  const rawId = useId()
  const gid = `area-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`

  const w = 100
  const h = 100
  const maxV = Math.max(max, ...data) || 1
  const latest = data.length ? data[data.length - 1] : 0

  const coords =
    data.length >= 2
      ? data.map((v, i) => {
          const x = (i / (data.length - 1)) * w
          const y = h - (Math.min(v, maxV) / maxV) * h
          return [x, y] as const
        })
      : []

  const line = coords.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ')
  const area = coords.length ? `0,${h} ${line} ${w},${h}` : ''
  const dotTop = `${((1 - Math.min(latest, maxV) / maxV) * 100).toFixed(2)}%`

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
    </div>
  )
}
