/** Sparkline ringan berbasis SVG (tanpa library chart). */
export default function Sparkline({
  data,
  max = 100,
  height = 44,
  stroke = '#1f66f2',
  className,
}: {
  data: number[]
  max?: number
  height?: number
  stroke?: string
  className?: string
}) {
  if (data.length < 2) {
    return <div style={{ height }} className={className} />
  }

  const w = 100
  const h = height
  const maxV = Math.max(max, ...data) || 1
  const step = w / (data.length - 1)
  const points = data
    .map((v, i) => `${(i * step).toFixed(2)},${(h - (v / maxV) * h).toFixed(2)}`)
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
