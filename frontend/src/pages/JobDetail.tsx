import { useEffect, useRef, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import RefreshButton from '../components/RefreshButton'
import Sparkline from '../components/Sparkline'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import {
  IconActivity,
  IconArrowLeft,
  IconDownload,
  IconGpu,
  IconX,
} from '../components/icons'
import { api } from '../lib/api'
import { formatDateTime, formatDuration, formatMB } from '../lib/format'
import type { JobStatus } from '../lib/types'

const TERMINAL: JobStatus[] = ['succeeded', 'failed', 'cancelled']

export default function JobDetail() {
  const { id } = useParams()
  const jobId = Number(id)
  const qc = useQueryClient()

  const jobQ = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId),
    refetchInterval: (q) =>
      q.state.data && TERMINAL.includes(q.state.data.status) ? false : 4000,
    enabled: Number.isFinite(jobId),
  })

  const job = jobQ.data
  const isTerminal = job ? TERMINAL.includes(job.status) : false

  const logsQ = useQuery({
    queryKey: ['job-logs', jobId],
    queryFn: () => api.getJobLogs(jobId, 500),
    refetchInterval: isTerminal ? false : 3000,
    enabled: Number.isFinite(jobId),
  })

  const samplesQ = useQuery({
    queryKey: ['job-samples', jobId],
    queryFn: () => api.getJobSamples(jobId, 200),
    refetchInterval: isTerminal ? false : 6000,
    enabled: Number.isFinite(jobId),
  })

  const queueQ = useQuery({
    queryKey: ['queue'],
    queryFn: api.getQueue,
    enabled: jobQ.data?.status === 'queued',
    refetchInterval: jobQ.data?.status === 'queued' ? 8000 : false,
  })

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelJob(jobId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['job', jobId] })
      void qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const downloadMutation = useMutation({
    mutationFn: async () => {
      const blob = await api.downloadNotebook(jobId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${jobQ.data?.name ?? 'notebook'}_executed.ipynb`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    },
    onError: (err) =>
      window.alert(
        err instanceof Error ? err.message : 'Gagal mengunduh notebook.',
      ),
  })

  const outputMutation = useMutation({
    mutationFn: async () => {
      const blob = await api.downloadOutput(jobId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${jobQ.data?.name ?? 'job'}_output.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    },
    onError: (err) =>
      window.alert(
        err instanceof Error ? err.message : 'Gagal mengunduh output.',
      ),
  })

  const logRef = useRef<HTMLPreElement>(null)
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logsQ.data])

  if (jobQ.isLoading) return <Spinner label="Memuat job…" className="p-6" />
  if (jobQ.isError || !job) {
    return (
      <div className="space-y-4">
        <BackLink />
        <div className="card-pad text-rose-600">Job tidak ditemukan.</div>
      </div>
    )
  }

  const canCancel = job.status === 'queued' || job.status === 'running'

  const samples = samplesQ.data ?? []
  const vramHistory = [...samples].reverse().map((s) => s.gpu_mem_used_mb)
  const myQueue = queueQ.data?.find((q) => q.job_id === job.id)

  return (
    <div className="space-y-6">
      <BackLink />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-800">{job.name}</h1>
            <StatusBadge status={job.status} />
          </div>
          <p className="text-sm text-slate-500">Job #{job.id}</p>
        </div>
        <div className="flex gap-2">
          <RefreshButton
            onRefresh={() => Promise.all([jobQ.refetch(), logsQ.refetch()])}
          />
          {canCancel && (
            <button
              onClick={() => cancelMutation.mutate()}
              className="btn-danger"
              disabled={cancelMutation.isPending}
            >
              <IconX className="h-4 w-4" />
              {cancelMutation.isPending ? 'Membatalkan…' : 'Batalkan'}
            </button>
          )}
          {job.source_type === 'notebook' && job.status === 'succeeded' && (
            <button
              onClick={() => downloadMutation.mutate()}
              className="btn-primary"
              disabled={downloadMutation.isPending}
            >
              <IconDownload className="h-4 w-4" />
              {downloadMutation.isPending ? 'Menyiapkan…' : 'Unduh Notebook'}
            </button>
          )}
          {isTerminal && (
            <button
              onClick={() => outputMutation.mutate()}
              className="btn-ghost"
              disabled={outputMutation.isPending}
              title="Unduh log & berkas hasil (ZIP)"
            >
              <IconDownload className="h-4 w-4" />
              {outputMutation.isPending ? 'Menyiapkan…' : 'Unduh Output'}
            </button>
          )}
        </div>
      </div>

      {job.status === 'failed' ? (
        <div className="space-y-1 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          <p className="font-semibold">
            Job gagal{job.exit_code != null ? ` (exit code ${job.exit_code})` : ''}.
          </p>
          {job.error_message && <p>{job.error_message}</p>}
          <p className="text-rose-600/80">
            Penyebab lengkap ada di <b>Log</b> di bawah. Klik <b>Unduh Output</b>{' '}
            untuk mengunduh log &amp; berkas hasil.
          </p>
        </div>
      ) : (
        job.error_message && (
          <div className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
            {job.error_message}
          </div>
        )
      )}

      {job.status === 'queued' && myQueue && (
        <div className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-600/20">
          Antrian posisi <b>#{myQueue.position}</b> · perkiraan mulai{' '}
          <b>
            {myQueue.eta_seconds < 1
              ? 'segera'
              : `~${formatDuration(myQueue.eta_seconds)} lagi`}
          </b>
        </div>
      )}

      {/* Detail grid */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card-pad space-y-1">
          <DetailRow
            label="Perangkat"
            value={
              job.device === 'cpu' ? (
                <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                  CPU
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-slate-600">
                  <IconGpu className="h-4 w-4 text-brand-500" /> GPU
                </span>
              )
            }
          />
          <DetailRow
            label="GPU"
            value={
              job.gpu_index != null ? (
                <span className="inline-flex items-center gap-1">
                  <IconGpu className="h-4 w-4 text-brand-500" /> {job.gpu_index}
                </span>
              ) : (
                '—'
              )
            }
          />
          <DetailRow label="PID" value={job.pid ?? '—'} />
          <DetailRow label="Exit code" value={job.exit_code ?? '—'} />
          <DetailRow label="Prioritas" value={job.priority} />
          <DetailRow
            label="VRAM diminta"
            value={
              job.requested_gpu_memory_mb
                ? `${job.requested_gpu_memory_mb} MB`
                : '—'
            }
          />
          {job.source_type === 'git' && (
            <>
              <DetailRow
                label="Repo"
                value={
                  job.repo_url ? (
                    <a
                      href={job.repo_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-brand-700 hover:underline"
                    >
                      {job.repo_url.replace('https://', '')}
                    </a>
                  ) : (
                    '—'
                  )
                }
              />
              <DetailRow label="Ref" value={job.repo_ref ?? 'default'} />
            </>
          )}
          {(job.source_type === 'upload' || job.source_type === 'notebook') && (
            <DetailRow label="Berkas" value={job.upload_name ?? '—'} />
          )}
          <DetailRow
            label="Batas waktu"
            value={
              job.time_limit_seconds
                ? formatDuration(job.time_limit_seconds)
                : 'tanpa batas'
            }
          />
        </div>

        <div className="card-pad space-y-1">
          <DetailRow label="Disubmit" value={formatDateTime(job.submitted_at)} />
          <DetailRow label="Mulai" value={formatDateTime(job.started_at)} />
          <DetailRow label="Selesai" value={formatDateTime(job.finished_at)} />
          <DetailRow
            label="Estimasi runtime"
            value={
              job.estimated_runtime_seconds != null
                ? `~${formatDuration(job.estimated_runtime_seconds)}`
                : '—'
            }
          />
          <DetailRow
            label="Runtime aktual"
            value={formatDuration(job.actual_runtime_seconds)}
          />
        </div>
      </div>

      {/* Resource diukur sistem */}
      <div className="card-pad space-y-4">
        <div className="flex items-center gap-2 text-slate-700">
          <IconActivity className="h-5 w-5 text-brand-600" />
          <span className="font-semibold">Resource (diukur sistem)</span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="Peak VRAM" value={formatMB(job.peak_vram_mb)} />
          <Metric label="Peak RAM" value={formatMB(job.peak_ram_mb)} />
          <Metric
            label="Peak CPU"
            value={
              job.peak_cpu_percent != null
                ? `${job.peak_cpu_percent.toFixed(0)}%`
                : '—'
            }
          />
          <Metric
            label="Rata-rata GPU"
            value={
              job.avg_gpu_util_percent != null
                ? `${job.avg_gpu_util_percent.toFixed(0)}%`
                : '—'
            }
          />
        </div>
        {vramHistory.length > 1 && (
          <div>
            <p className="mb-1 text-xs text-slate-400">VRAM job — riwayat (MB)</p>
            <Sparkline
              data={vramHistory}
              max={Math.max(...vramHistory) * 1.2 || 1}
              height={48}
              stroke="#7c3aed"
            />
          </div>
        )}
      </div>

      {/* Command */}
      <div className="card-pad">
        <p className="label">{job.source_type === 'paste' ? 'Kode' : 'Perintah'}</p>
        <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700">
          {job.source_type === 'paste'
            ? job.inline_code ?? ''
            : job.command && job.command.trim()
              ? job.command
              : '(otomatis — entrypoint dideteksi sistem; lihat log)'}
        </pre>
      </div>

      {/* Logs */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
          <p className="text-sm font-semibold text-slate-700">Log</p>
          {!isTerminal && (
            <span className="flex items-center gap-1.5 text-xs text-slate-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              live
            </span>
          )}
        </div>
        <pre
          ref={logRef}
          className="max-h-[28rem] overflow-auto bg-slate-900 p-4 font-mono text-xs leading-relaxed text-slate-100"
        >
          {logsQ.data?.lines?.length
            ? logsQ.data.lines.join('\n')
            : logsQ.isLoading
              ? 'Memuat log…'
              : 'Log belum tersedia.'}
        </pre>
      </div>
    </div>
  )
}

function BackLink() {
  return (
    <Link
      to="/jobs"
      className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-800"
    >
      <IconArrowLeft className="h-4 w-4" />
      Kembali ke daftar job
    </Link>
  )
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-800">{value}</span>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3 text-center">
      <p className="text-lg font-bold text-slate-800">{value}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  )
}
