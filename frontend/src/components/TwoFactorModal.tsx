// Modal kelola 2FA (TOTP opt-in): aktifkan dengan QR + verifikasi kode,
// tampilkan kode pemulihan sekali, nonaktifkan / buat ulang kode pemulihan.
import { useEffect, useState } from 'react'

import { ApiError, api } from '../lib/api'
import type { MfaStatus } from '../lib/types'
import { IconCheck, IconCopy, IconDownload, IconShield, IconX } from './icons'

type Mode = 'loading' | 'overview' | 'setup' | 'recovery' | 'disable' | 'regen'

function RecoveryCodes({ codes }: { codes: string[] }) {
  const text = codes.join('\n')
  const copy = () => void navigator.clipboard?.writeText(text)
  const download = () => {
    const blob = new Blob([`Kode pemulihan 2FA ComputeHub\n\n${text}\n`], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'computehub-recovery-codes.txt'
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-1.5 rounded-lg bg-slate-50 p-3 font-mono text-sm text-slate-700 ring-1 ring-slate-200">
        {codes.map((c) => (
          <span key={c} className="select-all">{c}</span>
        ))}
      </div>
      <div className="flex gap-2">
        <button onClick={copy} type="button" className="btn-ghost flex-1 justify-center">
          <IconCopy className="h-4 w-4" /> Salin
        </button>
        <button onClick={download} type="button" className="btn-ghost flex-1 justify-center">
          <IconDownload className="h-4 w-4" /> Unduh
        </button>
      </div>
      <p className="text-xs text-amber-700">
        Simpan di tempat aman. Kode ini hanya muncul sekali dan dipakai bila Anda
        kehilangan aplikasi authenticator. Setiap kode hanya sekali pakai.
      </p>
    </div>
  )
}

export default function TwoFactorModal({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<Mode>('loading')
  const [status, setStatus] = useState<MfaStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Enrolment
  const [qr, setQr] = useState('')
  const [secret, setSecret] = useState('')
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState<string[]>([])
  // Disable / regen
  const [password, setPassword] = useState('')

  const loadStatus = async () => {
    try {
      const s = await api.getMfaStatus()
      setStatus(s)
      setMode('overview')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Gagal memuat status 2FA.')
      setMode('overview')
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  const startSetup = async () => {
    setError(null)
    setBusy(true)
    try {
      const s = await api.mfaSetup()
      setQr(s.qr_svg)
      setSecret(s.secret)
      setCode('')
      setMode('setup')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Gagal memulai pendaftaran 2FA.')
    } finally {
      setBusy(false)
    }
  }

  const confirmEnable = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = await api.mfaEnable(code.trim())
      setRecovery(res.recovery_codes)
      setMode('recovery')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Kode salah.')
    } finally {
      setBusy(false)
    }
  }

  const doDisable = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await api.mfaDisable(password, code.trim())
      setPassword('')
      setCode('')
      await loadStatus()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Gagal menonaktifkan 2FA.')
    } finally {
      setBusy(false)
    }
  }

  const doRegen = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = await api.mfaRegenRecovery(password, code.trim())
      setPassword('')
      setCode('')
      setRecovery(res.recovery_codes)
      setMode('recovery')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Gagal membuat ulang kode pemulihan.')
    } finally {
      setBusy(false)
    }
  }

  const body = () => {
    if (mode === 'loading') return <p className="p-5 text-center text-sm text-slate-500">Memuat…</p>

    if (mode === 'recovery') {
      return (
        <div className="space-y-4 p-4">
          <p className="text-sm font-medium text-emerald-700">
            <IconCheck className="mr-1 inline h-4 w-4" />
            2FA aktif. Berikut kode pemulihan Anda:
          </p>
          <RecoveryCodes codes={recovery} />
          <button onClick={() => void loadStatus()} className="btn-primary w-full">
            Saya sudah menyimpan, selesai
          </button>
        </div>
      )
    }

    if (mode === 'setup') {
      return (
        <form onSubmit={confirmEnable} className="space-y-3 p-4">
          <p className="text-sm text-slate-600">
            Pindai QR ini dengan aplikasi authenticator (Google Authenticator, Authy, dll),
            lalu masukkan kode 6 digit untuk mengaktifkan.
          </p>
          {qr && (
            <div className="flex justify-center">
              <img src={qr} alt="QR 2FA" className="h-44 w-44 rounded-lg ring-1 ring-slate-200" />
            </div>
          )}
          <p className="break-all text-center text-xs text-slate-400">
            Manual: <span className="select-all font-mono">{secret}</span>
          </p>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            className="input w-full text-center tracking-[0.3em]"
            required
          />
          {error && <p className="text-sm text-rose-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => void loadStatus()} className="rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100">
              Batal
            </button>
            <button type="submit" disabled={busy} className="btn-primary">
              {busy ? 'Memverifikasi…' : 'Aktifkan'}
            </button>
          </div>
        </form>
      )
    }

    if (mode === 'disable' || mode === 'regen') {
      const isDisable = mode === 'disable'
      return (
        <form onSubmit={isDisable ? doDisable : doRegen} className="space-y-3 p-4">
          <p className="text-sm text-slate-600">
            {isDisable
              ? 'Masukkan password dan kode 2FA (atau kode pemulihan) untuk menonaktifkan 2FA.'
              : 'Masukkan password dan kode authenticator untuk membuat ulang kode pemulihan. Kode lama akan hangus.'}
          </p>
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            autoComplete="current-password"
            placeholder="Password"
            className="input w-full"
            required
          />
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder={isDisable ? 'Kode 2FA / pemulihan' : 'Kode 2FA'}
            className="input w-full text-center tracking-[0.2em]"
            required={!isDisable}
          />
          {error && <p className="text-sm text-rose-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => { setError(null); setMode('overview') }} className="rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100">
              Batal
            </button>
            <button type="submit" disabled={busy} className={isDisable ? 'btn-danger' : 'btn-primary'}>
              {busy ? 'Memproses…' : isDisable ? 'Nonaktifkan' : 'Buat ulang'}
            </button>
          </div>
        </form>
      )
    }

    // overview
    const s = status
    if (s && !s.supported) {
      return (
        <div className="space-y-3 p-5 text-sm text-slate-600">
          2FA hanya tersedia untuk akun yang masuk dengan username/password. Akun SSO
          Unismuh mengelola keamanan lewat akun kampus.
          {error && <p className="text-rose-600">{error}</p>}
        </div>
      )
    }
    return (
      <div className="space-y-4 p-4">
        {error && <p className="text-sm text-rose-600">{error}</p>}
        {s?.enabled ? (
          <>
            <div className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700 ring-1 ring-emerald-600/20">
              <IconCheck className="mr-1 inline h-4 w-4" />
              2FA aktif. Sisa kode pemulihan: <strong>{s.recovery_remaining}</strong>
            </div>
            <div className="flex flex-col gap-2">
              <button onClick={() => { setError(null); setMode('regen') }} className="btn-ghost justify-center">
                Buat ulang kode pemulihan
              </button>
              <button onClick={() => { setError(null); setMode('disable') }} className="btn-danger justify-center">
                Nonaktifkan 2FA
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-slate-600">
              Tambahkan lapisan keamanan kedua: setelah password benar, login juga
              meminta kode dari aplikasi authenticator di ponsel Anda.
            </p>
            <button onClick={() => void startSetup()} disabled={busy} className="btn-primary w-full">
              {busy ? 'Menyiapkan…' : 'Aktifkan 2FA'}
            </button>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-sm overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
          <IconShield className="h-4 w-4 text-brand-500" />
          <span className="flex-1 text-sm font-semibold text-slate-700">Autentikasi Dua Faktor (2FA)</span>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>
        {body()}
      </div>
    </div>
  )
}
