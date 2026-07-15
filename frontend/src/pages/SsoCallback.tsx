import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import Spinner from '../components/Spinner'
import { setToken } from '../lib/api'
import { useAuth } from '../lib/auth'

/**
 * Halaman pendaratan setelah backend menyelesaikan callback SSO. Backend redirect
 * ke sini dengan access token di FRAGMENT (`#access_token=...`) — fragment tidak
 * dikirim ke server / tidak masuk log. Refresh token sudah dipasang sebagai cookie
 * HttpOnly oleh backend. Di sini: ambil token, simpan, muat user, lalu masuk.
 */
export default function SsoCallback() {
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const done = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true

    const raw = window.location.hash.replace(/^#/, '')
    const params = new URLSearchParams(raw)
    const err = params.get('error')
    const token = params.get('access_token')
    // Bersihkan fragment dari address bar & history (jangan tinggalkan token).
    window.history.replaceState(null, '', window.location.pathname)

    if (err) {
      setError(err)
      return
    }
    if (!token) {
      setError('Token SSO tidak ditemukan. Silakan coba lagi.')
      return
    }
    setToken(token)
    void (async () => {
      try {
        await refresh()
        navigate('/', { replace: true })
      } catch {
        setError('Gagal memuat profil. Silakan coba lagi.')
      }
    })()
  }, [navigate, refresh])

  return (
    <div className="grid min-h-screen place-items-center bg-slate-50 p-4">
      {error ? (
        <div className="w-full max-w-sm rounded-2xl bg-white p-6 text-center shadow-lg ring-1 ring-slate-200">
          <h1 className="text-lg font-semibold text-slate-800">Login SSO gagal</h1>
          <p className="mt-2 text-sm text-slate-500">{error}</p>
          <Link
            to="/login"
            className="btn-primary mt-5 inline-flex w-full items-center justify-center"
          >
            Kembali ke halaman masuk
          </Link>
        </div>
      ) : (
        <Spinner label="Menyelesaikan login SSO…" />
      )}
    </div>
  )
}
