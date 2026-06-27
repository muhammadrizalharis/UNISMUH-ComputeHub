import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { IconKey, IconMail } from '../components/icons'
import { ApiError, LOGOUT_REASON_KEY } from '../lib/api'
import { useAuth } from '../lib/auth'

const LOGOS = [
  { src: '/logos/unismuh.jpg', alt: 'Universitas Muhammadiyah Makassar' },
  { src: '/logos/teknik-biru.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/unggul.png', alt: 'Akreditasi Unggul' },
  { src: '/logos/teknik-merah.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/gift.png', alt: 'GIFT UNISMUH' },
]

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // Tampilkan alasan keluar paksa (mis. sesi diambil alih di perangkat lain).
  useEffect(() => {
    try {
      const reason = sessionStorage.getItem(LOGOUT_REASON_KEY)
      if (reason) {
        setNotice(reason)
        sessionStorage.removeItem(LOGOUT_REASON_KEY)
      }
    } catch {
      /* sessionStorage tak tersedia */
    }
  }, [])

  if (user) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Gagal login. Coba lagi.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-gradient-to-br from-slate-950 via-[#0a1230] to-[#04140f]">
      {/* Aurora + blobs (latar futuristik, beda dari foto gedung) */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(55rem 55rem at 12% 8%, rgba(51,133,252,0.22), transparent 60%), radial-gradient(48rem 48rem at 88% 18%, rgba(16,185,129,0.18), transparent 60%), radial-gradient(45rem 45rem at 50% 110%, rgba(124,58,237,0.20), transparent 55%)',
        }}
      />
      <div className="blob pointer-events-none absolute -left-20 top-12 h-72 w-72 rounded-full bg-brand-500/20" />
      <div
        className="blob pointer-events-none absolute right-0 top-1/4 h-80 w-80 rounded-full bg-emerald-500/15"
        style={{ animationDelay: '2.5s' }}
      />

      {/* ================= LOGIN: kartu mengambang ================= */}
      <main className="relative z-10 flex flex-1 items-center justify-center p-4 sm:p-6 lg:p-10">
        <div className="grid w-full max-w-5xl animate-fade-in overflow-hidden rounded-[1.75rem] shadow-2xl ring-1 ring-white/10 lg:grid-cols-2">
          {/* -- Branding (kiri) -- */}
          <div className="relative flex flex-col justify-between gap-8 overflow-hidden bg-gradient-to-br from-brand-600/40 via-indigo-700/30 to-emerald-600/30 p-8 text-white backdrop-blur-xl lg:p-10">
            <div className="flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center overflow-hidden rounded-full bg-white shadow-lg">
                <img src="/logos/unismuh.jpg" alt="UNISMUH" className="h-9 w-9 object-contain" />
              </span>
              <div>
                <p className="text-sm font-semibold tracking-wide">UNISMUH ComputeHub</p>
                <p className="text-xs text-white/60">Fakultas Teknik · Informatika</p>
              </div>
            </div>

            <div>
              {/* Logo Universitas Muhammadiyah Makassar (focal kiri) */}
              <span className="relative mb-6 inline-grid h-24 w-24 place-items-center">
                <span
                  className="ring-spin absolute -inset-2 rounded-full opacity-60 blur-md"
                  style={{
                    background:
                      'conic-gradient(from 0deg, #3385fc, #10b981, #06b6d4, #3385fc)',
                  }}
                />
                <span className="relative grid h-24 w-24 place-items-center rounded-3xl bg-white/95 shadow-2xl ring-1 ring-white/40">
                  <img
                    src="/logos/unismuh.jpg"
                    alt="Universitas Muhammadiyah Makassar"
                    className="h-[4.5rem] w-[4.5rem] object-contain"
                  />
                </span>
              </span>
              <h1 className="text-3xl font-black leading-[1.15] xl:text-4xl">
                Platform <span className="gradient-text">Komputasi Server Kampus</span>
              </h1>
              <p className="mt-4 max-w-md text-sm leading-relaxed text-white/70">
                Layanan komputasi terpusat Fakultas Teknik untuk mendukung kegiatan
                riset, praktikum, dan pembelajaran sivitas akademika secara efisien,
                terjadwal, dan aman.
              </p>
            </div>

            <p className="text-xs text-white/40">
              © {new Date().getFullYear()} UNISMUH ComputeHub · Universitas Muhammadiyah Makassar
            </p>
          </div>

          {/* -- Form (kanan) -- */}
          <div className="bg-white p-8 sm:p-10">
            <div className="mb-6 flex items-center justify-center gap-2.5">
              {LOGOS.map((l) => (
                <span
                  key={l.src}
                  className="grid h-10 w-10 place-items-center rounded-xl bg-white shadow-sm ring-1 ring-slate-200/80 transition hover:-translate-y-0.5 hover:shadow-md"
                >
                  <img src={l.src} alt={l.alt} className="h-6 w-6 object-contain" />
                </span>
              ))}
            </div>

            <div className="mb-6 text-center">
              <h2 className="gradient-text text-2xl font-bold">Selamat Datang</h2>
              <p className="mt-1 text-sm text-slate-500">
                Silakan masuk untuk mengakses dashboard Anda
              </p>
            </div>

            <form onSubmit={submit} className="space-y-4">
              {notice && (
                <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700 ring-1 ring-inset ring-amber-600/20">
                  {notice}
                </div>
              )}

              <div>
                <label
                  className="mb-1 block text-sm font-medium text-slate-700"
                  htmlFor="email"
                >
                  Email
                </label>
                <div className="relative">
                  <IconMail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    id="email"
                    type="email"
                    autoComplete="username"
                    className="input pl-10"
                    placeholder="nama@unismuh.ac.id"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div>
                <label
                  className="mb-1 block text-sm font-medium text-slate-700"
                  htmlFor="password"
                >
                  Password
                </label>
                <div className="relative">
                  <IconKey className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    id="password"
                    type={showPw ? 'text' : 'password'}
                    autoComplete="current-password"
                    className="input pl-10 pr-10"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                    aria-label={showPw ? 'Sembunyikan password' : 'Tampilkan password'}
                  >
                    {showPw ? (
                      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" stroke="currentColor" strokeWidth="2">
                        <path d="M3 3l18 18" strokeLinecap="round" />
                        <path d="M10.6 10.6a2 2 0 002.8 2.8" strokeLinecap="round" />
                        <path d="M9.9 4.2A10.9 10.9 0 0112 4c5 0 9.3 3.1 11 8a12.6 12.6 0 01-2.2 3.6M6.1 6.1A12.6 12.6 0 001 12c1.7 4.9 6 8 11 8 1.6 0 3.1-.3 4.5-.9" strokeLinecap="round" />
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" stroke="currentColor" strokeWidth="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" strokeLinecap="round" strokeLinejoin="round" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              {error && (
                <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
                  {error}
                </div>
              )}

              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? 'Masuk…' : 'Masuk ke Dashboard'}
              </button>
            </form>

            <p className="mt-5 text-center text-xs text-slate-400">
              Akun dibuat oleh administrator. Butuh bantuan? Hubungi admin lab / IT.
            </p>
          </div>
        </div>
      </main>

      {/* ================= FOOTER ================= */}
      <footer className="relative z-10 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-10">
          <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-4">
            {/* Brand */}
            <div>
              <div className="flex items-center gap-2">
                <img src="/logos/teknik-biru.png" alt="" className="h-9 w-9 object-contain" />
                <div>
                  <p className="font-bold text-slate-800">UNISMUH ComputeHub</p>
                  <p className="text-[11px] uppercase tracking-wide text-slate-400">
                    Sistem Komputasi Terpadu
                  </p>
                </div>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-slate-500">
                Fakultas Teknik · Universitas Muhammadiyah Makassar
              </p>
            </div>

            {/* Hubungi Kami */}
            <div>
              <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-700">
                Hubungi Kami
              </h3>
              <ul className="space-y-2.5 text-sm text-slate-500">
                <li className="flex items-center gap-2">
                  <IconMail className="h-4 w-4 shrink-0 text-brand-600" />
                  ft@unismuh.ac.id
                </li>
                <li className="flex items-center gap-2">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4 shrink-0 text-brand-600">
                    <path d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1.9.3 1.8.6 2.6a2 2 0 01-.5 2.1L8.1 9.6a16 16 0 006 6l1.2-1.2a2 2 0 012.1-.5c.8.3 1.7.5 2.6.6a2 2 0 011.7 2z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  +62 411 865 545
                </li>
                <li className="flex items-start gap-2">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mt-0.5 h-4 w-4 shrink-0 text-brand-600">
                    <path d="M21 10c0 7-9 12-9 12s-9-5-9-12a9 9 0 0118 0z" />
                    <circle cx="12" cy="10" r="3" />
                  </svg>
                  Jl. Sultan Alauddin No.259, Makassar
                </li>
              </ul>
            </div>

            {/* Kebijakan + Ikuti Kami */}
            <div>
              <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-700">
                Kebijakan
              </h3>
              <ul className="space-y-2 text-sm text-slate-500">
                <li>Kebijakan Privasi</li>
                <li>Syarat &amp; Ketentuan</li>
                <li>Kebijakan Cookie</li>
              </ul>
              <h3 className="mb-2 mt-5 text-sm font-bold uppercase tracking-wide text-slate-700">
                Ikuti Kami
              </h3>
              <div className="flex gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-[#1877f2] text-white" title="Facebook">
                  <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4"><path d="M15 3h-3a4 4 0 00-4 4v3H5v4h3v7h4v-7h3l1-4h-4V7a1 1 0 011-1h3z" /></svg>
                </span>
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-[#f58529] via-[#dd2a7b] to-[#8134af] text-white" title="Instagram">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><rect x="3" y="3" width="18" height="18" rx="5" /><circle cx="12" cy="12" r="4" /><circle cx="17.5" cy="6.5" r="1" fill="currentColor" /></svg>
                </span>
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-[#ff0000] text-white" title="YouTube">
                  <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4"><path d="M22 12s0-3.2-.4-4.7a2.5 2.5 0 00-1.8-1.8C18.3 5 12 5 12 5s-6.3 0-7.8.5A2.5 2.5 0 002.4 7.3C2 8.8 2 12 2 12s0 3.2.4 4.7a2.5 2.5 0 001.8 1.8C5.7 19 12 19 12 19s6.3 0 7.8-.5a2.5 2.5 0 001.8-1.8C22 15.2 22 12 22 12zM10 15V9l5 3z" /></svg>
                </span>
              </div>
            </div>

            {/* Pengembang */}
            <div className="flex items-center gap-4 md:justify-end">
              <img
                src="/developer.jpg"
                alt="muhammadrizalharis"
                className="h-24 w-20 rounded-2xl object-cover object-top shadow-md ring-2 ring-brand-500/30"
              />
              <div>
                <p className="text-[11px] uppercase tracking-wide text-slate-400">Built by</p>
                <p className="font-bold text-slate-800">muhammadrizalharis</p>
                <p className="text-xs text-slate-500">Pengembang · Informatika</p>
              </div>
            </div>
          </div>

          <div className="mt-8 flex flex-col items-center justify-between gap-2 border-t border-slate-200 pt-5 text-xs text-slate-400 sm:flex-row">
            <p>
              © {new Date().getFullYear()}{' '}
              <span className="font-semibold text-slate-600">UNISMUH ComputeHub</span>{' '}
              · Semua hak dilindungi.
            </p>
            <p>
              Built by{' '}
              <span className="font-semibold text-slate-600">muhammadrizalharis</span>
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
