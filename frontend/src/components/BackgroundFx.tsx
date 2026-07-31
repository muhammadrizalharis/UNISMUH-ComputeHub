import { useEffect, useRef } from 'react'

/*
 * Efek latar bersama untuk halaman publik (Landing & Login):
 * - ParticleField: jaringan partikel bergaris (nuansa neural-net) yang
 *   bereaksi mengikuti kursor pengunjung. Canvas + rAF, ringan.
 * - Meteors: beberapa meteor melintas diagonal berkala (murni CSS).
 */

export function ParticleField() {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    // Laptop lemah (≤4 core): gambar di resolusi 1x — garis sedikit lebih lembut
    // tapi beban piksel turun 4x; perangkat kencang tetap tajam (2x).
    const inti = navigator.hardwareConcurrency || 8
    const DPR = Math.min(inti <= 4 ? 1 : 2, window.devicePixelRatio || 1)
    let w = 0
    let h = 0
    const ukur = () => {
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = w * DPR
      canvas.height = h * DPR
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0)
    }
    ukur()
    const N = Math.max(30, Math.min(90, Math.floor((w * h) / 20000)))
    const pts = Array.from({ length: N }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
    }))
    const mouse = { x: -9999, y: -9999 }
    const onMove = (e: MouseEvent) => {
      const r = canvas.getBoundingClientRect()
      mouse.x = e.clientX - r.left
      mouse.y = e.clientY - r.top
    }
    const onLeave = () => {
      mouse.x = -9999
      mouse.y = -9999
    }
    let raf = 0
    let lalu = performance.now()
    const gambar = () => {
      // Delta-time: bila frame drop (laptop lambat), partikel melangkah lebih
      // jauh per frame — kecepatan gerak tampak SAMA di semua perangkat.
      const kini = performance.now()
      const dt = Math.min(3, (kini - lalu) / 16.67)
      lalu = kini
      ctx.clearRect(0, 0, w, h)
      for (const p of pts) {
        p.x += p.vx * dt
        p.y += p.vy * dt
        if (p.x < 0) p.x = w
        if (p.x > w) p.x = 0
        if (p.y < 0) p.y = h
        if (p.y > h) p.y = 0
        ctx.beginPath()
        ctx.arc(p.x, p.y, 1.3, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(147, 197, 253, 0.6)'
        ctx.fill()
      }
      const JANGKAU = 110
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x
          const dy = pts[i].y - pts[j].y
          const d2 = dx * dx + dy * dy
          if (d2 < JANGKAU * JANGKAU) {
            const a = 0.14 * (1 - Math.sqrt(d2) / JANGKAU)
            ctx.strokeStyle = `rgba(96, 165, 250, ${a})`
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(pts[i].x, pts[i].y)
            ctx.lineTo(pts[j].x, pts[j].y)
            ctx.stroke()
          }
        }
        // Garis ke kursor: partikel "menyapa" pengunjung.
        const mx = pts[i].x - mouse.x
        const my = pts[i].y - mouse.y
        const md2 = mx * mx + my * my
        if (md2 < 160 * 160) {
          const a = 0.3 * (1 - Math.sqrt(md2) / 160)
          ctx.strokeStyle = `rgba(103, 232, 249, ${a})`
          ctx.beginPath()
          ctx.moveTo(pts[i].x, pts[i].y)
          ctx.lineTo(mouse.x, mouse.y)
          ctx.stroke()
        }
      }
      raf = requestAnimationFrame(gambar)
    }
    raf = requestAnimationFrame(gambar)
    window.addEventListener('resize', ukur)
    window.addEventListener('mousemove', onMove, { passive: true })
    window.addEventListener('mouseout', onLeave)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', ukur)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseout', onLeave)
    }
  }, [])
  return (
    <canvas
      ref={ref}
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden="true"
    />
  )
}

const POSISI_METEOR: Array<{ left: string; top: string; t: string; d: string }> = [
  { left: '68%', top: '8%', t: '6s', d: '0s' },
  { left: '85%', top: '22%', t: '7.5s', d: '2.4s' },
  { left: '45%', top: '4%', t: '8s', d: '4.8s' },
  { left: '92%', top: '55%', t: '9s', d: '6.5s' },
  { left: '25%', top: '12%', t: '10s', d: '8.2s' },
]

export function Meteors() {
  return (
    <div
      className="pointer-events-none absolute inset-0 overflow-hidden"
      aria-hidden="true"
    >
      {POSISI_METEOR.map((m, i) => (
        <span
          key={i}
          className="meteor"
          style={
            {
              left: m.left,
              top: m.top,
              '--t': m.t,
              '--d': m.d,
            } as React.CSSProperties
          }
        />
      ))}
    </div>
  )
}
