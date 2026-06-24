import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import SubmitJobForm from '../components/SubmitJobForm'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import { IconClock, IconGpu, IconPlus, IconRefresh } from '../components/icons'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDuration, timeAgo } from '../lib/format'
import type { JobStatus } from '../lib/types'

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

  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState<'' | JobStatus>('')
  // Admin default melihat SEMUA job (riwayat lintas pengguna). Non-admin selalu
  // dibatasi ke job miliknya oleh backend.
  const [mineOnly, setMineOnly] = useState(false)

  const jobsQ = useQuery({
    queryKey: ['jobs', statusFilter, mineOnly],
    queryFn: () =>
      api.listJobs({
        status: statusFilter || undefined,
        mineOnly: isAdmin ? mineOnly : true,
      }),
    refetchInterval: 8000,
  })

  const queueQ = useQuery({
    queryKey: ['queue'],
    queryFn: api.getQueue,
    refetchInterval: 10000,
  })

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
            Submit &amp; pantau job — semua dijalankan di GPU.
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

      {showForm && (
        <SubmitJobForm
          onDone={() => {
            setShowForm(false)
            void qc.invalidateQueries({ queryKey: ['jobs'] })
          }}
        />
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
          onClick={() => void jobsQ.refetch()}
          className="btn-ghost ml-auto"
        >
          <IconRefresh className="h-4 w-4" />
          Refresh
        </button>
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
                      className={cn('hover:bg-slate-50', mine && 'bg-brand-50/50')}
                    >
                      <td className="table-td font-semibold text-slate-500">
                        {q.position}
                      </td>
                      <td className="table-td">
                        <Link
                          to={`/jobs/${q.job_id}`}
                          className="font-semibold text-brand-700 hover:underline"
                        >
                          {q.name}
                        </Link>
                        {mine && (
                          <span className="ml-2 text-xs text-brand-500">(Anda)</span>
                        )}
                      </td>
                      <td className="table-td text-slate-600">{q.owner_name}</td>
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

      {/* List */}
      <div className="card overflow-hidden">
        {jobsQ.isLoading ? (
          <Spinner label="Memuat job…" className="p-6" />
        ) : !jobsQ.data || jobsQ.data.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Belum ada job. Klik “Submit Job” untuk membuat yang pertama.
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
                  <th className="table-th">GPU</th>
                  <th className="table-th">Runtime</th>
                  <th className="table-th">Disubmit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobsQ.data.map((job) => (
                  <tr key={job.id} className="transition hover:bg-slate-50">
                    <td className="table-td text-slate-400">{job.id}</td>
                    <td className="table-td">
                      <Link
                        to={`/jobs/${job.id}`}
                        className="font-semibold text-brand-700 hover:underline"
                      >
                        {job.name}
                      </Link>
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
                      {job.gpu_index != null ? (
                        <span className="inline-flex items-center gap-1 text-slate-600">
                          <IconGpu className="h-4 w-4 text-brand-500" />
                          {job.gpu_index}
                        </span>
                      ) : (
                        <span className="text-slate-300">—</span>
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
                      {timeAgo(job.submitted_at)}
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

