import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import AreaChart from '../components/AreaChart'
import CountUp from '../components/CountUp'
import Spinner from '../components/Spinner'
import {
  IconBolt,
  IconChart,
  IconCpu,
  IconGpu,
  IconMemory,
  IconRefresh,
  IconThermometer,
} from '../components/icons'
import { api } from '../lib/api'
import { cn, formatMB, pct } from '../lib/format'
import type { Gpu } from '../lib/types'

const HISTORY_LEN = 60

export default function Monitor() {
  const overviewQ = useQuery({
    queryKey: ['overview'],
    queryFn: api.overview,
    refetchInterval: 2000,
  })

  const [cpuHist, setCpuHist] = useState<number[]>([])
  const [ramHist, setRamHist] = useState<number[]>([])
  const [gpuUtil, setGpuUtil] = useState<Record<number, number[]>>({})
  const [gpuVram, setGpuVram] = useState<Record<number, number[]>>({})

  const ov = overviewQ.data

  useEffect(() => {
    if (!ov) return
    const sys = ov.system
    setCpuHist((p) => [...p, sys.cpu_percent].slice(-HISTORY_LEN))
    setRamHist((p) =>
      [...p, pct(sys.memory_used_mb, sys.memory_total_mb)].slice(-HISTORY_LEN),
    )
    setGpuUtil((prev) => {
      const next = { ...prev }
      for (const g of sys.gpus) {
        next[g.index] = [...(next[g.index] ?? []), g.util_percent].slice(-HISTORY_LEN)
      }
      return next
    })
    setGpuVram((prev) => {
      const next = { ...prev }
      for (const g of sys.gpus) {
        next[g.index] = [...(next[g.index] ?? []), g.mem_used_mb].slice(-HISTORY_LEN)
      }
      return next
    })
  }, [ov])

  if (overviewQ.isLoading || !ov) {
    return <Spinner label="Memuat monitor…" className="p-6" />
  }

  const sys = ov.system
  const memPct = pct(sys.memory_used_mb, sys.memory_total_mb)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">Monitor Sistem</h1>
          <p className="text-sm text-slate-500">
            Grafik real-time CPU, memori &amp; GPU (live tiap 2 detik).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
            <span className="glow-pulse h-1.5 w-1.5 rounded-full bg-emerald-500" />
            LIVE
          </span>
          <button onClick={() => void overviewQ.refetch()} className="btn-ghost">
            <IconRefresh className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* CPU & RAM besar */}
      <div className="grid gap-5 lg:grid-cols-2">
        <BigMetric
          title="CPU"
          icon={<IconCpu className="h-5 w-5" />}
          value={sys.cpu_percent}
          suffix="%"
          subtitle={`${sys.cpu_cores} core`}
          color="#3b82f6"
          data={cpuHist}
          accent="from-brand-500 to-indigo-500"
        />
        <BigMetric
          title="Memori (RAM)"
          icon={<IconMemory className="h-5 w-5" />}
          value={memPct}
          suffix="%"
          subtitle={`${formatMB(sys.memory_used_mb)} / ${formatMB(sys.memory_total_mb)}`}
          color="#8b5cf6"
          data={ramHist}
          accent="from-violet-500 to-fuchsia-500"
        />
      </div>

      {/* GPU besar */}
      <div className="flex items-center gap-2 pt-1">
        <IconChart className="h-5 w-5 text-brand-600" />
        <h2 className="text-lg font-semibold text-slate-800">
          GPU ({sys.gpus.length})
        </h2>
      </div>

      {sys.gpus.length === 0 ? (
        <div className="card-pad text-sm text-slate-500">Tidak ada GPU terdeteksi.</div>
      ) : (
        <div className="space-y-5">
          {sys.gpus.map((g) => (
            <GpuMonitor
              key={g.index}
              gpu={g}
              util={gpuUtil[g.index] ?? []}
              vram={gpuVram[g.index] ?? []}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function BigMetric({
  title,
  icon,
  value,
  suffix,
  subtitle,
  color,
  data,
  accent,
}: {
  title: string
  icon: React.ReactNode
  value: number
  suffix: string
  subtitle: string
  color: string
  data: number[]
  accent: string
}) {
  return (
    <div className="card-pad hover-lift space-y-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              'grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br text-white shadow-lg',
              accent,
            )}
          >
            {icon}
          </span>
          <div>
            <p className="font-semibold text-slate-800">{title}</p>
            <p className="text-xs text-slate-500">{subtitle}</p>
          </div>
        </div>
        <div className="text-right">
          <span className="text-3xl font-extrabold tracking-tight text-slate-800">
            <CountUp value={value} decimals={value < 10 ? 1 : 0} />
          </span>
          <span className="text-lg font-bold text-slate-400">{suffix}</span>
        </div>
      </div>
      <AreaChart data={data} max={100} height={200} color={color} autoScale formatValue={(v) => v.toFixed(1) + '%'} />
    </div>
  )
}

function GpuMonitor({
  gpu,
  util,
  vram,
}: {
  gpu: Gpu
  util: number[]
  vram: number[]
}) {
  const memPct = pct(gpu.mem_used_mb, gpu.mem_total_mb)

  return (
    <div className="card-pad space-y-5">
      {/* Header GPU */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-indigo-500 text-white shadow-lg shadow-brand-600/30">
            <IconGpu />
          </span>
          <div>
            <p className="font-semibold text-slate-800">GPU {gpu.index}</p>
            <p className="text-xs text-slate-500">{gpu.name}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge bg-slate-100 text-slate-600 ring-slate-500/20">
            <IconThermometer className="h-3.5 w-3.5 text-rose-500" />
            {gpu.temperature_c.toFixed(0)}°C
          </span>
          <span className="badge bg-slate-100 text-slate-600 ring-slate-500/20">
            <IconBolt className="h-3.5 w-3.5 text-amber-500" />
            {gpu.power_w.toFixed(0)} W
          </span>
          <span className="badge bg-slate-100 text-slate-600 ring-slate-500/20">
            {formatMB(gpu.mem_free_mb)} bebas
          </span>
        </div>
      </div>

      {/* Dua grafik besar berdampingan */}
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-600">Utilisasi GPU</span>
            <span className="text-2xl font-extrabold text-slate-800">
              <CountUp value={gpu.util_percent} decimals={0} />
              <span className="text-base font-bold text-slate-400">%</span>
            </span>
          </div>
          <AreaChart data={util} max={100} height={180} color="#6366f1" autoScale formatValue={(v) => v.toFixed(0) + '%'} />
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-600">Memori VRAM</span>
            <span className="text-right text-sm font-bold text-slate-700">
              {formatMB(gpu.mem_used_mb)}{' '}
              <span className="text-slate-400">
                / {formatMB(gpu.mem_total_mb)} ({memPct.toFixed(0)}%)
              </span>
            </span>
          </div>
          <AreaChart
            data={vram}
            max={gpu.mem_total_mb}
            height={180}
            color="#06b6d4"
            autoScale
            formatValue={formatMB}
          />
        </div>
      </div>
    </div>
  )
}
