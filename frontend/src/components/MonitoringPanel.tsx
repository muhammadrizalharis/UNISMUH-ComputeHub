import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import Spinner from './Spinner'
import { IconActivity, IconRefresh } from './icons'
import { api } from '../lib/api'
import { cn, formatDateTime } from '../lib/format'
import type { MonitoringSeriesPoint } from '../lib/types'

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('id-ID', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })
}

function fmtMs(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const ms = seconds * 1000
  if (ms < 1) return `${(ms * 1000).toFixed(0)} µs`
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)} ms`
  return `${seconds.toFixed(2)} s`
}

function fmtBytes(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = v
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`
}

function fmtUptime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const s = Math.floor(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}h ${h}j`
  if (h > 0) return `${h}j ${m}m`
  return `${m}m`
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: React.ReactNode
  sub?: string
  tone?: 'ok' | 'warn' | 'bad'
}) {
  const toneCls =
    tone === 'bad'
      ? 'text-rose-600'
      : tone === 'warn'
        ? 'text-amber-600'
        : 'text-slate-900 dark:text-slate-100'
  return (
    <div className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200/60 dark:bg-slate-800/40 dark:ring-white/5">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className={cn('mt-1 text-lg font-bold tabular-nums', toneCls)}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-400">{sub}</p>}
    </div>
  )
}

function Sparkline({
  points,
  color,
  label,
  fmt,
}: {
  points: MonitoringSeriesPoint[]
  color: string
  label: string
  fmt: (v: number) => string
}) {
  const geom = useMemo(() => {
    if (!points || points.length < 2) return null
    const W = 320
    const H = 80
    const pad = 6
    const xs = points.map((p) => p.t)
    const ys = points.map((p) => p.v)
    const xMin = Math.min(...xs)
    const xMax = Math.max(...xs)
    const yMin = Math.min(...ys)
    const yMax = Math.max(...ys)
    const xRange = xMax - xMin || 1
    const yRange = yMax - yMin || 1
    const px = (x: number) => pad + ((x - xMin) / xRange) * (W - 2 * pad)
    const py = (y: number) => pad + (1 - (y - yMin) / yRange) * (H - 2 * pad)
    const line = points.map((p) => `${px(p.t).toFixed(1)},${py(p.v).toFixed(1)}`).join(' ')
    const area = `${pad},${H - pad} ${line} ${W - pad},${H - pad}`
    return { W, H, line, area, last: ys[ys.length - 1], max: yMax, min: yMin }
  }, [points])

  return (
    <div className="rounded-xl bg-white p-3 ring-1 ring-slate-200/60 dark:bg-slate-800/40 dark:ring-white/5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-slate-600 dark:text-slate-300">{label}</p>
        {geom && <span className="text-xs font-bold tabular-nums" style={{ color }}>{fmt(geom.last)}</span>}
      </div>
      {geom ? (
        <svg viewBox={`0 0 ${geom.W} ${geom.H}`} className="mt-2 h-20 w-full" preserveAspectRatio="none">
          <polygon points={geom.area} fill={color} fillOpacity="0.08" />
          <polyline points={geom.line} fill="none" stroke={color} strokeWidth="1.5" />
        </svg>
      ) : (
        <p className="mt-4 text-center text-xs text-slate-400">Data belum cukup</p>
      )}
      {geom && (
        <div className="mt-1 flex justify-between text-[10px] text-slate-400">
          <span>min {fmt(geom.min)}</span>
          <span>max {fmt(geom.max)}</span>
        </div>
      )}
    </div>
  )
}

export default function MonitoringPanel() {
  const summaryQ = useQuery({
    queryKey: ['admin-monitoring-summary'],
    queryFn: () => api.getMonitoringSummary(),
    refetchInterval: 15000,
    retry: false,
  })
  const seriesQ = useQuery({
    queryKey: ['admin-monitoring-series'],
    queryFn: () => api.getMonitoringSeries(360, 120),
    refetchInterval: 60000,
    retry: false,
  })

  const s = summaryQ.data
  const v = s?.values

  if (summaryQ.isLoading) return <Spinner label="Memuat metrik…" className="card card-pad" />

  if (summaryQ.isError) {
    return (
      <div className="card card-pad text-sm text-rose-600">
        Gagal memuat metrik monitoring. Pastikan layanan Prometheus berjalan.
      </div>
    )
  }

  const errorRate = v?.error_rate ?? 0
  const errorTone: 'ok' | 'warn' | 'bad' = errorRate >= 5 ? 'bad' : errorRate >= 1 ? 'warn' : 'ok'
  const allUp = (s?.targets ?? []).every((t) => t.health === 'up')

  return (
    <div className="space-y-4">
      <div className="card card-pad space-y-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <IconActivity className="h-5 w-5 text-brand-500" />
            <h2 className="text-base font-bold">Observability — Metrik Backend</h2>
          </div>
          <div className="flex items-center gap-2">
            {s?.grafana_url && (
              <a
                href={s.grafana_url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-ghost text-xs"
              >
                Buka Grafana
              </a>
            )}
            <button
              onClick={() => {
                summaryQ.refetch()
                seriesQ.refetch()
              }}
              className="btn-ghost text-xs"
              title="Muat ulang"
            >
              <IconRefresh className="h-4 w-4" />
            </button>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          Data langsung dari Prometheus (diperbarui otomatis tiap 15 detik). Hanya terlihat oleh
          administrator utama.
          {s?.generated_at && ` · ${formatDateTime(s.generated_at)}`}
        </p>
      </div>

      {!s?.prometheus_reachable && (
        <div className="card card-pad text-sm text-amber-600">
          Prometheus tidak dapat dihubungi dari backend. Periksa layanan
          <code className="mx-1">computehub-prometheus.service</code>.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard label="Request / detik" value={fmtNum(v?.req_rate)} />
        <StatCard
          label="Error 5xx"
          value={`${fmtNum(errorRate, 2)}%`}
          tone={errorTone}
        />
        <StatCard label="Sedang diproses" value={fmtNum(v?.in_progress, 0)} />
        <StatCard label="Uptime proses" value={fmtUptime(v?.uptime_seconds)} />
        <StatCard label="Latensi p50" value={fmtMs(v?.latency_p50)} />
        <StatCard label="Latensi p95" value={fmtMs(v?.latency_p95)} />
        <StatCard label="Latensi p99" value={fmtMs(v?.latency_p99)} />
        <StatCard label="CPU (core)" value={fmtNum(v?.cpu_cores, 2)} />
        <StatCard label="Memori (RSS)" value={fmtBytes(v?.rss_bytes)} />
        <StatCard label="File descriptor" value={fmtNum(v?.open_fds, 0)} />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Sparkline
          points={seriesQ.data?.series.req_rate ?? []}
          color="#0ea5e9"
          label="Request/detik (6 jam)"
          fmt={(x) => fmtNum(x)}
        />
        <Sparkline
          points={seriesQ.data?.series.latency_p95 ?? []}
          color="#8b5cf6"
          label="Latensi p95 (6 jam)"
          fmt={fmtMs}
        />
        <Sparkline
          points={seriesQ.data?.series.error_rate ?? []}
          color="#e11d48"
          label="Error 5xx % (6 jam)"
          fmt={(x) => `${fmtNum(x, 1)}%`}
        />
        <Sparkline
          points={seriesQ.data?.series.rss_bytes ?? []}
          color="#059669"
          label="Memori RSS (6 jam)"
          fmt={fmtBytes}
        />
      </div>

      <div className="card card-pad space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Target scrape Prometheus
          <span
            className={cn(
              'ml-2 rounded px-1.5 py-0.5 text-[10px] font-bold',
              allUp ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700',
            )}
          >
            {allUp ? 'semua UP' : 'ada DOWN'}
          </span>
        </p>
        <div className="space-y-1">
          {(s?.targets ?? []).map((t, i) => (
            <div
              key={i}
              className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-1.5 text-sm dark:bg-slate-800/40"
            >
              <span className="font-medium">{t.job ?? '—'}</span>
              <span
                className={cn(
                  'rounded px-2 py-0.5 text-xs font-bold',
                  t.health === 'up'
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-rose-100 text-rose-700',
                )}
              >
                {t.health ?? '—'}
              </span>
            </div>
          ))}
          {(s?.targets ?? []).length === 0 && (
            <p className="text-xs text-slate-400">Belum ada target.</p>
          )}
        </div>
      </div>
    </div>
  )
}
