import { useEffect, useRef, useState } from 'react'

/** Animasi angka dari nilai sebelumnya ke target (easing cubic-out). */
export function useCountUp(target: number, duration = 800): number {
  const [val, setVal] = useState(0)
  const prev = useRef(0)

  useEffect(() => {
    const start = prev.current
    const diff = target - start
    if (diff === 0) return

    const t0 = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      const current = start + diff * eased
      setVal(current)
      prev.current = current // selalu update -> mulus bila target berubah di tengah animasi
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])

  return val
}

export default function CountUp({
  value,
  decimals = 0,
}: {
  value: number
  decimals?: number
}) {
  const v = useCountUp(value)
  return <>{v.toFixed(decimals)}</>
}
