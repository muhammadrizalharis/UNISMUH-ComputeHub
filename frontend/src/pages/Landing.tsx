import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

import SiteFooter from '../components/SiteFooter'
import { IconMoon, IconSun } from '../components/icons'
import { useAuth } from '../lib/auth'
import { getTheme, setTheme } from '../lib/theme'

const CAMPUS_BG = '/campus.jpg'

const LOGOS = [
  { src: '/logos/unismuh.jpg', alt: 'Universitas Muhammadiyah Makassar' },
  { src: '/logos/teknik-biru.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/unggul.png', alt: 'Akreditasi Unggul' },
  { src: '/logos/gift.png', alt: 'GIFT UNISMUH' },
  { src: '/logos/teknik-merah.png', alt: 'Fakultas Teknik UNISMUH' },
]

export default function Landing() {
  const { user } = useAuth()
  const [theme, setThemeState] = useState(getTheme())
  const flipTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    setThemeState(next)
  }
  if (user) return <Navigate to="/" replace />

  return (
    <div className="bg-white">
      {/* ===== HERO ===== */}
      <section className="relative flex min-h-screen flex-col overflow-hidden">
        {/* Latar gedung UNISMUH */}
        <div
          className="absolute inset-0 scale-110 bg-cover bg-center blur-[6px]"
          style={{ backgroundImage: `url(${CAMPUS_BG})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/90 via-slate-900/85 to-[#06122b]/92" />
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
            <button
              onClick={flipTheme}
              title={theme === 'dark' ? 'Ganti ke mode terang' : 'Ganti ke mode gelap'}
              aria-label="Ganti tema"
              className="grid h-10 w-10 place-items-center rounded-xl bg-white/10 text-white ring-1 ring-white/20 backdrop-blur transition hover:bg-white/20"
            >
              {theme === 'dark' ? (
                <IconSun className="h-5 w-5" />
              ) : (
                <IconMoon className="h-5 w-5" />
              )}
            </button>
            <Link to="/login" className="btn-primary">
              Masuk
            </Link>
          </div>
        </header>

        {/* Konten hero */}
        <div className="relative z-10 flex flex-1 items-center justify-center px-6 py-10 text-center text-white">
          <div className="max-w-3xl animate-fade-in">
            <span className="relative mx-auto mb-7 grid h-40 w-40 place-items-center">
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
                className="relative h-40 w-40 object-contain drop-shadow-2xl"
              />
            </span>

            <span className="inline-flex items-center rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/80 ring-1 ring-inset ring-white/20 backdrop-blur">
              Academic HPC Platform · Fakultas Teknik · Informatika
            </span>

            <h1 className="mt-4 text-4xl font-black leading-[1.1] sm:text-5xl">
              Komputasi <span className="gradient-text">Cerdas</span>
              <br />
              untuk Masa Depan Akademik
            </h1>

            <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-white/70">
              Infrastruktur komputasi berkinerja tinggi yang dirancang untuk
              mendukung penelitian, pembelajaran, kecerdasan buatan, dan inovasi
              digital di Fakultas Teknik Universitas Muhammadiyah Makassar.
            </p>

            <div className="mt-8 flex items-center justify-center">
              <Link to="/login" className="btn-primary px-7 py-3 text-base">
                Masuk ke Dashboard →
              </Link>
            </div>

            <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
              {LOGOS.map((l) => (
                <span
                  key={l.src}
                  className="keep-light grid h-14 w-14 place-items-center rounded-2xl bg-white shadow-md ring-1 ring-white/40 transition hover:-translate-y-0.5"
                >
                  <img src={l.src} alt={l.alt} className="h-9 w-9 object-contain" />
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  )
}
