import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import RefreshButton from '../components/RefreshButton'
import SubmitJobForm from '../components/SubmitJobForm'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import { IconClock, IconGpu, IconPlus, IconRefresh, IconTrash } from '../components/icons'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDuration, timeAgo } from '../lib/format'
import type { Job, JobStatus } from '../lib/types'

const STATUS_OPTIONS: { value: '' | JobStatus; label: string }[] = [
  { value: '', label: 'Semua status' },
  { value: 'queued', label: 'Antri' },
  { value: 'running', label: 'Berjalan' },
  { value: 'succeeded', label: 'Sukses' },
  { value: 'failed', label: 'Gagal' },
  { value: 'cancelled', label: 'Dibatalkan' },
]

export default function Jobs() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const isAdmin = user?.role === 'admin'
  const navigate = useNavigate()

  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState<'' | JobStatus>('')
  // Admin default melihat SEMUA job (riwayat lintas pengguna). Non-admin selalu
  // dibatasi ke job miliknya oleh backend.
  const [mineOnly, setMineOnly] = useState(false)
  // Tampilan "Sampah": job yang di-soft-delete (bisa dikembalikan).
  const [trash, setTrash] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)

  const isSuperadmin = !!user?.is_superadmin
  // HAPUS: super admin (semua job) ATAU pemilik NON-admin (miliknya). Admin biasa TIDAK.
  const canDelete = (job: Job) =>
    isSuperadmin || (job.user_id === user?.id && user?.role !== 'admin')
  // KEMBALIKAN: seperti hapus, PLUS admin biasa boleh mengembalikan job mahasiswa/dosen
  // (menolong user), selama belum terhapus permanen.
  const canRestore = (job: Job) =>
    canDelete(job) ||
    (user?.role === 'admin' &&
      (job.owner_role === 'mahasiswa' || job.owner_role === 'dosen'))

  const jobsQ = useQuery({
    queryKey: ['jobs', statusFilter, mineOnly, trash],
    queryFn: () =>
      api.listJobs({
        status: statusFilter || undefined,
        mineOnly: isAdmin ? mineOnly : true,
        deleted: trash,
      }),
    refetchInterval: 8000,
  })

  const act = async (id: number, fn: () => Promise<unknown>) => {
    setBusyId(id)
    try {
      await fn()
      await qc.invalidateQueries({ queryKey: ['jobs'] })
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Operasi gagal.')
    } finally {
      setBusyId(null)
    }
  }
  const onDelete = (job: Job) => {
    if (window.confirm(`Pindahkan job "${job.name}" ke Sampah? Bisa dikembalikan nanti.`))
      void act(job.id, () => api.deleteJob(job.id))
  }
  const onRestore = (job: Job) => void act(job.id, () => api.restoreJob(job.id))
  const onPurge = (job: Job) => {
    if (
      window.confirm(
        `Hapus PERMANEN job "${job.name}"? File & data terhapus selamanya dan TIDAK bisa dikembalikan.`,
      )
    )
      void act(job.id, () => api.purgeJob(job.id))
  }

  const queueQ = useQuery({
    queryKey: ['queue'],
    queryFn: api.getQueue,
    refetchInterval: 10000,
  })

  const poolsQ = useQuery({
    queryKey: ['pools'],
    queryFn: api.getPools,
    refetchInterval: 10000,
  })
  const pools = poolsQ.data

  const usageQ = useQuery({
    queryKey: ['usage'],
    queryFn: api.getUsage,
    refetchInterval: 15000,
    enabled: user?.role === 'mahasiswa',
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">Jobs</h1>
          <p className="text-sm text-slate-500">
            Submit &amp; pantau job — pilih GPU atau CPU, sistem mengatur antrian.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {usageQ.data?.quota_enabled && (
            <div className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs text-slate-600">
              Kuota GPU 24 jam:{' '}
              <b
                className={cn(
                  usageQ.data.remaining_seconds != null &&
                    usageQ.data.remaining_seconds <= 0 &&
                    'text-rose-600',
                )}
              >
                {formatDuration(usageQ.data.used_seconds)}
              </b>{' '}
              / {formatDuration(usageQ.data.quota_seconds)}
            </div>
          )}
          <button onClick={() => setShowForm((v) => !v)} className="btn-primary">
            <IconPlus className="h-4 w-4" />
            Submit Job
          </button>
        </div>
      </div>

      {/* Info: mana yang tetap jalan saat laptop dimatikan (untuk user awam) */}
      <div className="rounded-xl border border-slate-200 bg-gradient-to-r from-emerald-50/70 to-violet-50/60 px-4 py-3 text-sm text-slate-600">
        <p className="mb-2 font-semibold text-slate-700">
          Mana yang tetap berjalan saat laptop dimatikan?
        </p>
        <div className="space-y-1.5">
          <p className="flex items-start gap-2">
            <span className="mt-0.5 inline-flex shrink-0 items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
              Latar belakang
            </span>
            <span>
              <b>Job batch</b> (lewat <b>Submit Job</b>) berjalan di server — tetap
              lanjut walau laptop dimatikan atau koneksi terputus. ✅
            </span>
          </p>
          <p className="flex items-start gap-2">
            <span className="mt-0.5 inline-flex shrink-0 items-center rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700">
              Interaktif
            </span>
            <span>
              <b>Notebook interaktif</b> butuh koneksi aktif — berhenti jika laptop
              mati atau tab ditutup.
            </span>
          </p>
        </div>
      </div>

      {showForm && (
        <SubmitJobForm
          onDone={() => {
            setShowForm(false)
            void qc.invalidateQueries({ queryKey: ['jobs'] })
          }}
        />
      )}

      {/* Status pool resource (CPU & GPU) */}
      {pools && (
        <div className="flex flex-wrap gap-3">
          <div
            className={cn(
              'flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium ring-1 ring-inset',
              pools.gpu.full
                ? 'bg-amber-50 text-amber-700 ring-amber-600/20'
                : 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
            )}
          >
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                pools.gpu.full ? 'bg-amber-500' : 'bg-emerald-500',
              )}
            />
            GPU{' '}
            {pools.gpu.full
              ? 'sedang penuh'
              : `tersedia (${pools.gpu.available ? pools.gpu.count : 0}/${pools.gpu.count})`}
          </div>
          {pools.allow_cpu_jobs && (
            <div
              className={cn(
                'flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium ring-1 ring-inset',
                pools.cpu.full
                  ? 'bg-amber-50 text-amber-700 ring-amber-600/20'
                  : 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
              )}
            >
              <span
                className={cn(
                  'h-2 w-2 rounded-full',
                  pools.cpu.full ? 'bg-amber-500' : 'bg-emerald-500',
                )}
              />
              CPU{' '}
              {pools.cpu.full
                ? 'sedang penuh'
                : `tersedia (${pools.cpu.free}/${pools.cpu.total} core)`}
            </div>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          className="input max-w-[200px]"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as '' | JobStatus)}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {isAdmin && (
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={mineOnly}
              onChange={(e) => setMineOnly(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Hanya job saya
          </label>
        )}
        <button
          onClick={() => setTrash((v) => !v)}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition',
            trash
              ? 'bg-rose-50 text-rose-700 ring-rose-600/20 hover:bg-rose-100'
              : 'text-slate-600 ring-slate-200 hover:bg-slate-50',
          )}
        >
          <IconTrash className="h-4 w-4" />
          {trash ? 'Keluar dari Sampah' : 'Sampah'}
        </button>
        <RefreshButton onRefresh={() => jobsQ.refetch()} className="ml-auto" />
      </div>

      {/* Antrian & ETA */}
      {queueQ.data && queueQ.data.length > 0 && (
        <div className="card overflow-hidden">
          <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700">
            <IconClock className="h-4 w-4 text-brand-600" />
            Antrian — perkiraan giliran ({queueQ.data.length})
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="table-th">#</th>
                  <th className="table-th">Job</th>
                  <th className="table-th">Pemilik</th>
                  <th className="table-th">Perangkat</th>
                  <th className="table-th">Perkiraan durasi</th>
                  <th className="table-th">Mulai dalam</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {queueQ.data.map((q) => {
                  const mine = q.user_id === user?.id
                  return (
                    <tr
                      key={q.job_id}
                      onClick={() => navigate(`/jobs/${q.job_id}`)}
                      className={cn('cursor-pointer hover:bg-slate-50', mine && 'bg-brand-50/50')}
                    >
                      <td className="table-td font-semibold text-slate-500">
                        {q.position}
                      </td>
                      <td className="table-td">
                        <Link
                          to={`/jobs/${q.job_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="font-semibold text-brand-700 hover:underline"
                        >
                          {q.name}
                        </Link>
                        {mine && (
                          <span className="ml-2 text-xs text-brand-500">(Anda)</span>
                        )}
                      </td>
                      <td className="table-td text-slate-600">{q.owner_name}</td>
                      <td className="table-td">
                        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                          {q.device === 'cpu' ? 'CPU' : 'GPU'}
                        </span>
                        {q.waiting_reason && (
                          <span className="ml-1.5 text-[11px] font-medium text-amber-600">
                            {q.waiting_reason === 'cpu_full'
                              ? 'CPU penuh'
                              : 'GPU penuh'}
                          </span>
                        )}
                      </td>
                      <td className="table-td text-slate-500">
                        ~{formatDuration(q.estimated_runtime_seconds)}
                      </td>
                      <td className="table-td">
                        {q.eta_seconds < 1 ? (
                          <span className="font-semibold text-emerald-600">
                            segera
                          </span>
                        ) : (
                          <span className="font-medium text-slate-700">
                            ~{formatDuration(q.eta_seconds)}
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {trash && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Job di Sampah otomatis dihapus <b>permanen setelah 7 hari</b> (menghemat disk).
          {isSuperadmin
            ? ' Sebagai super admin, Anda bisa mengembalikan atau menghapus permanen sekarang.'
            : user?.role === 'admin'
              ? ' Anda bisa mengembalikan job mahasiswa/dosen yang terhapus.'
              : ' Kembalikan sebelum terhapus permanen bila masih dibutuhkan.'}
        </p>
      )}

      {/* List */}
      <div className="card overflow-hidden">
        {jobsQ.isLoading ? (
          <Spinner label="Memuat job…" className="p-6" />
        ) : !jobsQ.data || jobsQ.data.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            {trash
              ? 'Sampah kosong.'
              : 'Belum ada job. Klik “Submit Job” untuk membuat yang pertama.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="table-th">#</th>
                  <th className="table-th">Nama</th>
                  {isAdmin && <th className="table-th">Pemilik</th>}
                  <th className="table-th">Status</th>
                  <th className="table-th">Perangkat</th>
                  <th className="table-th">Runtime</th>
                  <th className="table-th">{trash ? 'Dihapus' : 'Disubmit'}</th>
                  <th className="table-th">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobsQ.data.map((job) => (
                  <tr
                    key={job.id}
                    onClick={() => navigate(`/jobs/${job.id}`)}
                    className="cursor-pointer transition hover:bg-slate-50"
                  >
                    <td className="table-td text-slate-400">{job.id}</td>
                    <td className="table-td">
                      <Link
                        to={`/jobs/${job.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="font-semibold text-brand-700 hover:underline"
                      >
                        {job.name}
                      </Link>
                      {job.is_interactive ? (
                        <span
                          title="Butuh koneksi aktif — berhenti jika laptop dimatikan / tab ditutup"
                          className="ml-2 inline-flex items-center rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700"
                        >
                          Interaktif
                        </span>
                      ) : (
                        <span
                          title="Berjalan di server — aman walau laptop dimatikan"
                          className="ml-2 inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700"
                        >
                          Latar belakang
                        </span>
                      )}
                    </td>
                    {isAdmin && (
                      <td className="table-td text-slate-600">
                        {job.owner_name || '—'}
                      </td>
                    )}
                    <td className="table-td">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="table-td">
                      {job.device === 'cpu' ? (
                        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                          CPU
                        </span>
                      ) : job.gpu_index != null ? (
                        <span className="inline-flex items-center gap-1 text-slate-600">
                          <IconGpu className="h-4 w-4 text-brand-500" />
                          {job.gpu_index}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-slate-400">
                          <IconGpu className="h-4 w-4 text-slate-300" />
                          GPU
                        </span>
                      )}
                    </td>
                    <td className="table-td">
                      {job.actual_runtime_seconds != null
                        ? formatDuration(job.actual_runtime_seconds)
                        : job.estimated_runtime_seconds != null
                          ? `~${formatDuration(job.estimated_runtime_seconds)}`
                          : '—'}
                    </td>
                    <td className="table-td text-slate-500">
                      {trash && job.deleted_at
                        ? timeAgo(job.deleted_at)
                        : timeAgo(job.submitted_at)}
                    </td>
                    <td className="table-td" onClick={(e) => e.stopPropagation()}>
                      {trash ? (
                        <div className="flex items-center gap-1.5">
                          {canRestore(job) && (
                            <button
                              onClick={() => onRestore(job)}
                              disabled={busyId === job.id}
                              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-600/20 transition hover:bg-emerald-50 disabled:opacity-40"
                            >
                              <IconRefresh className="h-3.5 w-3.5" /> Kembalikan
                            </button>
                          )}
                          {isSuperadmin && (
                            <button
                              onClick={() => onPurge(job)}
                              disabled={busyId === job.id}
                              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-rose-700 ring-1 ring-rose-600/20 transition hover:bg-rose-50 disabled:opacity-40"
                            >
                              <IconTrash className="h-3.5 w-3.5" /> Hapus permanen
                            </button>
                          )}
                          {!canRestore(job) && !isSuperadmin && (
                            <span className="text-xs text-slate-300">—</span>
                          )}
                        </div>
                      ) : canDelete(job) ? (
                        <button
                          onClick={() => onDelete(job)}
                          disabled={busyId === job.id}
                          title="Hapus (pindah ke Sampah)"
                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-rose-600 ring-1 ring-rose-200 transition hover:bg-rose-50 disabled:opacity-40"
                        >
                          <IconTrash className="h-3.5 w-3.5" /> Hapus
                        </button>
                      ) : (
                        <span className="text-xs text-slate-300">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

