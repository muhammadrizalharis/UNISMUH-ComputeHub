import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import Spinner from '../components/Spinner'
import {
  IconActivity,
  IconArrowLeft,
  IconCpu,
  IconDownload,
  IconMemory,
  IconServer,
} from '../components/icons'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatMB } from '../lib/format'
import type { UserReport } from '../lib/types'

function mib(mb: number): string {
  return `${Math.round(mb).toLocaleString('id-ID')} MiB`
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function Card({
  title,
  icon,
  sub,
  children,
}: {
  title: string
  icon?: React.ReactNode
  sub?: string
  children: React.ReactNode
}) {
  return (
    <section className="card-pad space-y-3">
      <div className="flex items-center gap-2">
        {icon && <span className="text-brand-600">{icon}</span>}
        <h2 className="font-semibold text-slate-800">{title}</h2>
        {sub && <span className="text-xs text-slate-400">· {sub}</span>}
      </div>
      {children}
    </section>
  )
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-100 py-1.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-700">{value}</span>
    </div>
  )
}

export default function UserReportPage() {
  const { username = '' } = useParams()
  const { user } = useAuth()

  const q = useQuery({
    queryKey: ['user-report', username],
    queryFn: () => api.getUserReport(username),
    enabled: user?.role === 'admin' && !!username,
    refetchInterval: 15000,
  })

  const dl = useMutation({
    mutationFn: async () => {
      const blob = await api.downloadReportBlob(
        `/admin/report/user/${encodeURIComponent(username)}/download`,
      )
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')
      triggerDownload(blob, `laporan_${username}_${stamp}.html`)
    },
  })

  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  if (q.isLoading || !q.data) {
    return <Spinner label={`Menganalisis ${username}…`} className="p-6" />
  }

  const r: UserReport = q.data
  const s = r.system
  const st = r.status
  const main = r.processes.main

  return (
    <div className="space-y-5">
      <Link
        to="/report"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600"
      >
        <IconArrowLeft className="h-4 w-4" />
        Kembali ke Laporan
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">
            Laporan Lengkap — {r.username}
          </h1>
          <p className="text-sm text-slate-500">
            <span className="badge mr-2 bg-emerald-50 text-emerald-700 ring-emerald-600/20">
              <span className="glow-pulse h-1.5 w-1.5 rounded-full bg-emerald-500" />
              LIVE
            </span>
            Status saat ini · {r.generated_at}
          </p>
        </div>
        <button
          onClick={() => dl.mutate()}
          className="btn-primary"
          disabled={dl.isPending}
        >
          <IconDownload className="h-4 w-4" />
          {dl.isPending ? 'Menyiapkan…' : 'Unduh (HTML/PDF)'}
        </button>
      </div>

      {/* Workload */}
      <Card title="Analisis Pekerjaan (Workload)" icon={<IconActivity className="h-5 w-5" />}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge bg-brand-50 text-brand-700 ring-brand-600/20">
            {r.workload.primary}
          </span>
          {r.workload.signals.map((sig) => (
            <span
              key={sig}
              className="badge bg-slate-100 text-slate-500 ring-slate-500/20"
            >
              {sig}
            </span>
          ))}
        </div>
        {r.workload.hint && (
          <p className="text-sm text-slate-500">{r.workload.hint}</p>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Profil */}
        <Card title="Profil User" icon={<IconServer className="h-5 w-5" />}>
          <KV label="Username" value={r.profile.username} />
          <KV label="UID" value={r.profile.uid ?? '—'} />
          <KV label="Home" value={r.profile.home || '—'} />
          <KV label="Shell" value={r.profile.shell || '—'} />
          <KV label="Proses aktif" value={r.profile.processes_count} />
          {r.profile.sessions.length > 0 && (
            <div className="pt-1">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Sesi aktif
              </p>
              {r.profile.sessions.map((x, i) => (
                <p key={i} className="text-xs text-slate-500">
                  {x.terminal} · {x.host || 'lokal'} · {x.started}
                </p>
              ))}
            </div>
          )}
        </Card>

        {/* Info sistem ringkas */}
        <Card title="Informasi Sistem" icon={<IconServer className="h-5 w-5" />} sub={s.hostname}>
          <KV label="OS" value={s.os} />
          <KV label="CPU" value={`${s.cpu_cores} core`} />
          <KV label="RAM" value={formatMB(s.memory_total_mb)} />
          <KV
            label="GPU"
            value={`${s.gpus.length} × ${s.gpus[0]?.name ?? '—'}`}
          />
          <KV label="Driver / CUDA" value={`${s.driver_version} / ${s.cuda_version}`} />
        </Card>
      </div>

      {/* Status live */}
      <Card
        title="Status Resource Saat Ini"
        icon={<IconActivity className="h-5 w-5" />}
        sub={r.generated_at}
      >
        {/* 3.1 GPU */}
        <h3 className="text-sm font-semibold text-slate-600">3.1 Penggunaan GPU</h3>
        {st.gpu.length === 0 ? (
          <p className="text-sm text-slate-400">Tidak memakai GPU.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead>
                <tr>
                  <th className="table-th">GPU</th>
                  <th className="table-th text-right">VRAM (user / total)</th>
                  <th className="table-th text-right">Util</th>
                  <th className="table-th text-right">Suhu</th>
                  <th className="table-th text-right">Power</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {st.gpu.map((g) => (
                  <tr key={g.index}>
                    <td className="table-td font-semibold">GPU {g.index}</td>
                    <td className="table-td text-right">
                      {mib(g.user_vram_mb)} / {mib(g.total_vram_mb)}
                    </td>
                    <td className="table-td text-right">{g.util_percent.toFixed(0)}%</td>
                    <td className="table-td text-right">{g.temperature_c.toFixed(0)}°C</td>
                    <td className="table-td text-right">{g.power_w.toFixed(0)} W</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="grid gap-4 pt-2 sm:grid-cols-3">
          <div>
            <h3 className="mb-1 flex items-center gap-1 text-sm font-semibold text-slate-600">
              <IconMemory className="h-4 w-4" /> 3.2 RAM
            </h3>
            <KV label="User" value={`${formatMB(st.ram.user_rss_mb)} (${st.ram.percent_of_total.toFixed(1)}%)`} />
            <KV label="Sistem" value={`${formatMB(st.ram.system_used_mb)} / ${formatMB(st.ram.system_total_mb)}`} />
            <KV label="Swap" value={formatMB(st.ram.swap_used_mb)} />
          </div>
          <div>
            <h3 className="mb-1 flex items-center gap-1 text-sm font-semibold text-slate-600">
              <IconCpu className="h-4 w-4" /> 3.3 CPU
            </h3>
            <KV
              label="User"
              value={
                <span className={cn(st.cpu.cores_eq >= 4 && 'text-rose-600')}>
                  {st.cpu.user_cpu_percent.toFixed(0)}% (~{st.cpu.cores_eq.toFixed(0)} core)
                </span>
              }
            />
            <KV label="CPU time" value={`${(st.cpu.cpu_time_seconds / 60).toFixed(0)} mnt`} />
            <KV label="Load avg" value={st.cpu.load_avg.join(' / ')} />
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold text-slate-600">3.4 Disk</h3>
            <KV
              label="Filesystem /"
              value={`${st.disk.fs_used_gb.toFixed(0)} / ${st.disk.fs_total_gb.toFixed(0)} GB`}
            />
            <KV label="Terpakai" value={`${st.disk.fs_percent.toFixed(0)}%`} />
            <KV label="Home" value={st.disk.home || '—'} />
          </div>
        </div>
      </Card>

      {/* Proses */}
      <Card title="Proses yang Sedang Berjalan" icon={<IconActivity className="h-5 w-5" />}>
        <h3 className="text-sm font-semibold text-slate-600">5.1 Proses Utama</h3>
        {main ? (
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <KV label="PID" value={main.pid} />
              <KV label="Status" value={main.status} />
              <KV label="Mulai" value={main.started} />
              <KV
                label="Runtime"
                value={`${((main.runtime_seconds ?? 0) / 60).toFixed(0)} mnt`}
              />
              <KV
                label="CPU"
                value={`${main.cpu_percent.toFixed(0)}% (~${main.cpu_cores_eq.toFixed(0)} core)`}
              />
              <KV label="CPU time" value={`${(main.cpu_time / 60).toFixed(0)} mnt`} />
              <KV label="RAM" value={formatMB(main.memory_mb)} />
              <KV
                label="GPU VRAM"
                value={main.gpu_vram_mb ? mib(main.gpu_vram_mb) : '—'}
              />
            </div>
            <p className="mt-2 break-all font-mono text-xs text-slate-600">
              {main.command}
            </p>
          </div>
        ) : (
          <p className="text-sm text-slate-400">Tidak ada proses aktif.</p>
        )}

        {r.processes.supporting.length > 0 && (
          <>
            <h3 className="pt-2 text-sm font-semibold text-slate-600">
              5.3 Proses Pendukung
            </h3>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead>
                  <tr>
                    <th className="table-th">PID</th>
                    <th className="table-th">Proses</th>
                    <th className="table-th">Workload</th>
                    <th className="table-th text-right">CPU</th>
                    <th className="table-th text-right">RAM</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {r.processes.supporting.map((e) => (
                    <tr key={e.pid}>
                      <td className="table-td font-mono text-xs text-slate-500">{e.pid}</td>
                      <td className="table-td text-slate-700">{e.name}</td>
                      <td className="table-td text-xs text-slate-500">{e.workload}</td>
                      <td className="table-td text-right">{e.cpu_percent.toFixed(0)}%</td>
                      <td className="table-td text-right">{formatMB(e.memory_mb)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Temuan */}
        <Card title="Temuan" icon={<IconActivity className="h-5 w-5" />}>
          <ul className="space-y-2">
            {r.findings.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span
                  className={cn(
                    'badge mt-0.5 shrink-0',
                    f.level === 'warn'
                      ? 'bg-rose-50 text-rose-700 ring-rose-600/20'
                      : 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
                  )}
                >
                  {f.level === 'warn' ? 'PERHATIAN' : 'OK'}
                </span>
                <span className="text-slate-600">{f.text}</span>
              </li>
            ))}
          </ul>
        </Card>

        {/* Rekomendasi */}
        <Card title="Rekomendasi" icon={<IconActivity className="h-5 w-5" />}>
          {(['high', 'medium', 'low'] as const).map((lvl) => {
            const items = r.recommendations[lvl]
            if (items.length === 0) return null
            const label =
              lvl === 'high' ? 'Prioritas Tinggi' : lvl === 'medium' ? 'Prioritas Sedang' : 'Prioritas Rendah'
            const color =
              lvl === 'high' ? 'text-rose-600' : lvl === 'medium' ? 'text-amber-600' : 'text-emerald-600'
            return (
              <div key={lvl} className="space-y-1">
                <p className={cn('text-xs font-semibold uppercase tracking-wide', color)}>
                  {label}
                </p>
                <ul className="ml-4 list-disc space-y-1 text-sm text-slate-600">
                  {items.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
            )
          })}
        </Card>
      </div>

      {/* Perbandingan */}
      <Card title="Perbandingan dengan User Lain" icon={<IconActivity className="h-5 w-5" />}>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead>
              <tr>
                <th className="table-th">User OS</th>
                <th className="table-th text-right">VRAM</th>
                <th className="table-th text-right">CPU</th>
                <th className="table-th text-right">RAM</th>
                <th className="table-th">Aktivitas</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {r.comparison.slice(0, 12).map((u) => (
                <tr
                  key={u.username}
                  className={cn(u.username === r.username && 'bg-brand-50/50')}
                >
                  <td className="table-td font-semibold text-slate-800">{u.username}</td>
                  <td className="table-td text-right">
                    {u.vram_mb > 0 ? mib(u.vram_mb) : '—'}
                  </td>
                  <td
                    className={cn(
                      'table-td text-right',
                      u.cpu_cores_eq >= 4 && 'text-rose-600',
                    )}
                  >
                    {u.cpu_percent.toFixed(0)}%
                  </td>
                  <td className="table-td text-right">{formatMB(u.memory_mb)}</td>
                  <td className="table-td text-xs text-slate-500">{u.activity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Kesimpulan */}
      <Card title="Kesimpulan" icon={<IconActivity className="h-5 w-5" />}>
        <p className="text-sm text-slate-600">{r.conclusion}</p>
      </Card>
    </div>
  )
}
