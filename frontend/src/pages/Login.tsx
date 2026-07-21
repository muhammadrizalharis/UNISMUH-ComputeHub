import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { IconKey, IconMail } from '../components/icons'
import { ApiError, LOGOUT_REASON_KEY, ssoEnabled, ssoLoginUrl } from '../lib/api'
import { useAuth } from '../lib/auth'

const LOGOS = [
  { src: '/logos/unismuh.jpg', alt: 'Universitas Muhammadiyah Makassar' },
  { src: '/logos/teknik-biru.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/unggul.png', alt: 'Akreditasi Unggul' },
  { src: '/logos/teknik-merah.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/gift.png', alt: 'GIFT UNISMUH' },
]

const CAMPUS_BG = '/campus.jpg'

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [ssoOn, setSsoOn] = useState(false)

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

  // Tampilkan tombol SSO hanya bila backend mengaktifkannya.
  useEffect(() => {
    let alive = true
    void ssoEnabled().then((on) => {
      if (alive) setSsoOn(on)
    })
    return () => {
      alive = false
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
    <div className="bg-white">
      {/* ===== LOGIN: layar bersih — hanya kartu, latar gedung UNISMUH ===== */}
      <main className="relative flex min-h-screen items-center justify-center overflow-hidden p-4 sm:p-6">
        {/* Background gedung UNISMUH */}
        <div
          className="absolute inset-0 scale-105 bg-cover bg-center"
          style={{ backgroundImage: `url(${CAMPUS_BG})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/92 via-slate-900/85 to-[#06122b]/92" />
        <div className="blob pointer-events-none absolute -left-20 top-10 h-72 w-72 rounded-full bg-brand-500/25" />
        <div
          className="blob pointer-events-none absolute -right-16 top-1/3 h-80 w-80 rounded-full bg-emerald-500/20"
          style={{ animationDelay: '2.5s' }}
        />
        <div
          className="blob pointer-events-none absolute bottom-8 left-1/3 h-56 w-56 rounded-full bg-cyan-400/15"
          style={{ animationDelay: '4s' }}
        />

        {/* Kartu login */}
        <div className="relative z-10 w-full max-w-md animate-fade-in rounded-3xl border border-white/60 bg-white/95 p-7 shadow-2xl backdrop-blur-xl sm:p-8">
          {/* Brand */}
          <div className="mb-5 flex flex-col items-center text-center">
            <span className="relative mb-3 grid h-16 w-16 place-items-center">
              <span
                className="ring-spin absolute -inset-1.5 rounded-full opacity-70 blur-md"
                style={{
                  background:
                    'conic-gradient(from 0deg, #3385fc, #10b981, #06b6d4, #3385fc)',
                }}
              />
              <span className="keep-light relative grid h-16 w-16 place-items-center overflow-hidden rounded-2xl bg-white shadow-lg ring-1 ring-slate-200">
                <img
                  src="/logos/teknik-merah.png"
                  alt="Fakultas Teknik UNISMUH"
                  className="h-12 w-12 object-contain"
                />
              </span>
            </span>
            <h1 className="text-xl font-bold text-slate-800">UNISMUH ComputeHub</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              Platform Komputasi Server Kampus · Fakultas Teknik
            </p>
          </div>

            <div className="mb-6 flex items-center justify-center gap-2.5">
              {LOGOS.map((l) => (
                <span
                  key={l.src}
                  className="keep-light grid h-10 w-10 place-items-center rounded-xl bg-white shadow-sm ring-1 ring-slate-200/80 transition hover:-translate-y-0.5 hover:shadow-md"
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
                  Username atau Email
                </label>
                <div className="relative">
                  <IconMail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    id="email"
                    type="text"
                    autoComplete="username"
                    className="input pl-10"
                    placeholder="CH12345 atau nama@unismuh.ac.id"
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

            {ssoOn && (
              <div className="mt-5">
                <div className="flex items-center gap-3">
                  <span className="h-px flex-1 bg-slate-200" />
                  <span className="text-xs font-medium text-slate-400">
                    Atau masuk dengan
                  </span>
                  <span className="h-px flex-1 bg-slate-200" />
                </div>
                <a
                  href={ssoLoginUrl()}
                  className="mt-4 flex w-full items-center justify-center gap-2.5 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-brand-400 hover:bg-slate-50"
                >
                  <img
                    src="/logos/unismuh.jpg"
                    alt=""
                    className="h-5 w-5 rounded-full object-contain"
                  />
                  Masuk dengan SSO Unismuh
                </a>
              </div>
            )}

            <p className="mt-5 text-center text-xs text-slate-400">
              Akun dibuat oleh administrator. Butuh bantuan? Hubungi admin lab / IT.
            </p>

            <div className="mt-4 text-center">
              <Link
                to="/welcome"
                className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 transition hover:text-brand-600"
              >
                ← Kembali ke Beranda
              </Link>
            </div>
          </div>
      </main>
    </div>
  )
}
