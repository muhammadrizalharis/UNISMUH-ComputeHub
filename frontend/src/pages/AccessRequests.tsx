import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDateTime } from '../lib/format'
import type { AccessRequest, UserRole } from '../lib/types'
import Spinner from '../components/Spinner'

export default function AccessRequests() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const admin = user?.role === 'admin'
  const allowed = admin || !!user?.is_local
  const query = useQuery({
    queryKey: ['access-requests'], queryFn: api.accessRequests,
    enabled: allowed, refetchInterval: 15_000,
  })
  const create = useMutation({
    mutationFn: () => api.requestAccess(reason.trim()),
    onSuccess: () => {
      setReason('')
      setError(null)
      void qc.invalidateQueries({ queryKey: ['access-requests'] })
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Permintaan akses gagal dikirim.'),
  })
  if (!allowed) return <div className="card-pad text-rose-600">Akses ditolak.</div>
  const pending = query.data?.some((r) => r.status === 'pending') ?? false
  const submit = (e: FormEvent) => { e.preventDefault(); setError(null); create.mutate() }
  return (
    <div className="space-y-5">
      <h1 className="gradient-text text-2xl font-bold">{admin ? 'Permintaan Akses Lokal' : 'Minta Akses'}</h1>
      <p className="text-sm text-slate-500">
        {admin ? 'Tinjau permintaan pengguna Google lokal. Semua admin dapat menyetujui dan menentukan peran non-admin.'
          : user?.access_approved ? 'Akses Anda sudah disetujui. Fitur mengikuti peran dan kuota yang ditetapkan admin.'
            : 'Dashboard tetap live. Jelaskan kebutuhan Anda agar admin dapat membuka seluruh fitur sesuai peran.'}
      </p>
      {!admin && !user?.access_approved && (
        <form onSubmit={submit} className="card-pad space-y-3">
          <label htmlFor="access-reason" className="label">Alasan meminta akses</label>
          <textarea id="access-reason" className="input min-h-32" minLength={5} maxLength={2000}
            value={reason} onChange={(e) => setReason(e.target.value)} required
            disabled={pending || create.isPending || query.isLoading || query.isError}
            placeholder="Jelaskan tujuan penggunaan, misalnya penelitian atau tugas kuliah..." />
          <button className="btn-primary" disabled={pending || create.isPending || query.isLoading || query.isError}>
            {pending ? 'Menunggu keputusan admin' : create.isPending ? 'Mengirim...' : 'Kirim permintaan akses'}
          </button>
        </form>
      )}
      {(error || query.isError) && <div role="alert" className="card-pad text-rose-600">
        {error ?? (query.error instanceof ApiError ? query.error.message : 'Gagal memuat permintaan akses.')}
      </div>}
      {query.isLoading && <Spinner label="Memuat permintaan akses..." />}
      {query.data?.length === 0 && <div className="card-pad text-sm text-slate-500">Belum ada permintaan akses.</div>}
      {query.data?.map((r) => <RequestCard key={r.id} item={r} admin={admin} onDecided={() => {
        void qc.invalidateQueries({ queryKey: ['access-requests'] })
        void qc.invalidateQueries({ queryKey: ['users'] })
      }} />)}
    </div>
  )
}

function RequestCard({ item, admin, onDecided }: { item: AccessRequest; admin: boolean; onDecided: () => void }) {
  const [role, setRole] = useState<UserRole>('mahasiswa')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const decide = useMutation({
    mutationFn: (approved: boolean) => api.decideAccess(item.id, approved, approved ? role : undefined, note.trim()),
    onSuccess: () => { setError(null); onDecided() },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Gagal menyimpan keputusan.'),
  })
  const status = { pending: 'Menunggu persetujuan', approved: 'Disetujui', rejected: 'Ditolak' }[item.status]
  return (
    <div className="card-pad space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{admin ? `${item.user_name} (${item.user_email})` : `Permintaan #${item.id}`}</h2>
        <span className="badge bg-slate-100 text-slate-600">{status}</span>
      </div>
      <p className="text-xs text-slate-500">{formatDateTime(item.created_at)}</p>
      <p className="whitespace-pre-wrap break-words text-sm">{item.reason}</p>
      {item.note && <p className="text-sm text-slate-500">Catatan admin: {item.note}</p>}
      {admin && item.status === 'pending' && (
        <div className="space-y-3 border-t border-slate-100 pt-3">
          <label className="label">Peran yang diberikan
            <select className="input mt-1" value={role} disabled={decide.isPending}
              onChange={(e) => setRole(e.target.value === 'dosen' ? 'dosen' : 'mahasiswa')}>
              <option value="mahasiswa">Mahasiswa</option><option value="dosen">Dosen</option>
            </select>
          </label>
          <textarea className="input" aria-label="Catatan keputusan" maxLength={2000} value={note}
            onChange={(e) => setNote(e.target.value)} disabled={decide.isPending} placeholder="Catatan untuk pemohon (opsional)" />
          <div className="flex gap-2">
            <button className="btn-primary" disabled={decide.isPending} onClick={() => decide.mutate(true)}>Setujui akses</button>
            <button className="btn-ghost" disabled={decide.isPending} onClick={() => decide.mutate(false)}>Tolak</button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
    </div>
  )
}
