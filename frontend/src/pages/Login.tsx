import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { IconKey, IconMail } from '../components/icons'
import { ApiError, LOGOUT_REASON_KEY } from '../lib/api'
import { useAuth } from '../lib/auth'

const HERO_IMAGE =
  'https://s3.ap-southeast-1.amazonaws.com/maukuliah/gallery/091004/Gedung%201%20UNISMUH-thumbnail.jpg'

const LOGOS = [
  { src: '/logos/unismuh.jpg', alt: 'Universitas Muhammadiyah Makassar' },
  { src: '/logos/teknik-biru.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/unggul.png', alt: 'Akreditasi Unggul' },
  { src: '/logos/teknik-merah.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/gift.png', alt: 'GIFT UNISMUH' },
]

const FEATURES = [
  '2× NVIDIA L40S',
  'Pemantauan real-time',
  'Notebook ala Colab',
  'Antrian & kuota GPU',
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
    <div className="flex min-h-screen bg-slate-50">
      {/* ============ KIRI: Hero (tampil di layar besar) ============ */}
      <div className="relative hidden overflow-hidden lg:flex lg:w-[56%]">
        <div
          className="absolute inset-0 scale-105 bg-cover bg-center"
          style={{ backgroundImage: `url(${HERO_IMAGE})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/95 via-slate-900/85 to-[#06122b]/90" />

        <div className="blob absolute -left-24 -top-24 h-72 w-72 rounded-full bg-brand-500/30" />
        <div
          className="blob absolute -bottom-28 right-0 h-80 w-80 rounded-full bg-emerald-500/20"
          style={{ animationDelay: '2s' }}
        />
        <div
          className="blob absolute bottom-1/3 left-1/4 h-56 w-56 rounded-full bg-cyan-400/20"
          style={{ animationDelay: '4s' }}
        />

        <div className="relative z-10 flex w-full flex-col justify-between p-10 text-white xl:p-14">
          <div className="flex items-center gap-3">
            <span className="relative grid h-12 w-12 place-items-center">
              <span
                className="ring-spin absolute -inset-1 rounded-2xl opacity-70 blur-md"
                style={{
                  background:
                    'conic-gradient(from 0deg, #3385fc, #10b981, #06b6d4, #3385fc)',
                }}
              />
              <span className="relative grid h-12 w-12 place-items-center overflow-hidden rounded-2xl bg-white/95 shadow-xl">
                <img
                  src="/logos/gift.png"
                  alt="GIFT UNISMUH"
                  className="h-9 w-9 object-contain"
                />
              </span>
            </span>
            <div>
              <p className="text-sm font-semibold tracking-wide">UNISMUH Makassar</p>
              <p className="text-xs text-white/60">Fakultas Teknik · Informatika</p>
            </div>
          </div>

          <div className="max-w-lg">
            <span className="mb-4 inline-flex items-center rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/80 ring-1 ring-inset ring-white/20 backdrop-blur">
              Academic HPC Platform
            </span>
            <h1 className="text-4xl font-black leading-[1.1] xl:text-5xl">
              Ekosistem <span className="gradient-text">Komputasi GPU</span> Kampus
            </h1>
            <p className="mt-4 text-base leading-relaxed text-white/70">
              Submit kode, notebook, & proyek langsung ke GPU — terjadwal,
              terpantau, dan aman. Satu platform untuk mahasiswa, dosen, & admin.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {FEATURES.map((f) => (
                <span
                  key={f}
                  className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/80 ring-1 ring-inset ring-white/15 backdrop-blur"
                >
                  {f}
                </span>
              ))}
            </div>
          </div>

          <p className="text-xs text-white/40">
            © {new Date().getFullYear()} UNISMUH ComputeHub · Informatika, Fakultas Teknik
          </p>
        </div>
      </div>

      {/* ============ KANAN: Form ============ */}
      <div className="relative flex w-full items-center justify-center overflow-hidden p-6 sm:p-8 lg:w-[44%]">
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="blob absolute -right-24 -top-24 h-64 w-64 rounded-full bg-brand-200/50" />
          <div
            className="blob absolute -bottom-24 -left-20 h-64 w-64 rounded-full bg-emerald-200/40"
            style={{ animationDelay: '2.5s' }}
          />
        </div>

        <div className="relative w-full max-w-sm animate-fade-in">
          {/* Deret logo (seperti SINTEKMu) */}
          <div className="mb-6 flex items-center justify-center gap-2.5">
            {LOGOS.map((l) => (
              <span
                key={l.src}
                className="grid h-11 w-11 place-items-center rounded-xl bg-white shadow-sm ring-1 ring-slate-200/80 transition hover:-translate-y-0.5 hover:shadow-md"
              >
                <img src={l.src} alt={l.alt} className="h-7 w-7 object-contain" />
              </span>
            ))}
          </div>

          <div className="mb-6 text-center">
            <h2 className="gradient-text text-2xl font-bold">Selamat Datang</h2>
            <p className="mt-1 text-sm text-slate-500">
              Masuk ke{' '}
              <b className="font-semibold text-slate-700">UNISMUH ComputeHub</b>
            </p>
          </div>

          <form
            onSubmit={submit}
            className="space-y-4 rounded-2xl border border-slate-200/80 bg-white/80 p-6 shadow-xl shadow-slate-300/30 backdrop-blur-xl"
          >
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
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      className="h-4 w-4"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M3 3l18 18" strokeLinecap="round" />
                      <path
                        d="M10.6 10.6a2 2 0 002.8 2.8"
                        strokeLinecap="round"
                      />
                      <path
                        d="M9.9 4.2A10.9 10.9 0 0112 4c5 0 9.3 3.1 11 8a12.6 12.6 0 01-2.2 3.6M6.1 6.1A12.6 12.6 0 001 12c1.7 4.9 6 8 11 8 1.6 0 3.1-.3 4.5-.9"
                        strokeLinecap="round"
                      />
                    </svg>
                  ) : (
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      className="h-4 w-4"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path
                        d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
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
    </div>
  )
}
