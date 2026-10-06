// Permintaan tambahan kuota penyimpanan: modal form (user) + banner global.
// Banner tampil di semua halaman untuk akun BERKUOTA (>0) mulai tahap 80%;
// merah saat 100% (mode keras: unggahan & job/sesi baru ditolak). Super admin /
// akun tanpa kuota tidak melihat apa pun.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import type { StorageQuotaStatus } from '../lib/types'
import { IconFolder, IconX } from './icons'

export const STORAGE_QUOTA_KEY = ['storage-quota'] as const

export function useStorageQuota(enabled = true) {
  const { user } = useAuth()
  return useQuery({
    queryKey: STORAGE_QUOTA_KEY,
    queryFn: api.getStorageQuota,
    enabled: enabled && !!user && !user.is_superadmin,
    refetchInterval: 60000,
    staleTime: 30000,
    retry: false,
  })
}

export function fmtGb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`
}

export function StorageQuotaRequestModal({
  status,
  onClose,
}: {
  status: StorageQuotaStatus
  onClose: () => void
}) {
  const qc = useQueryClient()
  const sekarangGb = status.quota_mb / 1024
  const [gb, setGb] = useState(String(Math.max(1, Math.ceil(sekarangGb * 2))))
  const [alasan, setAlasan] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const mut = useMutation({
    mutationFn: () => api.requestStorageQuota(Math.round(Number(gb) * 1024), alasan.trim()),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: STORAGE_QUOTA_KEY })
      onClose()
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal mengirim permintaan.'),
  })
  const angka = Number(gb)
  const valid =
    Number.isFinite(angka) && angka * 1024 > status.quota_mb && angka * 1024 <= status.request_max_mb && alasan.trim().length >= 10

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-900/60 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="quota-request-title"
    >
      <div className="card w-full max-w-md animate-fade-in" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 id="quota-request-title" className="font-semibold text-slate-800">Ajukan tambahan kuota penyimpanan</h2>
            <p className="text-xs text-slate-500">
              Kuota sekarang {fmtGb(status.quota_mb)}
              {status.used_mb != null ? ` · terpakai ${fmtGb(status.used_mb)}` : ''}. Admin akan meninjau dan Anda diberi tahu lewat notifikasi.
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100" title="Tutup" aria-label="Tutup">
            <IconX className="h-5 w-5" />
          </button>
        </div>
        <form
          className="space-y-3 px-5 py-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (valid) mut.mutate()
          }}
        >
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Kuota yang diminta (GB)</span>
            <input
              type="number"
              min={Math.floor(sekarangGb) + 1}
              max={Math.floor(status.request_max_mb / 1024)}
              step={1}
              value={gb}
              onChange={(e) => setGb(e.target.value)}
              className="input mt-1 w-full"
              required
            />
            <span className="mt-1 block text-xs text-slate-400">
              Harus lebih besar dari {fmtGb(status.quota_mb)}; maksimal {fmtGb(status.request_max_mb)}.
            </span>
          </label>
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Alasan / keperluan</span>
            <textarea
              value={alasan}
              onChange={(e) => setAlasan(e.target.value)}
              className="input mt-1 w-full"
              rows={3}
              minLength={10}
              maxLength={1000}
              placeholder="Contoh: dataset skripsi deteksi objek 15 GB + checkpoint model"
              required
            />
            <span className="mt-1 block text-xs text-slate-400">{alasan.trim().length}/1000 (min 10)</span>
          </label>
          {err && <p className="text-sm text-rose-600">{err}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-ghost">Batal</button>
            <button type="submit" disabled={!valid || mut.isPending} className="btn-primary">
              {mut.isPending ? 'Mengirim…' : 'Kirim permintaan'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function PendingRequestNote({ status }: { status: StorageQuotaStatus }) {
  const r = status.latest_request
  if (!r) return null
  if (r.status === 'pending')
    return (
      <span className="text-xs text-amber-700">
        Permintaan {fmtGb(r.requested_mb)} sedang menunggu keputusan admin.
      </span>
    )
  if (r.status === 'rejected')
    return (
      <span className="text-xs text-slate-500" title={r.decision_note || undefined}>
        Permintaan terakhir ({fmtGb(r.requested_mb)}) ditolak{r.decision_note ? `: ${r.decision_note}` : '.'}
      </span>
    )
  return null
}

export default function StorageQuotaBanner() {
  const q = useStorageQuota()
  const [open, setOpen] = useState(false)
  const s = q.data
  if (!s || s.quota_mb <= 0 || s.used_mb == null) return null
  const tahapAwal = s.stages[0] ?? 80
  if (s.percent < tahapAwal && !s.over) return null
  const penuh = s.over || s.percent >= 100
  const pending = s.latest_request?.status === 'pending'
  return (
    <>
      <div
        data-testid="storage-quota-banner"
        className={cn(
          'mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl px-4 py-3 text-sm ring-1 ring-inset',
          penuh ? 'bg-rose-50 text-rose-800 ring-rose-600/20' : 'bg-amber-50 text-amber-800 ring-amber-600/20',
        )}
      >
        <IconFolder className="h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">
            {penuh ? 'Penyimpanan penuh' : `Penyimpanan ${Math.floor(s.percent)}% terpakai`}
            <span className="ml-2 font-normal opacity-80">
              {fmtGb(s.used_mb)} dari {fmtGb(s.quota_mb)}
            </span>
          </p>
          <p className="text-xs opacity-90">
            {penuh
              ? s.hard_limit
                ? 'Unggahan serta job/notebook/Devbox baru ditolak sampai ada ruang. Berkas Anda aman; mengunduh dan menghapus tetap bisa.'
                : 'Hapus berkas yang tidak terpakai agar tidak melewati batas.'
              : 'Rapikan berkas yang tidak terpakai, atau ajukan tambahan kuota sebelum penuh.'}
            {' '}
            <PendingRequestNote status={s} />
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Link to="/storage" className="btn-ghost px-3 py-1.5 text-xs">Buka Penyimpanan</Link>
          {!pending && (
            <button type="button" onClick={() => setOpen(true)} className="btn-primary px-3 py-1.5 text-xs">
              Ajukan tambahan kuota
            </button>
          )}
        </div>
      </div>
      {open && <StorageQuotaRequestModal status={s} onClose={() => setOpen(false)} />}
    </>
  )
}
