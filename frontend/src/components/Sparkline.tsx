/** Sparkline ringan berbasis SVG (tanpa library chart). */
export default function Sparkline({
  data,
  max = 100,
  height = 44,
  stroke = '#1f66f2',
  autoScale = false,
  className,
}: {
  data: number[]
  max?: number
  height?: number
  stroke?: string
  autoScale?: boolean
  className?: string
}) {
  if (data.length < 2) {
    return <div style={{ height }} className={className} />
  }

  const w = 100
  const h = height
  let lo = 0
  let hi = Math.max(max, ...data) || 1
  if (autoScale) {
    const dMin = Math.min(...data)
    const dMax = Math.max(...data)
    const pad = Math.max((dMax - dMin) * 0.25, dMax * 0.05)
    lo = Math.max(0, dMin - pad)
    hi = Math.min(max, dMax + pad)
    if (hi - lo < 1e-6) {
      lo = Math.max(0, dMax - 1)
      hi = Math.min(max, dMax + 1)
      if (hi <= lo) hi = lo + 1
    }
  }
  const span = hi - lo || 1
  const step = w / (data.length - 1)
  const points = data
    .map(
      (v, i) =>
        `${(i * step).toFixed(2)},${(h - ((Math.min(Math.max(v, lo), hi) - lo) / span) * h).toFixed(2)}`,
    )
    .join(' ')
  const area = `0,${h} ${points} ${w},${h}`

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className={className}
      style={{ width: '100%', height }}
    >
      <polygon points={area} fill={stroke} opacity={0.1} />
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
