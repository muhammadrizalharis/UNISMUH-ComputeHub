import type { Gpu } from '../lib/types'
import { cn, formatMB, pct } from '../lib/format'
import ProgressBar from './ProgressBar'
import RadialGauge from './RadialGauge'
import Sparkline from './Sparkline'
import { IconBolt, IconGpu, IconThermometer } from './icons'

export default function GpuCard({
  gpu,
  busy,
  history,
  delay = 0,
}: {
  gpu: Gpu
  busy?: boolean
  history?: number[]
  delay?: number
}) {
  const memPct = pct(gpu.mem_used_mb, gpu.mem_total_mb)

  return (
    <div
      className={cn(
        'card-pad hover-lift animate-fade-in space-y-4',
        busy && 'ring-2 ring-brand-400/50',
      )}
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-indigo-500 text-white shadow-lg shadow-brand-600/30">
            <IconGpu />
          </span>
          <div>
            <p className="font-semibold text-slate-800">GPU {gpu.index}</p>
            <p className="text-xs text-slate-500">{gpu.name}</p>
          </div>
        </div>
        {busy ? (
          <span className="badge bg-brand-50 text-brand-700 ring-brand-600/20">
            <span className="glow-pulse h-1.5 w-1.5 rounded-full bg-brand-500" />
            dipakai job
          </span>
        ) : (
          <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
            bebas
          </span>
        )}
      </div>

      <div className="flex items-center gap-5">
        <RadialGauge value={gpu.util_percent} label="GPU" />
        <div className="flex-1 space-y-3">
          <div>
            <div className="mb-1 flex justify-between text-sm">
              <span className="text-slate-500">Memori</span>
              <span className="font-semibold text-slate-700">
                {formatMB(gpu.mem_used_mb)} / {formatMB(gpu.mem_total_mb)}
              </span>
            </div>
            <ProgressBar value={memPct} />
          </div>

          <div className="flex items-center gap-4 text-sm text-slate-600">
            <span className="inline-flex items-center gap-1.5">
              <IconThermometer className="h-4 w-4 text-rose-500" />
              {gpu.temperature_c.toFixed(0)}°C
            </span>
            <span className="inline-flex items-center gap-1.5">
              <IconBolt className="h-4 w-4 text-amber-500" />
              {gpu.power_w.toFixed(0)} W
            </span>
            <span className="ml-auto text-xs text-slate-400">
              {formatMB(gpu.mem_free_mb)} bebas
            </span>
          </div>
        </div>
      </div>

      {history && history.length > 1 && (
        <div className="pt-1">
          <p className="mb-1 text-xs text-slate-400">Utilisasi (riwayat)</p>
          <Sparkline data={history} max={100} height={40} autoScale />
        </div>
      )}
    </div>
  )
}
