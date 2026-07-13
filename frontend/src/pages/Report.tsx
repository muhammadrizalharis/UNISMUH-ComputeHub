import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'

import RefreshButton from '../components/RefreshButton'
import Spinner from '../components/Spinner'
import {
  IconActivity,
  IconBolt,
  IconChart,
  IconCpu,
  IconDownload,
  IconGpu,
  IconServer,
  IconUsers,
} from '../components/icons'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDuration, formatMB, pct, timeAgo } from '../lib/format'
import type {
  GpuProcess,
  InteractiveSessionAdmin,
  OsUserUsage,
  PlatformUserUsage,
  ReportRunningJob,
  ReportSystem,
  SystemProcess,
  UserRole,
  DiskReport,
} from '../lib/types'

const ROLE_BADGE: Record<UserRole, string> = {
  admin: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  dosen: 'bg-violet-50 text-violet-700 ring-violet-600/20',
  mahasiswa: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

function mib(mb: number): string {
  return `${Math.round(mb).toLocaleString('id-ID')} MiB`
}

function fmtBytes(n: number): string {
  if (!n || n < 1) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i >= 3 ? 2 : i >= 2 ? 1 : 0)} ${u[i]}`
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

async function downloadHtml(path: string, filename: string) {
  try {
    const blob = await api.downloadReportBlob(path)
    triggerDownload(blob, filename)
  } catch {
    window.alert('Gagal mengunduh laporan.')
  }
}

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  if (d > 0) return `${d} hari ${h} jam`
  const m = Math.floor((seconds % 3600) / 60)
  return `${h} jam ${m} mnt`
}

function Section({
  title,
  icon,
  sub,
  children,
  id,
}: {
  title: string
  icon: React.ReactNode
  sub?: string
  children: React.ReactNode
  id?: string
}) {
  return (
    <section id={id} className="scroll-mt-20 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-brand-600">{icon}</span>
        <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
        {sub && <span className="text-xs text-slate-400">· {sub}</span>}
      </div>
      {children}
    </section>
  )
}

export default function Report() {
  const { user } = useAuth()
  const reportQ = useQuery({
    queryKey: ['admin-report'],
    queryFn: api.getReport,
    enabled: user?.role === 'admin',
    refetchInterval: 15000,
  })
  const sessionsQ = useQuery({
    queryKey: ['interactive-sessions'],
    queryFn: api.listInteractiveSessionsAdmin,
    enabled: user?.role === 'admin',
    refetchInterval: 8000,
  })
  const diskQ = useQuery({
    queryKey: ['admin-report-disk'],
    queryFn: api.getDiskReport,
    enabled: user?.role === 'admin',
    refetchInterval: 60000,
  })

  // Scroll otomatis ke seksi bila dibuka via anchor (mis. /report#akun dari Dashboard).
  const location = useLocation()
  useEffect(() => {
    if (!location.hash) return
    const id = location.hash.slice(1)
    const t = setTimeout(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 150)
    return () => clearTimeout(t)
  }, [location.hash, reportQ.data])

  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  if (reportQ.isLoading || !reportQ.data) {
    return <Spinner label="Menyusun laporan penggunaan…" className="p-6" />
  }

  const r = reportQ.data

  return (
    <div className="space-y-7">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">
            Laporan Penggunaan Resource
          </h1>
          <p className="text-sm text-slate-500">
            Pemakaian server langsung (semua user OS) + statistik akun ComputeHub.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
            <span className="glow-pulse h-1.5 w-1.5 rounded-full bg-emerald-500" />
            LIVE
          </span>
          <button
            onClick={() =>
              void downloadHtml('/admin/report/download', 'laporan_server.html')
            }
            className="btn-primary"
          >
            <IconDownload className="h-4 w-4" />
            Unduh Laporan
          </button>
          <RefreshButton onRefresh={() => reportQ.refetch()} />
        </div>
      </div>

      <SystemInfo s={r.system} />

      <Section
        title="Pemakaian Disk per User"
        icon={<IconServer className="h-5 w-5" />}
        sub="ukuran folder home tiap user (di-cache, dihitung di latar)"
        id="disk"
      >
        <DiskUsage data={diskQ.data} loading={diskQ.isPending} />
      </Section>

      <Section
        title="Penggunaan GPU Langsung"
        icon={<IconGpu className="h-5 w-5" />}
        sub="siapa yang memakai GPU sekarang (semua user server)"
      >
        <GpuUsage system={r.system} procs={r.gpu_processes} />
      </Section>

      <Section
        title="Pengguna Server (OS)"
        icon={<IconUsers className="h-5 w-5" />}
        sub="agregasi VRAM / CPU / RAM per akun Linux"
      >
        <OsUsersTable rows={r.os_users} />
      </Section>

      <Section
        title="Proses CPU Teratas"
        icon={<IconCpu className="h-5 w-5" />}
        sub="proses paling membebani CPU"
      >
        <TopProcesses rows={r.top_processes} />
      </Section>

      <Section
        title="Job ComputeHub Berjalan"
        icon={<IconActivity className="h-5 w-5" />}
        sub="siapa yang berjalan via platform"
      >
        <RunningJobs rows={r.running_jobs} />
      </Section>

      <Section
        title="Sesi Interaktif Aktif"
        icon={<IconBolt className="h-5 w-5" />}
        sub="notebook/console ala Colab yang memakai GPU (kernel hidup)"
      >
        <InteractiveSessions rows={sessionsQ.data ?? []} />
      </Section>

      <Section
        title="Statistik per Akun ComputeHub"
        icon={<IconChart className="h-5 w-5" />}
        sub="mahasiswa, dosen & admin"
        id="akun"
      >
        <PlatformUsers rows={r.users} />
      </Section>

      <p className="pt-2 text-center text-xs text-slate-400">
        Diperbarui {timeAgo(r.system.now)} · server {r.system.hostname}
      </p>
    </div>
  )
}

function InteractiveSessions({ rows }: { rows: InteractiveSessionAdmin[] }) {
  if (!rows.length) {
    return <p className="card-pad text-sm text-slate-400">Tidak ada sesi interaktif aktif.</p>
  }
  return (
    <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-slate-200">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
            <th className="px-4 py-2.5 font-medium">Pemilik</th>
            <th className="px-4 py-2.5 font-medium">GPU</th>
            <th className="px-4 py-2.5 font-medium">VRAM</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
            <th className="px-4 py-2.5 font-medium">Sel dijalankan</th>
            <th className="px-4 py-2.5 font-medium">Idle</th>
            <th className="px-4 py-2.5 font-medium">Berakhir dalam</th>
            <th className="px-4 py-2.5 font-medium">Project</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.session_id} className="border-b border-slate-50 last:border-0">
              <td className="px-4 py-2.5">
                <div className="font-medium text-slate-700">{s.owner_name ?? `User #${s.user_id}`}</div>
                {s.owner_email && <div className="text-xs text-slate-400">{s.owner_email}</div>}
              </td>
              <td className="px-4 py-2.5">
                <span className="badge bg-brand-50 text-brand-700 ring-brand-600/20">
                  <IconGpu className="h-3.5 w-3.5" /> GPU {s.gpu_index}
                </span>
              </td>
              <td className="px-4 py-2.5 text-slate-600">
                {s.vram_budget_mb ? (
                  <span title="VRAM terpakai / jatah">
                    {Math.round(s.vram_used_mb ?? 0)} / {Math.round(s.vram_budget_mb)} MB
                  </span>
                ) : (
                  '—'
                )}
              </td>
              <td className="px-4 py-2.5">
                {s.busy ? (
                  <span className="badge bg-blue-50 text-blue-700 ring-blue-600/20">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" /> menjalankan
                  </span>
                ) : (
                  <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> idle
                  </span>
                )}
              </td>
              <td className="px-4 py-2.5 text-slate-600">{s.execution_count}</td>
              <td className="px-4 py-2.5 text-slate-600">{formatDuration(s.idle_seconds)}</td>
              <td className="px-4 py-2.5 text-slate-600">
                {s.expires_in_seconds != null ? formatDuration(s.expires_in_seconds) : '—'}
              </td>
              <td className="px-4 py-2.5 text-slate-500">{s.has_project ? 'ya' : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl bg-white/60 px-4 py-3 ring-1 ring-slate-900/5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className="mt-0.5 font-semibold text-slate-800">{value}</p>
      {hint && <p className="text-xs text-slate-400">{hint}</p>}
    </div>
  )
}

