import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import type { AccessRequest, UserRole } from '../lib/types'
import Spinner from '../components/Spinner'
import RefreshButton from '../components/RefreshButton'
import { IconActivity } from '../components/icons'

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
      {admin && <StorageRequestsPanel />}
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

// ----- Permintaan tambahan kuota penyimpanan (user -> admin) -----
function StorageRequestsPanel() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'pending' | 'all'>('pending')
  const [err, setErr] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['admin-storage-requests', tab],
    queryFn: () => api.listStorageRequests(tab, 100),
    refetchInterval: 30000,
    retry: false,
  })
  const segarkan = () => {
    void qc.invalidateQueries({ queryKey: ['admin-storage-requests'] })
    void qc.invalidateQueries({ queryKey: ['admin-audit'] })
  }
  const approve = useMutation({
    mutationFn: (v: { id: number; gb: number }) => api.approveStorageRequest(v.id, Math.round(v.gb * 1024)),
    onSuccess: () => { setErr(null); segarkan() },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal menyetujui.'),
  })
  const reject = useMutation({
    mutationFn: (v: { id: number; note: string }) => api.rejectStorageRequest(v.id, v.note),
    onSuccess: () => { setErr(null); segarkan() },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal menolak.'),
  })
  const rows = q.data ?? []
  const gb = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`)
  const belumAda = q.error instanceof ApiError && q.error.status === 404
  return (
    <div className="space-y-3" id="kuota" data-testid="storage-requests">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconActivity className="h-5 w-5 text-brand-600" />
          Permintaan Kuota Penyimpanan
          {tab === 'pending' && rows.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 text-xs font-semibold text-amber-700">{rows.length}</span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          <select value={tab} onChange={(e) => setTab(e.target.value as 'pending' | 'all')} className="input w-auto py-1 text-xs" aria-label="Saring permintaan kuota">
            <option value="pending">Menunggu</option>
            <option value="all">Semua</option>
          </select>
          <RefreshButton onRefresh={() => q.refetch()} />
        </div>
      </div>
      {err && <p className="text-sm text-rose-600">{err}</p>}
      <div className="card overflow-hidden">
        {q.isLoading ? (
          <Spinner label="Memuat permintaan…" className="p-6" />
        ) : belumAda ? (
          <p className="p-6 text-sm text-amber-700">Backend belum memuat modul permintaan kuota; aktif setelah backend diperbarui.</p>
        ) : rows.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">
            {tab === 'pending' ? 'Tidak ada permintaan yang menunggu.' : 'Belum ada permintaan.'}
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm" data-request-id={r.id}>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-slate-800">
                    #{r.user_id} {r.user_name || r.user_email}
                    <span className="ml-2 text-xs font-normal text-slate-400">{r.user_role} · {formatDateTime(r.created_at)}</span>
                  </p>
                  <p className="text-slate-600">
                    Minta <b>{gb(r.requested_mb)}</b> (sekarang {gb(r.current_quota_mb)}, terpakai {gb(r.used_mb)})
                  </p>
                  <p className="mt-0.5 whitespace-pre-wrap text-xs text-slate-500">{r.reason}</p>
                  {r.status !== 'pending' && (
                    <p className="mt-1 text-xs">
                      <span className={cn('badge', r.status === 'approved' ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-rose-50 text-rose-700 ring-rose-600/20')}>
                        {r.status === 'approved' ? `Disetujui ${gb(r.granted_mb ?? 0)}` : 'Ditolak'}
                      </span>
                      <span className="ml-2 text-slate-400">oleh {r.decided_by_email}{r.decision_note ? ` — ${r.decision_note}` : ''}</span>
                    </p>
                  )}
                </div>
                {r.status === 'pending' && (
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      className="btn-primary px-3 py-1.5 text-xs"
                      disabled={approve.isPending}
                      onClick={() => {
                        const v = window.prompt(`Setujui: kuota baru untuk ${r.user_name || r.user_email} (GB)`, String(Math.round(r.requested_mb / 1024)))
                        if (v == null) return
                        const n = Number(v)
                        if (!Number.isFinite(n) || n <= 0) { setErr('Angka GB tidak valid.'); return }
                        approve.mutate({ id: r.id, gb: n })
                      }}
                    >
                      Setujui
                    </button>
                    <button
                      type="button"
                      className="btn-ghost px-3 py-1.5 text-xs text-rose-600"
                      disabled={reject.isPending}
                      onClick={() => {
                        const note = window.prompt('Alasan penolakan (dikirim ke pemohon):', 'Rapikan berkas yang tidak terpakai terlebih dahulu.')
                        if (note == null) return
                        reject.mutate({ id: r.id, note: note.trim() })
                      }}
                    >
                      Tolak
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
