import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { IconGpu } from '../components/icons'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-[#0b1020] p-4">
      {/* Background foto Gedung UNISMUH */}
      <div
        className="absolute inset-0 scale-105 bg-cover bg-center"
        style={{
          backgroundImage:
            'url(https://s3.ap-southeast-1.amazonaws.com/maukuliah/gallery/091004/Gedung%201%20UNISMUH-thumbnail.jpg)',
        }}
      />
      {/* Overlay gelap agar teks & kartu tetap terbaca */}
      <div className="absolute inset-0 bg-gradient-to-br from-slate-950/90 via-slate-900/80 to-[#0b1020]/90" />

      {/* Glow blobs */}
      <div className="blob absolute -left-24 -top-24 h-72 w-72 rounded-full bg-brand-500/30" />
      <div
        className="blob absolute -bottom-28 -right-20 h-80 w-80 rounded-full bg-violet-500/30"
        style={{ animationDelay: '1.5s' }}
      />
      <div
        className="blob absolute bottom-10 left-1/3 h-56 w-56 rounded-full bg-cyan-400/20"
        style={{ animationDelay: '3s' }}
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="relative mb-3 grid h-16 w-16 place-items-center">
            <span
              className="ring-spin absolute -inset-1 rounded-2xl opacity-70 blur-md"
              style={{
                background:
                  'conic-gradient(from 0deg, #3385fc, #7c3aed, #06b6d4, #3385fc)',
              }}
            />
            <span className="relative grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-indigo-500 text-white shadow-2xl shadow-brand-600/50">
              <IconGpu className="h-8 w-8" />
            </span>
          </span>
          <h1 className="text-2xl font-bold text-white">UNISMUH ComputeHub</h1>
          <p className="text-sm text-slate-400">
            Academic High-Performance Computing Platform
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Informatics · Universitas Muhammadiyah Makassar
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-2xl border border-white/10 bg-white/10 p-6 shadow-2xl backdrop-blur-2xl"
        >
          <div>
            <label
              className="mb-1 block text-sm font-medium text-slate-200"
              htmlFor="email"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              className="input"
              placeholder="nama@unismuh.ac.id"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div>
            <label
              className="mb-1 block text-sm font-medium text-slate-200"
              htmlFor="password"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              className="input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {error && (
            <div className="rounded-lg bg-rose-500/15 px-3 py-2 text-sm text-rose-200 ring-1 ring-inset ring-rose-400/30">
              {error}
            </div>
          )}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Masuk…' : 'Masuk'}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-slate-500">
          Akun dibuat oleh administrator. Hubungi admin lab bila belum punya akun.
        </p>
      </div>
    </div>
  )
}