function DiskUsage({ data, loading }: { data?: DiskReport; loading: boolean }) {
  if (loading && !data) {
    return <Spinner label="Memuat pemakaian disk…" className="p-6" />
  }
  if (!data) {
    return <p className="card-pad text-sm text-slate-400">Data disk belum tersedia.</p>
  }
  const computing = data.computing && data.users.length === 0
  const maxUser = data.users.reduce((m, u) => Math.max(m, u.bytes), 0)
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Total disk (/)" value={fmtBytes(data.total_bytes)} />
        <Stat
          label="Terpakai"
          value={fmtBytes(data.used_bytes)}
          hint={`${data.used_percent.toFixed(1)}% terpakai`}
        />
        <Stat label="Sisa" value={fmtBytes(data.free_bytes)} />
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-slate-100 ring-1 ring-slate-900/5">
        <div
          className={cn(
            'h-full rounded-full',
            data.used_percent >= 90
              ? 'bg-rose-500'
              : data.used_percent >= 75
                ? 'bg-amber-500'
                : 'bg-emerald-500',
          )}
          style={{ width: `${Math.min(100, data.used_percent)}%` }}
        />
      </div>

      {computing ? (
        <div className="card-pad flex items-center gap-2 text-sm text-slate-500">
          <Spinner className="!p-0" />
          Sedang menghitung ukuran folder tiap user… (du /home, perlu beberapa menit).
          Halaman memperbarui otomatis.
        </div>
      ) : data.users.length === 0 ? (
        <p className="card-pad text-sm text-slate-400">Tidak ada data per-user.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-slate-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="px-4 py-2.5 font-medium">#</th>
                <th className="px-4 py-2.5 font-medium">User (home)</th>
                <th className="px-4 py-2.5 font-medium">Ukuran</th>
                <th className="px-4 py-2.5 font-medium">% dari disk</th>
                <th className="px-4 py-2.5 font-medium">Proporsi</th>
              </tr>
            </thead>
            <tbody>
              {data.users.map((u, i) => (
                <tr key={u.user} className="border-b border-slate-50 last:border-0">
                  <td className="px-4 py-2.5 text-slate-400">{i + 1}</td>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{u.user}</td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtBytes(u.bytes)}</td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {data.total_bytes
                      ? `${((u.bytes / data.total_bytes) * 100).toFixed(1)}%`
                      : '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-brand-500"
                        style={{ width: `${maxUser ? (u.bytes / maxUser) * 100 : 0}%` }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-slate-400">
        {data.computed_at ? `Dihitung ${timeAgo(data.computed_at)}` : 'Belum pernah dihitung'}
        {data.computing && data.users.length > 0 ? ' · memperbarui di latar…' : ''}
      </p>
    </div>
  )
}

function SystemInfo({ s }: { s: ReportSystem }) {
  const ramPct = pct(s.memory_used_mb, s.memory_total_mb)
  return (
    <Section
      title="Informasi Sistem"
      icon={<IconServer className="h-5 w-5" />}
      sub={s.hostname}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Hostname" value={s.hostname} hint={s.os} />
        <Stat
          label="CPU"
          value={`${s.cpu_cores} core`}
          hint={`util ${s.cpu_percent.toFixed(0)}% · load ${s.load_avg.join(' / ')}`}
        />
        <Stat
          label="RAM"
          value={`${formatMB(s.memory_used_mb)} / ${formatMB(s.memory_total_mb)}`}
          hint={`${ramPct.toFixed(0)}% terpakai · swap ${formatMB(s.swap_used_mb)}`}
        />
        <Stat
          label="Disk (/)"
          value={`${s.disk_used_gb.toFixed(0)} / ${s.disk_total_gb.toFixed(0)} GB`}
          hint={`${s.disk_percent.toFixed(0)}% terpakai`}
        />
        <Stat
          label="GPU"
          value={`${s.gpus.length} × ${s.gpus[0]?.name ?? '-'}`}
          hint={s.gpus[0] ? `${formatMB(s.gpus[0].mem_total_mb)} VRAM / GPU` : undefined}
        />
        <Stat
          label="Driver / CUDA"
          value={s.driver_version || '-'}
          hint={s.cuda_version ? `CUDA ${s.cuda_version}` : undefined}
        />
        <Stat label="Uptime" value={fmtUptime(s.uptime_seconds)} />
        <Stat label="Akun ComputeHub" value={`${s.platform_users} user`} />
      </div>
    </Section>
  )
}

function GpuUsage({
  system,
  procs,
}: {
  system: ReportSystem
  procs: GpuProcess[]
}) {
  return (
    <div className="space-y-4">
      {/* ringkasan per GPU */}
      <div className="grid gap-3 md:grid-cols-2">
        {system.gpus.map((g) => {
          const memPct = pct(g.mem_used_mb, g.mem_total_mb)
          const users = [
            ...new Set(
              procs.filter((p) => p.gpu_index === g.index).map((p) => p.username),
            ),
          ]
          return (
            <div key={g.index} className="card-pad space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-indigo-500 text-white">
                    <IconGpu className="h-5 w-5" />
                  </span>
                  <div>
                    <p className="font-semibold text-slate-800">GPU {g.index}</p>
                    <p className="text-xs text-slate-500">{g.name}</p>
                  </div>
                </div>
                <div className="text-right text-sm">
                  <p className="font-semibold text-slate-700">
                    {g.util_percent.toFixed(0)}% util
                  </p>
                  <p className="text-xs text-slate-400">
                    {g.temperature_c.toFixed(0)}°C · {g.power_w.toFixed(0)} W
                  </p>
                </div>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">VRAM</span>
                <span className="font-semibold text-slate-700">
                  {formatMB(g.mem_used_mb)} / {formatMB(g.mem_total_mb)} (
                  {memPct.toFixed(0)}%)
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-brand-500 to-indigo-500"
                  style={{ width: `${memPct}%` }}
                />
              </div>
              <p className="text-xs text-slate-400">
                {users.length ? `dipakai: ${users.join(', ')}` : 'tidak ada proses'}
              </p>
            </div>
          )
        })}
      </div>

      {/* tabel proses GPU */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="table-th">GPU</th>
                <th className="table-th">PID</th>
                <th className="table-th">User OS</th>
                <th className="table-th">Workload</th>
                <th className="table-th">Program</th>
                <th className="table-th text-right">VRAM</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {procs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="p-6 text-center text-sm text-slate-500">
                    Tidak ada proses GPU aktif.
                  </td>
                </tr>
              ) : (
                procs.map((p) => (
                  <tr key={`${p.gpu_index}-${p.pid}`} className="hover:bg-slate-50">
                    <td className="table-td">
                      <span className="inline-flex items-center gap-1 font-semibold text-slate-600">
                        <IconGpu className="h-4 w-4 text-brand-500" />
                        {p.gpu_index}
                      </span>
                    </td>
                    <td className="table-td font-mono text-xs text-slate-500">
                      {p.pid}
                    </td>
                    <td className="table-td">
                      <span className="font-semibold text-slate-800">
                        {p.username}
                      </span>
                      {p.is_platform_job && (
                        <span className="ml-2 badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                          ComputeHub #{p.job_id}
                        </span>
                      )}
                    </td>
                    <td className="table-td text-xs text-slate-600">{p.workload}</td>
                    <td className="table-td max-w-md truncate font-mono text-xs text-slate-600">
                      {p.command || p.name}
                    </td>
                    <td className="table-td text-right font-semibold text-slate-700">
                      {mib(p.vram_mb)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function OsUsersTable({ rows }: { rows: OsUserUsage[] }) {
  const mainRows = rows.filter((u) => !u.is_system)
  const sysRows = rows.filter((u) => u.is_system)
  const renderRow = (u: OsUserUsage) => {
    const heavyCpu = u.cpu_cores_eq >= 4
    return (
      <tr key={u.username} className="hover:bg-slate-50">
        <td className="table-td">
          <Link
            to={`/report/user/${encodeURIComponent(u.username)}`}
            className="font-semibold text-brand-700 hover:underline"
          >
            {u.username}
          </Link>
        </td>
        <td className="table-td text-right font-semibold text-slate-700">
          {u.vram_mb > 0 ? mib(u.vram_mb) : '—'}
        </td>
        <td className="table-td text-slate-500">
          {u.gpu_indices.length ? u.gpu_indices.join(', ') : '—'}
        </td>
        <td
          className={cn(
            'table-td text-right font-medium',
            heavyCpu ? 'text-rose-600' : 'text-slate-600',
          )}
        >
          {u.cpu_percent.toFixed(0)}%
          <span className="ml-1 text-xs text-slate-400">(~{u.cpu_cores_eq} core)</span>
        </td>
        <td className="table-td text-right text-slate-600">{formatMB(u.memory_mb)}</td>
        <td className="table-td text-right text-slate-500">{u.processes}</td>
        <td className="table-td max-w-[180px] truncate text-xs text-slate-500">
          {u.activity || '—'}
        </td>
        <td className="table-td text-right">
          <div className="flex items-center justify-end gap-1">
            <Link
              to={`/report/user/${encodeURIComponent(u.username)}`}
              className="rounded-lg px-2 py-1 text-xs font-medium text-brand-600 hover:bg-brand-50"
            >
              Lihat
            </Link>
            <button
              title="Unduh laporan user"
              onClick={() =>
                void downloadHtml(
                  `/admin/report/user/${encodeURIComponent(u.username)}/download`,
                  `laporan_${u.username}.html`,
                )
              }
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-brand-50 hover:text-brand-600"
            >
              <IconDownload className="h-4 w-4" />
            </button>
          </div>
        </td>
      </tr>
    )
  }
  const renderTable = (data: OsUserUsage[]) => (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50">
          <tr>
            <th className="table-th">User OS</th>
            <th className="table-th text-right">VRAM</th>
            <th className="table-th">GPU</th>
            <th className="table-th text-right">CPU</th>
            <th className="table-th text-right">RAM</th>
            <th className="table-th text-right">Proses</th>
            <th className="table-th">Aktivitas</th>
            <th className="table-th text-right">Detail</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{data.map(renderRow)}</tbody>
      </table>
    </div>
  )
  return (
    <div className="card overflow-hidden">
      {renderTable(mainRows)}
      {sysRows.length > 0 && (
        <details className="border-t border-slate-200/70">
          <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50">
            Akun sistem / bawaan OS (default) — {sysRows.length} disembunyikan
          </summary>
          {renderTable(sysRows)}
        </details>
      )}
    </div>
  )
}

function TopProcesses({ rows }: { rows: SystemProcess[] }) {
  const mainRows = rows.filter((p) => !p.is_system)
  const sysRows = rows.filter((p) => p.is_system)
  const renderRow = (p: SystemProcess) => (
    <tr key={p.pid} className="hover:bg-slate-50">
      <td className="table-td font-mono text-xs text-slate-500">{p.pid}</td>
      <td className="table-td text-slate-700">{p.username}</td>
      <td className="table-td font-medium text-slate-700">{p.name}</td>
      <td className="table-td text-xs text-slate-500">{p.workload}</td>
      <td
        className={cn(
          'table-td text-right font-semibold',
          p.cpu_cores_eq >= 4 ? 'text-rose-600' : 'text-slate-700',
        )}
      >
        {p.cpu_percent.toFixed(0)}%
        <span className="ml-1 text-xs font-normal text-slate-400">~{p.cpu_cores_eq} core</span>
      </td>
      <td className="table-td text-right text-slate-600">{formatMB(p.memory_mb)}</td>
    </tr>
  )
  const renderTable = (data: SystemProcess[]) => (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50">
          <tr>
            <th className="table-th">PID</th>
            <th className="table-th">User</th>
            <th className="table-th">Proses</th>
            <th className="table-th">Workload</th>
            <th className="table-th text-right">CPU</th>
            <th className="table-th text-right">RAM</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{data.map(renderRow)}</tbody>
      </table>
    </div>
  )
  return (
    <div className="card overflow-hidden">
      {renderTable(mainRows)}
      {sysRows.length > 0 && (
        <details className="border-t border-slate-200/70">
          <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50">
            Proses sistem / bawaan (default) — {sysRows.length} disembunyikan
          </summary>
          {renderTable(sysRows)}
        </details>
      )}
    </div>
  )
}

function RunningJobs({ rows }: { rows: ReportRunningJob[] }) {
  if (rows.length === 0) {
    return (
      <div className="card-pad text-sm text-slate-500">
        Tidak ada job ComputeHub yang sedang berjalan.
      </div>
    )
  }
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="table-th">Job</th>
              <th className="table-th">Pemilik</th>
              <th className="table-th">GPU</th>
              <th className="table-th text-right">Runtime</th>
              <th className="table-th text-right">RAM</th>
              <th className="table-th text-right">VRAM</th>
              <th className="table-th text-right">GPU util</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((j) => (
              <tr key={j.id} className="hover:bg-slate-50">
                <td className="table-td font-semibold text-slate-800">
                  #{j.id} {j.name}
                </td>
                <td className="table-td">
                  <div className="text-slate-700">{j.owner_name}</div>
                  <span className={cn('badge mt-0.5', ROLE_BADGE[j.role])}>
                    {j.role}
                  </span>
                </td>
                <td className="table-td text-slate-600">
                  {j.gpu_index != null ? `GPU ${j.gpu_index}` : '—'}
                </td>
                <td className="table-td text-right text-slate-600">
                  {formatDuration(j.runtime_seconds)}
                </td>
                <td className="table-td text-right text-slate-600">
                  {j.peak_ram_mb != null ? formatMB(j.peak_ram_mb) : '—'}
                </td>
                <td className="table-td text-right text-slate-600">
                  {j.peak_vram_mb != null ? formatMB(j.peak_vram_mb) : '—'}
                </td>
                <td className="table-td text-right text-slate-600">
                  {j.avg_gpu_util_percent != null
                    ? `${j.avg_gpu_util_percent.toFixed(0)}%`
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PlatformUsers({ rows }: { rows: PlatformUserUsage[] }) {
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="table-th">Pengguna</th>
              <th className="table-th">Role</th>
              <th className="table-th text-right">Job</th>
              <th className="table-th text-right">Jalan</th>
              <th className="table-th text-right">Antri</th>
              <th className="table-th text-right">Batal</th>
              <th className="table-th text-right">GPU 24 jam</th>
              <th className="table-th text-right">GPU total</th>
              <th className="table-th text-right">Peak CPU</th>
              <th className="table-th text-right">Peak VRAM</th>
              <th className="table-th">Aktivitas</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((u) => (
              <tr key={u.user_id} className="hover:bg-slate-50">
                <td className="table-td">
                  <div className="font-semibold text-slate-800">{u.name}</div>
                  <div className="text-xs text-slate-400">{u.email}</div>
                </td>
                <td className="table-td">
                  <span className={cn('badge', ROLE_BADGE[u.role])}>{u.role}</span>
                </td>
                <td className="table-td text-right font-semibold text-slate-700">
                  {u.jobs_total}
                  <span className="ml-1 text-xs font-normal text-slate-400">
                    ({u.jobs_succeeded}✓ {u.jobs_failed}✗)
                  </span>
                </td>
                <td className="table-td text-right">
                  {u.jobs_running > 0 ? (
                    <span className="font-semibold text-emerald-600">
                      {u.jobs_running}
                    </span>
                  ) : (
                    <span className="text-slate-300">0</span>
                  )}
                </td>
                <td className="table-td text-right text-slate-500">
                  {u.jobs_queued || '—'}
                </td>
                <td className="table-td text-right">
                  {u.jobs_cancelled > 0 ? (
                    <span className="text-amber-600">{u.jobs_cancelled}</span>
                  ) : (
                    <span className="text-slate-300">0</span>
                  )}
                </td>
                <td className="table-td text-right text-slate-600">
                  {formatDuration(u.gpu_seconds_24h)}
                </td>
                <td className="table-td text-right text-slate-600">
                  {formatDuration(u.gpu_seconds_total)}
                </td>
                <td className="table-td text-right text-slate-600">
                  {u.peak_cpu_percent != null ? `${u.peak_cpu_percent.toFixed(0)}%` : '—'}
                </td>
                <td className="table-td text-right text-slate-600">
                  {u.peak_vram_mb != null ? formatMB(u.peak_vram_mb) : '—'}
                </td>
                <td className="table-td text-xs text-slate-500">
                  {u.last_activity ? timeAgo(u.last_activity) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
