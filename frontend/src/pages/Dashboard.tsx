import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import AreaChart from '../components/AreaChart'
import CountUp from '../components/CountUp'
import GpuCard from '../components/GpuCard'
import ProgressBar from '../components/ProgressBar'
import Spinner from '../components/Spinner'
import StatCard from '../components/StatCard'
import {
  IconActivity,
  IconCheck,
  IconClock,
  IconCpu,
  IconGpu,
  IconMemory,
  IconRefresh,
  IconShield,
  IconX,
} from '../components/icons'
import { api } from '../lib/api'
import { cn, formatMB, pct } from '../lib/format'

const HISTORY_LEN = 30

function PolicyItem({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span
        className={cn(
          'grid h-5 w-5 shrink-0 place-items-center rounded-full ring-1',
          ok
            ? 'bg-emerald-100 text-emerald-700 ring-emerald-600/20'
            : 'bg-slate-100 text-slate-400 ring-slate-300/40',
        )}
      >
        {ok ? <IconCheck className="h-3.5 w-3.5" /> : <IconX className="h-3.5 w-3.5" />}
      </span>
      <span className="text-slate-600">{label}</span>
    </div>
  )
}

export default function Dashboard() {
  const overviewQ = useQuery({
    queryKey: ['overview'],
    queryFn: api.overview,
    refetchInterval: 2500,
  })
  const capQ = useQuery({
    queryKey: ['capabilities'],
    queryFn: api.capabilities,
    refetchInterval: 4000,
  })

  const [history, setHistory] = useState<Record<number, number[]>>({})
  const [cpuHist, setCpuHist] = useState<number[]>([])
  const [ramHist, setRamHist] = useState<number[]>([])
  const ov = overviewQ.data

  useEffect(() => {
    if (!ov) return
    const s = ov.system
    setCpuHist((p) => [...p, s.cpu_percent].slice(-HISTORY_LEN))
    setRamHist((p) =>
      [...p, pct(s.memory_used_mb, s.memory_total_mb)].slice(-HISTORY_LEN),
    )
    setHistory((prev) => {
      const next = { ...prev }
      for (const g of s.gpus) {
        next[g.index] = [...(next[g.index] ?? []), g.util_percent].slice(
          -HISTORY_LEN,
        )
      }
      return next
    })
  }, [ov])

  if (overviewQ.isLoading || !ov) {
    return <Spinner label="Memuat dashboard…" className="p-6" />
  }

  const sys = ov.system
  const cap = capQ.data
  const busyGpus = cap?.busy_gpus ?? []
  const memPct = pct(sys.memory_used_mb, sys.memory_total_mb)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">
            ComputeHub Control Center
          </h1>
          <p className="text-sm text-slate-500">
            Real-Time Resource Monitoring &amp; Job Scheduling
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'badge',
              ov.enforce_gpu
                ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
                : 'bg-amber-50 text-amber-700 ring-amber-600/20',
            )}
          >
            <IconGpu className="h-3.5 w-3.5" />
            {ov.enforce_gpu ? 'GPU wajib (CPU ditolak)' : 'GPU tidak dipaksa'}
          </span>
          <button
            onClick={() => {
              void overviewQ.refetch()
              void capQ.refetch()
            }}
            className="btn-ghost"
          >
            <IconRefresh className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Job stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Antri"
          value={<CountUp value={ov.jobs_queued} />}
          icon={<IconClock />}
          accent="bg-amber-50 text-amber-600"
          delay={0}
        />
        <StatCard
          label="Berjalan"
          value={<CountUp value={ov.jobs_running} />}
          sub={`maks ${ov.max_concurrent_jobs} paralel`}
          icon={<IconActivity />}
          accent="bg-brand-50 text-brand-600"
          delay={80}
        />
        <StatCard
          label="Sukses"
          value={<CountUp value={ov.jobs_succeeded} />}
          icon={<IconCheck />}
          accent="bg-emerald-50 text-emerald-600"
          delay={160}
        />
        <StatCard
          label="Gagal"
          value={<CountUp value={ov.jobs_failed} />}
          icon={<IconX />}
          accent="bg-rose-50 text-rose-600"
          delay={240}
        />
      </div>

      {/* System CPU / RAM */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card-pad space-y-3">
          <div className="flex items-center gap-2 text-slate-700">
            <IconCpu className="h-5 w-5 text-brand-600" />
            <span className="font-semibold">CPU</span>
            <span className="ml-auto text-sm text-slate-500">
              {sys.cpu_cores} core
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">Utilisasi</span>
            <span className="font-semibold">
              <CountUp value={sys.cpu_percent} decimals={1} />%
            </span>
          </div>
          <ProgressBar value={sys.cpu_percent} />
          <AreaChart data={cpuHist} max={100} height={120} color="#3b82f6" />
          <p className="text-xs text-slate-400">
            Orkestrasi memakai CPU minimal — komputasi job dijalankan di GPU.
          </p>
        </div>

        <div className="card-pad space-y-3">
          <div className="flex items-center gap-2 text-slate-700">
            <IconMemory className="h-5 w-5 text-brand-600" />
            <span className="font-semibold">Memori (RAM)</span>
            <span className="ml-auto text-sm text-slate-500">
              {formatMB(sys.memory_total_mb)}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">Terpakai</span>
            <span className="font-semibold">
              {formatMB(sys.memory_used_mb)} ({memPct.toFixed(0)}%)
            </span>
          </div>
          <ProgressBar value={memPct} />
          <AreaChart data={ramHist} max={100} height={120} color="#8b5cf6" />
        </div>
      </div>

      {/* GPUs */}
      <div>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconGpu className="h-5 w-5 text-brand-600" />
          GPU ({sys.gpus.length})
        </h2>
        {sys.gpus.length === 0 ? (
          <div className="card-pad text-sm text-slate-500">
            Tidak ada GPU terdeteksi.
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {sys.gpus.map((g, i) => (
              <GpuCard
                key={g.index}
                gpu={g}
                busy={busyGpus.includes(g.index)}
                history={history[g.index]}
                delay={i * 90}
              />
            ))}
          </div>
        )}
      </div>

      {/* Kebijakan eksekusi */}
      {cap && (
        <div className="card-pad">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-slate-800">
            <IconShield className="h-5 w-5 text-brand-600" />
            Kebijakan eksekusi
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <PolicyItem ok={cap.enforce_gpu} label="GPU diwajibkan (CPU ditolak)" />
            <PolicyItem ok={!cap.allow_cpu_fallback} label="Tanpa fallback CPU" />
            <PolicyItem ok={cap.require_cuda_preflight} label="Preflight CUDA aktif" />
            <PolicyItem ok={cap.job_execution_enabled} label="Eksekusi job aktif" />
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <span className="text-slate-400">Maks paralel:</span>
              <b>{cap.max_concurrent_jobs}</b>
            </div>
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <span className="text-slate-400">Min VRAM bebas:</span>
              <b>{formatMB(cap.gpu_min_free_memory_mb)}</b>
            </div>
          </div>
          {cap.policy && (
            <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
              <b>Mahasiswa</b>: maks {cap.policy.student_max_concurrent_jobs} job
              paralel, prioritas terkunci (urutan submit). <b>Dosen</b>: bebas
              (prioritas s/d {cap.policy.dosen_max_priority}). Git:{' '}
              {cap.policy.allowed_git_hosts.join(', ')}.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
