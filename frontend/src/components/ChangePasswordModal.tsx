// Modal "Ubah Password" mandiri — wajib verifikasi password lama.
import { useState } from 'react'

import { ApiError, api } from '../lib/api'
import { IconKey, IconX } from './icons'

export default function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (next.length < 8) {
      setError('Password baru minimal 8 karakter.')
      return
    }
    if (next !== confirm) {
      setError('Konfirmasi password baru tidak cocok.')
      return
    }
    if (next === current) {
      setError('Password baru harus berbeda dari password lama.')
      return
    }
    setBusy(true)
    try {
      await api.changePassword(current, next)
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Gagal mengubah password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
          <IconKey className="h-4 w-4 text-brand-500" />
          <span className="flex-1 text-sm font-semibold text-slate-700">Ubah Password</span>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>

        {done ? (
          <div className="space-y-3 p-5 text-center">
            <p className="text-sm text-emerald-700">Password berhasil diubah.</p>
            <button onClick={onClose} className="btn-primary mx-auto">
              Selesai
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3 p-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">Password lama</label>
              <input
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                type="password"
                autoComplete="current-password"
                className="input w-full"
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">
                Password baru (min. 8 karakter)
              </label>
              <input
                value={next}
                onChange={(e) => setNext(e.target.value)}
                type="password"
                autoComplete="new-password"
                className="input w-full"
                minLength={8}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">Konfirmasi password baru</label>
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                type="password"
                autoComplete="new-password"
                className="input w-full"
                required
              />
            </div>

            {error && <p className="text-sm text-rose-600">{error}</p>}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100"
              >
                Batal
              </button>
              <button type="submit" disabled={busy} className="btn-primary">
                {busy ? 'Menyimpan…' : 'Simpan'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
