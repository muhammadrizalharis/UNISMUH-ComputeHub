import { useEffect, useRef, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

import SiteFooter from '../components/SiteFooter'
import ThemeToggle from '../components/ThemeToggle'
import { useAuth } from '../lib/auth'

const CAMPUS_BG = '/campus.jpg'

const LOGOS = [
  { src: '/logos/unismuh.jpg', alt: 'Universitas Muhammadiyah Makassar' },
  { src: '/logos/teknik-biru.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/unggul.png', alt: 'Akreditasi Unggul' },
  { src: '/logos/gift.png', alt: 'GIFT UNISMUH' },
  { src: '/logos/teknik-merah.png', alt: 'Fakultas Teknik UNISMUH' },
]

/** Angka menghitung naik saat halaman dibuka — mis. "90 GB" naik dari 0 ke 90. */
function CountUp({ value }: { value: string }) {
  // Pisahkan bagian angka & satuannya: '90 GB' -> 90 + ' GB'; '24/7' -> 24 + '/7'.
  const m = /^(\d+)(.*)$/.exec(value)
  const target = m ? parseInt(m[1], 10) : 0
  const suffix = m ? m[2] : value
  const [n, setN] = useState(0)
  useEffect(() => {
    if (!m || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setN(target)
      return
    }
    const t0 = performance.now()
    const DURASI = 1400
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / DURASI)
      setN(Math.round(target * (1 - Math.pow(1 - p, 3)))) // ease-out cubic
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return (
    <>
      {m ? n : ''}
      {suffix}
    </>
  )
}

/** Sorotan cahaya di kartu mengikuti posisi kursor (diset lewat CSS var). */
function ikutiKursor(e: React.MouseEvent<HTMLDivElement>) {
  const r = e.currentTarget.getBoundingClientRect()
  e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
  e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
}

export default function Landing() {
  const { user } = useAuth()
  const heroRef = useRef<HTMLDivElement>(null)

  // Parallax halus: latar gedung bergeser lebih lambat daripada konten saat scroll.
  useEffect(() => {
    const el = heroRef.current
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        el.style.transform = `translateY(${window.scrollY * 0.25}px) scale(1.1)`
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(raf)
    }
  }, [])

  if (user) return <Navigate to="/" replace />

  return (
    <div className="bg-white">
      {/* ===== HERO ===== */}
      <section className="relative flex min-h-screen flex-col overflow-hidden">
        {/* Latar gedung UNISMUH (parallax: digeser via ref saat scroll) */}
        <div
          ref={heroRef}
          className="absolute inset-0 scale-110 bg-cover bg-center blur-[6px] will-change-transform"
          style={{ backgroundImage: `url(${CAMPUS_BG})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/90 via-slate-900/85 to-[#06122b]/92" />
        <div className="bg-grid-fade pointer-events-none absolute inset-0" />
        <div className="blob pointer-events-none absolute -left-20 top-16 h-72 w-72 rounded-full bg-brand-500/25" />
        <div
          className="blob pointer-events-none absolute -right-16 top-1/4 h-80 w-80 rounded-full bg-emerald-500/20"
          style={{ animationDelay: '2.5s' }}
        />
        <div
          className="blob pointer-events-none absolute bottom-10 left-1/3 h-56 w-56 rounded-full bg-cyan-400/15"
          style={{ animationDelay: '4s' }}
        />

        {/* Navbar atas */}
        <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
          <div className="flex items-center gap-3.5 text-white">
            <img
              src="/logos/teknik-biru.png"
              alt="Fakultas Teknik UNISMUH"
              className="h-20 w-20 object-contain"
            />
            <div>
              <p className="text-2xl font-bold leading-tight">UNISMUH ComputeHub</p>
              <p className="text-base text-white/60">Fakultas Teknik</p>
            </div>
          </div>
          <div className="flex items-center gap-2.5">
            <ThemeToggle variant="overlay" />
            <Link to="/login" className="btn-primary">
              Masuk
            </Link>
          </div>
        </header>

        {/* Konten hero */}
        <div className="relative z-10 flex flex-1 items-center justify-center px-6 py-10 text-center text-white">
          <div className="max-w-3xl">
            <span
              className="reveal relative mx-auto mb-7 grid h-40 w-40 place-items-center"
              style={{ '--d': '0s' } as React.CSSProperties}
            >
              <span
                className="ring-spin absolute -inset-3 rounded-full opacity-75 blur-lg"
                style={{
                  background:
                    'conic-gradient(from 0deg, #3385fc, #10b981, #06b6d4, #3385fc)',
                }}
              />
              <span className="absolute inset-3 rounded-full bg-brand-400/20 blur-2xl" />
              <img
                src="/logos/unismuh-seal.png"
                alt="Universitas Muhammadiyah Makassar"
                className="float-soft relative h-40 w-40 object-contain drop-shadow-2xl"
              />
            </span>

            <span
              className="reveal inline-flex items-center rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/80 ring-1 ring-inset ring-white/20 backdrop-blur"
              style={{ '--d': '0.15s' } as React.CSSProperties}
            >
              Academic HPC Platform · Fakultas Teknik · Informatika
            </span>

            <h1
              className="reveal mt-4 text-4xl font-black leading-[1.1] sm:text-5xl"
              style={{ '--d': '0.25s' } as React.CSSProperties}
            >
              Komputasi <span className="gradient-text">Cerdas</span>
              <br />
              untuk Masa Depan Akademik
            </h1>

            <p
              className="reveal mx-auto mt-5 max-w-2xl text-base leading-relaxed text-white/70"
              style={{ '--d': '0.4s' } as React.CSSProperties}
            >
              Infrastruktur komputasi berkinerja tinggi yang dirancang untuk
              mendukung penelitian, pembelajaran, kecerdasan buatan, dan inovasi
              digital di Fakultas Teknik Universitas Muhammadiyah Makassar.
            </p>

            <div
              className="reveal mt-8 flex items-center justify-center"
              style={{ '--d': '0.55s' } as React.CSSProperties}
            >
              <Link
                to="/login"
                className="btn-primary px-7 py-3 text-base transition-transform duration-200 hover:scale-105 active:scale-95"
              >
                Masuk ke Dashboard →
              </Link>
            </div>

            {/* Angka unggulan */}
            <div className="mx-auto mt-10 grid max-w-3xl grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ['2×', 'NVIDIA L40S'],
                ['90 GB', 'VRAM total'],
                ['64', 'core CPU'],
                ['24/7', 'akses via SSO'],
              ].map(([num, label], i) => (
                <div
                  key={label}
                  onMouseMove={ikutiKursor}
                  className="reveal spotlight-card hover-lift rounded-2xl bg-white/5 px-4 py-4 ring-1 ring-white/10 backdrop-blur transition hover:bg-white/10 hover:ring-white/25"
                  style={{ '--d': `${0.65 + i * 0.1}s` } as React.CSSProperties}
                >
                  <p className="gradient-text text-2xl font-extrabold">
                    <CountUp value={num} />
                  </p>
                  <p className="mt-1 text-xs text-white/60">{label}</p>
                </div>
              ))}
            </div>

            {/* Fitur utama */}
            <div className="mx-auto mt-4 grid max-w-3xl gap-3 sm:grid-cols-3">
              {[
                [
                  '⚡ Notebook Interaktif',
                  'Kernel Python hidup di GPU ala Google Colab — variabel bertahan antar-sel, hasil langsung tampil.',
                ],
                [
                  '🛡️ Terisolasi & Adil',
                  'Tiap pengguna berjalan di container terpisah dengan kuota GPU harian — aman dan adil untuk semua.',
                ],
                [
                  '🔔 Selalu Terkabar',
                  'Job jalan di latar belakang walau laptop mati; selesai/gagal langsung dapat notifikasi & email.',
                ],
              ].map(([title, desc], i) => (
                <div
                  key={title}
                  onMouseMove={ikutiKursor}
                  className="reveal spotlight-card hover-lift rounded-2xl bg-white/5 px-4 py-4 text-left ring-1 ring-white/10 backdrop-blur transition hover:bg-white/10 hover:ring-white/25"
                  style={{ '--d': `${1.05 + i * 0.12}s` } as React.CSSProperties}
                >
                  <p className="text-sm font-bold text-white">{title}</p>
                  <p className="mt-1.5 text-xs leading-relaxed text-white/60">{desc}</p>
                </div>
              ))}
            </div>

            <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
              {LOGOS.map((l, i) => (
                <span
                  key={l.src}
                  className="keep-light reveal grid h-14 w-14 place-items-center rounded-2xl bg-white shadow-md ring-1 ring-white/40 transition hover:-translate-y-1 hover:shadow-xl"
                  style={{ '--d': `${1.3 + i * 0.08}s` } as React.CSSProperties}
                >
                  {/* float-soft di <img> (bukan span) agar tak menimpa animasi reveal */}
                  <img
                    src={l.src}
                    alt={l.alt}
                    className="float-soft h-9 w-9 object-contain"
                    style={{ '--d': `${i * 0.35}s` } as React.CSSProperties}
                  />
                </span>
              ))}
            </div>

            <div
              className="reveal mt-8"
              style={{ '--d': '1.6s' } as React.CSSProperties}
            >
              <span className="scroll-cue text-2xl text-white/70" aria-hidden="true">
                ↓
              </span>
            </div>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  )
}
