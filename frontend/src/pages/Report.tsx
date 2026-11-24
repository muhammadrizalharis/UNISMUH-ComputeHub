import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'

import AreaChart from '../components/AreaChart'
import DevboxActivePanel from '../components/DevboxActivePanel'
import RefreshButton from '../components/RefreshButton'
import Spinner from '../components/Spinner'
import {
  IconActivity,
  IconBolt,
  IconChart,
  IconChevron,
  IconCpu,
  IconDownload,
  IconFolder,
  IconGpu,
  IconServer,
  IconSparkles,
  IconTerminal,
  IconUsers,
} from '../components/icons'
import { api } from '../lib/api'
import { PresenceBadge, presenceOf } from '../components/Presence'
import { useAuth } from '../lib/auth'
import { accountSourceLabel, cn, formatDateTime, formatDuration, formatMB, pct, timeAgo } from '../lib/format'
import type {
  GpuProcess,
  InteractiveSessionAdmin,
  OsUserUsage,
  PlatformUserUsage,
  ReportRunningJob,
  ReportSystem,
  SystemProcess,
  UserRole,
  DiskGrowth,
  DiskReport,
  LlmConnections,
  LlmUserUsage,
  RiwayatPemakaian,
  StorageSummary,
} from '../lib/types'

const ROLE_BADGE: Record<UserRole, string> = {
  admin: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  dosen: 'bg-violet-50 text-violet-700 ring-violet-600/20',
  mahasiswa: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

function mib(mb: number): string {
  return `${Math.round(mb).toLocaleString('id-ID')} MiB`
}

/** Ukuran disk dalam GB DESIMAL (1 GB = 10^9 byte) — sama dgn label kapasitas disk & `df -H`. */
function fmtGB(n: number): string {
  if (!n || n < 1) return '0 GB'
  if (n < 1e7) return `${(n / 1e6).toFixed(n < 1e6 ? 2 : 1)} MB`
  return `${(n / 1e9).toFixed(2)} GB`
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

async function unduhBerkas(path: string, namaDasar: string) {
  try {
    const blob = await api.downloadReportBlob(path)
    // Ekstensi mengikuti isi SEBENARNYA -> berkas tak pernah salah nama
    // walau backend & frontend sempat beda versi.
    const ext = blob.type.includes('pdf') ? 'pdf' : 'html'
    triggerDownload(blob, `${namaDasar}.${ext}`)
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

// Semua seksi bisa dilipat agar halaman tidak perlu di-scroll panjang.
// Yang isinya tabel panjang sengaja TERTUTUP saat pertama dibuka.
const ID_SEKSI = [
  'sistem', 'disk', 'penyimpanan-akun', 'gpu', 'llm', 'os-users', 'proses', 'job-jalan', 'devbox', 'sesi', 'akun', 'riwayat', 'jam-gpu',
] as const
const TERTUTUP_AWAL: Record<string, boolean> = {
  sistem: true, disk: true, 'os-users': true, proses: true, akun: true, 'jam-gpu': true,
}

function Section({
  title,
  icon,
  sub,
  children,
  id,
  buka,
  onToggle,
}: {
  title: string
  icon: React.ReactNode
  sub?: string
  children: React.ReactNode
  id?: string
  buka: boolean
  onToggle: () => void
}) {
  return (
    <section id={id} className="scroll-mt-20 space-y-3">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={buka}
        className="group flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left transition hover:bg-slate-50"
      >
        <span className="text-brand-600">{icon}</span>
        <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
        {sub && <span className="hidden text-xs text-slate-400 sm:inline">· {sub}</span>}
        <IconChevron
          className={cn(
            'ml-auto h-4 w-4 shrink-0 text-slate-400 transition-transform',
            !buka && '-rotate-90',
          )}
        />
      </button>
      {buka && children}
    </section>
  )
}

export default function Report() {
  const { user } = useAuth()
  const reportQ = useQuery({
    queryKey: ['admin-report'],
    queryFn: api.getReport,
    enabled: user?.role === 'admin',
    // Backend menyegarkan snapshot proses/GPU tiap ~1 dtk selama halaman ini dibuka.
    refetchInterval: 1000,
    // Laporan = pemantauan real-time: tetap polling walau tab tak fokus, dan
    // segarkan SEKETIKA saat admin kembali ke tab (mis. usai menjalankan sesuatu).
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  })
  const sessionsQ = useQuery({
    queryKey: ['interactive-sessions'],
    queryFn: api.listInteractiveSessionsAdmin,
    enabled: user?.role === 'admin',
    refetchInterval: 8000,
  })
  const forceDiskRef = useRef(false)
  const diskQ = useQuery({
    queryKey: ['admin-report-disk'],
    queryFn: () => {
      const force = forceDiskRef.current
      forceDiskRef.current = false
      return api.getDiskReport(force)
    },
    enabled: user?.role === 'admin',
    // Total disk dibaca langsung tiap request (murah) -> poll 3 dtk agar perubahan
    // (mis. hapus 50 GB) langsung terlihat; rincian per user menyusul otomatis.
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })
  const refreshDisk = () => {
    forceDiskRef.current = true
    void diskQ.refetch()
  }
  const [riwayatHari, setRiwayatHari] = useState(30)
  const [riwayatSistem, setRiwayatSistem] = useState(true)
  // Pilihan user: '' = semua, 'os:<username>' = akun Linux, 'ch:<id>' = akun ComputeHub.
  const [riwayatPilih, setRiwayatPilih] = useState('')
  const riwayatOsUser = riwayatPilih.startsWith('os:') ? riwayatPilih.slice(3) : undefined
  const riwayatChId = riwayatPilih.startsWith('ch:')
    ? Number(riwayatPilih.slice(3))
    : undefined
  const riwayatLlm = riwayatPilih.startsWith('llm:') ? riwayatPilih.slice(4) : undefined
  const riwayatQ = useQuery({
    queryKey: ['admin-report-history', riwayatHari, riwayatSistem, riwayatPilih],
    queryFn: () =>
      api.getUsageHistory(
        riwayatHari,
        riwayatSistem,
        riwayatOsUser,
        riwayatChId,
        riwayatLlm,
      ),
    enabled: user?.role === 'admin',
    refetchInterval: 120000,
  })

  // Seksi mana yang terbuka — diingat di browser agar tata letak pilihan admin menetap.
  const [seksiBuka, setSeksiBuka] = useState<Record<string, boolean>>(() => {
    try {
      const v = localStorage.getItem('report-seksi')
      if (v) return JSON.parse(v) as Record<string, boolean>
    } catch {
      /* nilai rusak -> pakai bawaan */
    }
    return Object.fromEntries(ID_SEKSI.map((i) => [i, !TERTUTUP_AWAL[i]]))
  })
  useEffect(() => {
    localStorage.setItem('report-seksi', JSON.stringify(seksiBuka))
  }, [seksiBuka])
  const seksi = (id: string) => ({
    id,
    buka: seksiBuka[id] ?? true,
    onToggle: () => setSeksiBuka((s) => ({ ...s, [id]: !(s[id] ?? true) })),
  })
  const setSemuaSeksi = (v: boolean) =>
    setSeksiBuka(Object.fromEntries(ID_SEKSI.map((i) => [i, v])))

  // Scroll otomatis ke seksi bila dibuka via anchor (mis. /report#akun dari Dashboard).
  // HANYA sekali per anchor: laporan ini polling tiap detik, dan tanpa penjaga ini
  // setiap penyegaran data akan menyeret tampilan kembali ke anchor -- pengguna jadi
  // tidak bisa membaca seksi lain.
  const location = useLocation()
  const anchorSelesai = useRef('')
  useEffect(() => {
    const id = location.hash.slice(1)
    if (!id || !reportQ.data || anchorSelesai.current === id) return
    anchorSelesai.current = id
    setSeksiBuka((s) => (s[id] ? s : { ...s, [id]: true })) // anchor harus terlihat
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
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
            <span className="glow-pulse h-1.5 w-1.5 rounded-full bg-emerald-500" />
            LIVE
          </span>
          <button type="button" className="btn-ghost" onClick={() => setSemuaSeksi(false)}>
            Tutup semua
          </button>
          <button type="button" className="btn-ghost" onClick={() => setSemuaSeksi(true)}>
            Buka semua
          </button>
          <button
            onClick={() =>
              void unduhBerkas('/admin/report/download', 'laporan_server')
            }
            className="btn-primary"
          >
            <IconDownload className="h-4 w-4" />
            Unduh Laporan
          </button>
          <RefreshButton
            onRefresh={() => {
              void reportQ.refetch()
              refreshDisk()
            }}
          />
        </div>
      </div>

      <Section
        title="Informasi Sistem"
        icon={<IconServer className="h-5 w-5" />}
        sub="CPU, RAM, GPU & uptime server"
        {...seksi('sistem')}
      >
        <SystemInfo s={r.system} />
      </Section>

      <Section
        title="Pemakaian Disk Server (hpc-ai)"
        icon={<IconServer className="h-5 w-5" />}
        sub="partisi / server ini: folder /home tiap akun Linux + Docker, model & sistem (GB desimal, langsung)"
        {...seksi('disk')}
      >
        <DiskUsage data={diskQ.data} loading={diskQ.isPending} />
        <DiskGrowthPanel />
      </Section>

      <Section
        title="Penyimpanan Akun ComputeHub"
        icon={<IconFolder className="h-5 w-5" />}
        sub="isi folder Penyimpanan (/persist) tiap akun mahasiswa, dosen & admin"
        {...seksi('penyimpanan-akun')}
      >
        <StorageAccounts rows={r.users} summary={r.storage} />
      </Section>

      <Section
        title="Penggunaan GPU Langsung"
        icon={<IconGpu className="h-5 w-5" />}
        sub="siapa yang memakai GPU sekarang (semua user server)"
        {...seksi('gpu')}
      >
        <GpuUsage system={r.system} procs={r.gpu_processes} />
      </Section>

      <Section
        title="Pemakai Layanan LLM (Ollama)"
        icon={<IconSparkles className="h-5 w-5" />}
        sub="siapa di balik beban akun layanan — user Linux & akun ComputeHub"
        {...seksi('llm')}
      >
        <LlmPemakai koneksi={r.llm_connections} akun={r.llm_users} />
      </Section>

      <Section
        title="Pengguna Server (OS)"
        icon={<IconUsers className="h-5 w-5" />}
        sub="agregasi VRAM / CPU / RAM per akun Linux"
        {...seksi('os-users')}
      >
        <OsUsersTable rows={r.os_users} sampledAt={r.system.sampled_at} />
      </Section>
      <Section
        title="Proses CPU Teratas"
        icon={<IconCpu className="h-5 w-5" />}
        sub="proses paling membebani CPU"
        {...seksi('proses')}
      >
        <TopProcesses rows={r.top_processes} />
      </Section>

      <Section
        title="Job ComputeHub Berjalan"
        icon={<IconActivity className="h-5 w-5" />}
        sub="siapa yang berjalan via platform"
        {...seksi('job-jalan')}
      >
        <RunningJobs rows={r.running_jobs} />
      </Section>

      <Section
        title="Devbox VS Code Aktif"
        icon={<IconTerminal className="h-5 w-5" />}
        sub="siapa yang memakai devbox sekarang; admin dapat menghentikan"
        {...seksi('devbox')}
      >
        <DevboxActivePanel showHeading={false} />
      </Section>

      <Section
        title="Sesi Interaktif Aktif"
        icon={<IconBolt className="h-5 w-5" />}
        sub="notebook/console ala Colab yang memakai GPU (kernel hidup)"
        {...seksi('sesi')}
      >
        <InteractiveSessions rows={sessionsQ.data ?? []} />
      </Section>

      <Section
        title="Statistik per Akun ComputeHub"
        icon={<IconChart className="h-5 w-5" />}
        sub="mahasiswa, dosen & admin"
        {...seksi('akun')}
      >
        <PlatformUsers rows={r.users} />
      </Section>

      <Section
        title="Riwayat Pemakaian Harian"
        icon={<IconChart className="h-5 w-5" />}
        sub="arsip per user per hari — server (OS) & platform ComputeHub"
        {...seksi('riwayat')}
      >
        <RiwayatHarian
          data={riwayatQ.data}
          memuat={riwayatQ.isLoading}
          hari={riwayatHari}
          setHari={setRiwayatHari}
          sistem={riwayatSistem}
          setSistem={setRiwayatSistem}
          pilih={riwayatPilih}
          setPilih={setRiwayatPilih}
        />
      </Section>

      <Section
        title="Jam GPU Bulanan"
        icon={<IconGpu className="h-5 w-5" />}
        sub="per pengguna & peran — dihitung sama dengan kuota (hanya saat VRAM dipakai)"
        {...seksi('jam-gpu')}
      >
        <JamGpuBulanan />
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
                    {Math.round(s.vram_used_mb ?? 0)} / {Math.round(s.vram_budget_mb)} MiB
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

function DiskRow({
  no,
  label,
  sub,
  bytes,
  total,
  max,
  bar = 'bg-brand-500',
}: {
  no?: number
  label: string
  sub?: string
  bytes: number
  total: number
  max: number
  bar?: string
}) {
  return (
    <tr className="border-b border-slate-50 last:border-0">
      <td className="px-4 py-2.5 text-slate-400">{no ?? ''}</td>
      <td className="px-4 py-2.5">
        <div className="font-medium text-slate-700">{label}</div>
        {sub && <div className="font-mono text-[11px] text-slate-400">{sub}</div>}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{fmtGB(bytes)}</td>
      <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
        {total ? `${((bytes / total) * 100).toFixed(1)}%` : '—'}
      </td>
      <td className="px-4 py-2.5">
        <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-100">
          <div
            className={cn('h-full rounded-full', bar)}
            style={{ width: `${max ? (bytes / max) * 100 : 0}%` }}
          />
        </div>
      </td>
    </tr>
  )
}

function DiskSubtotal({ label, bytes, total }: { label: string; bytes: number; total: number }) {
  return (
    <tr className="border-y border-slate-200 bg-slate-50/70 font-semibold text-slate-700">
      <td className="px-4 py-2.5" />
      <td className="px-4 py-2.5">{label}</td>
      <td className="px-4 py-2.5 text-right tabular-nums">{fmtGB(bytes)}</td>
      <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
        {total ? `${((bytes / total) * 100).toFixed(1)}%` : '—'}
      </td>
      <td className="px-4 py-2.5" />
    </tr>
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
  const outside = data.outside_home ?? []
  const homeTotal = data.home_total_bytes || data.users.reduce((s, u) => s + u.bytes, 0)
  const max = Math.max(0, ...data.users.map((u) => u.bytes), ...outside.map((o) => o.bytes))
  const berubah = data.changed_since_scan_bytes ?? 0
  const scanUsed = data.scan_used_bytes ?? data.used_bytes
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Kapasitas disk (/)" value={fmtGB(data.total_bytes)} />
        <Stat
          label="Terpakai"
          value={fmtGB(data.used_bytes)}
          hint={`${data.used_percent.toFixed(1)}% dari ruang yang bisa dipakai (sama dgn df)`}
        />
        <Stat
          label="Sisa"
          value={fmtGB(data.free_bytes)}
          hint={
            data.reserved_bytes
              ? `+ ${fmtGB(data.reserved_bytes)} cadangan khusus root (tak bisa dipakai user)`
              : undefined
          }
        />
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

      {data.users.length > 0 && Math.abs(berubah) >= 5e8 && (
        <p className="flex items-center gap-2 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-800 ring-1 ring-sky-600/20">
          {data.computing && <Spinner className="!p-0" />}
          <span>
            Disk {berubah < 0 ? 'berkurang' : 'bertambah'} <b>{fmtGB(Math.abs(berubah))}</b> sejak
            rincian di bawah dihitung. Angka Terpakai &amp; Sisa di atas sudah yang terbaru;
            rincian per user {data.computing ? 'sedang dihitung ulang (±1–3 menit)…' : 'akan segera dihitung ulang.'}
          </span>
        </p>
      )}

      {data.complete === false && data.users.length > 0 && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-600/20">
          Pemindaian terakhir tidak lengkap (sebagian folder tak terbaca atau waktu habis), jadi
          angka per user bisa lebih kecil dari sebenarnya. Klik Refresh untuk menghitung ulang.
        </p>
      )}

      {computing ? (
        <div className="card-pad flex items-center gap-2 text-sm text-slate-500">
          <Spinner className="!p-0" />
          Sedang menghitung ukuran folder tiap user… (du /home, ±1–3 menit).
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
                <th className="px-4 py-2.5 font-medium">Akun Linux (/home/…)</th>
                <th className="px-4 py-2.5 text-right font-medium">Ukuran</th>
                <th className="px-4 py-2.5 text-right font-medium">% dari kapasitas</th>
                <th className="px-4 py-2.5 font-medium">Proporsi</th>
              </tr>
            </thead>
            <tbody>
              {data.users.map((u, i) => (
                <DiskRow
                  key={u.user}
                  no={i + 1}
                  label={u.user}
                  bytes={u.bytes}
                  total={data.total_bytes}
                  max={max}
                />
              ))}
              <DiskSubtotal label="Total /home" bytes={homeTotal} total={data.total_bytes} />
              {outside.length > 0 && (
                <>
                  <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                    <th className="px-4 pb-1.5 pt-4 font-medium" />
                    <th className="px-4 pb-1.5 pt-4 font-medium" colSpan={4}>
                      Di luar /home
                    </th>
                  </tr>
                  {outside.map((o) => (
                    <DiskRow
                      key={o.key}
                      label={o.label}
                      sub={o.key === 'other' ? undefined : o.path}
                      bytes={o.bytes}
                      total={data.total_bytes}
                      max={max}
                      bar="bg-slate-400"
                    />
                  ))}
                  <DiskSubtotal
                    label={
                      Math.abs(berubah) >= 5e8
                        ? 'Total terpakai saat dirinci (= /home + di luar /home)'
                        : 'Total terpakai (= /home + di luar /home)'
                    }
                    bytes={homeTotal + outside.reduce((s, o) => s + o.bytes, 0) || scanUsed}
                    total={data.total_bytes}
                  />
                </>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="space-y-0.5 text-xs text-slate-400">
        <p>
          Satuan GB desimal: 1 GB = 1.000.000.000 byte (sama dengan label kapasitas disk dan{' '}
          <code>df -H</code>). Diukur sebagai root, read-only.
        </p>
        <p>
          Data workspace ComputeHub disimpan di server penyimpanan terpisah (di luar hpc-ai),
          sehingga tidak termasuk dalam angka di atas.
        </p>
        <p>
          Kapasitas, Terpakai &amp; Sisa dibaca langsung dari disk (diperbarui tiap 3 detik).
          Rincian per user dihitung ulang otomatis begitu disk berubah ≥ 0,5 GB (selesai ±1–3
          menit) dan paling lambat tiap 15 menit.
        </p>
        <p>
          {data.computed_at ? `Rincian dihitung ${timeAgo(data.computed_at)}` : 'Rincian belum pernah dihitung'}
          {data.computing && data.users.length > 0 ? ' · menghitung ulang di latar…' : ''}
        </p>
      </div>
    </div>
  )
}

const GROWTH_RANGES = [
  { days: 1, label: '24 jam' },
  { days: 7, label: '7 hari' },
  { days: 30, label: '30 hari' },
]

/** Riwayat sisa disk "/" (tiap 10 menit) + daftar lonjakan ≥ 50 GB/jam beserta pelakunya. */
function DiskGrowthPanel() {
  const [days, setDays] = useState(7)
  const [open, setOpen] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['admin-disk-growth', days],
    queryFn: () => api.getDiskGrowth(days),
    refetchInterval: 5 * 60_000,
  })
  const detailQ = useQuery({
    queryKey: ['admin-disk-growth-spike', open],
    queryFn: () => api.getDiskGrowthSpike(open as string),
    enabled: !!open,
  })
  const d: DiskGrowth | undefined = q.data
  const pts = d?.points ?? []
  const first = pts[0]
  const last = pts[pts.length - 1]
  const change = first && last ? last.free_gb - first.free_gb : 0

  return (
    <div className="mt-5 space-y-3 border-t border-slate-900/5 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-semibold text-slate-800">Riwayat Sisa Disk</p>
          <p className="text-xs text-slate-400">
            Dicatat tiap 10 menit · lonjakan = sisa disk turun ≥ 50 GB dalam ±1 jam
          </p>
        </div>
        <div className="flex gap-1">
          {GROWTH_RANGES.map((r) => (
            <button
              key={r.days}
              type="button"
              onClick={() => setDays(r.days)}
              className={cn(
                'rounded-lg px-2.5 py-1 text-xs font-medium ring-1',
                days === r.days
                  ? 'bg-brand-600 text-white ring-brand-600'
                  : 'bg-white text-slate-600 ring-slate-900/10 hover:bg-slate-50',
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {q.isPending ? (
        <Spinner label="Memuat riwayat disk…" className="p-6" />
      ) : !d || pts.length < 2 ? (
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          {d && !d.available
            ? 'Pencatat riwayat disk belum aktif (timer computehub-disk-growth).'
            : 'Riwayat belum cukup — grafik muncul setelah beberapa catatan (tiap 10 menit).'}
        </p>
      ) : (
        <>
          <AreaChart
            data={pts.map((p) => p.free_gb)}
            max={1e6}
            autoScale
            height={160}
            color={last && last.used_pct != null && last.used_pct >= 90 ? '#e11d48' : '#0ea5e9'}
            formatValue={(v) => `${v.toFixed(0)} GB`}
          />
          <div className="flex justify-between text-[11px] text-slate-400">
            <span>{formatDateTime(first.t)}</span>
            <span>{formatDateTime(last.t)}</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Sisa sekarang" value={`${last.free_gb.toFixed(1)} GB`} />
            <Stat
              label={`Perubahan ${GROWTH_RANGES.find((r) => r.days === days)?.label ?? ''}`}
              value={`${change > 0 ? '+' : ''}${change.toFixed(1)} GB`}
              hint={change < 0 ? 'sisa disk berkurang' : 'sisa disk bertambah / tetap'}
            />
            <Stat
              label="Turun tercepat"
              value={`${d.max_drop_gb_per_h.toFixed(1)} GB/jam`}
              hint="laju terburuk pada rentang ini"
            />
          </div>
        </>
      )}

      {d && d.spikes.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-rose-600">
            Lonjakan ({d.spikes.length})
          </p>
          {d.spikes.map((s) => (
            <div key={s.name} className="rounded-lg bg-rose-50/60 ring-1 ring-rose-600/15">
              <button
                type="button"
                onClick={() => setOpen(open === s.name ? null : s.name)}
                className="flex w-full items-center gap-3 px-3 py-2 text-left text-xs"
              >
                <IconChevron className={cn('h-4 w-4 shrink-0 text-rose-400 transition', open === s.name && 'rotate-90')} />
                <span className="shrink-0 font-medium text-slate-700">{formatDateTime(s.t)}</span>
                <span className="shrink-0 font-semibold text-rose-700">
                  −{s.drop_gb?.toFixed(0) ?? '?'} GB/jam
                </span>
                <span className="truncate font-mono text-slate-500">{s.top_writer}</span>
              </button>
              {open === s.name && (
                <pre className="max-h-96 overflow-auto border-t border-rose-600/10 px-3 py-2 text-[11px] leading-relaxed text-slate-700">
                  {detailQ.isPending ? 'Memuat…' : detailQ.data?.text ?? 'Gagal memuat rekaman.'}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Ukuran dari MiB (1 GiB = 1024 MiB) — satuan yang sama dengan kuota & halaman Penyimpanan. */
function fmtMBGB(mb: number): string {
  if (mb < 1024) return `${mb.toFixed(mb < 10 ? 1 : 0)} MiB`
  return `${(mb / 1024).toFixed(2)} GiB`
}

function StorageAccounts({ rows, summary }: { rows: PlatformUserUsage[]; summary?: StorageSummary }) {
  const [tampilKosong, setTampilKosong] = useState(false)
  const dipindai = rows.filter((u) => u.storage_used_mb != null)
  const berisi = dipindai
    .filter((u) => (u.storage_used_mb ?? 0) > 0)
    .sort((a, b) => (b.storage_used_mb ?? 0) - (a.storage_used_mb ?? 0))
  const kosong = rows.filter((u) => u.storage_used_mb === 0)
  const belum = rows.filter((u) => u.storage_used_mb == null)
  const tampil = tampilKosong ? [...berisi, ...kosong] : berisi
  const totalAkunMB = dipindai.reduce((s, u) => s + (u.storage_used_mb ?? 0), 0)
  const orphanMB = (summary?.orphan_bytes ?? 0) / 1024 / 1024
  const totalMB = totalAkunMB + orphanMB
  const max = Math.max(0, ...berisi.map((u) => u.storage_used_mb ?? 0))
  const terbesar = berisi[0]

  if (dipindai.length === 0) {
    return (
      <div className="card-pad flex items-center gap-2 text-sm text-slate-500">
        <Spinner className="!p-0" />
        Sedang memindai folder Penyimpanan tiap akun… Akun kecil muncul dalam hitungan detik,
        akun besar menyusul. Halaman memperbarui otomatis.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label="Total penyimpanan akun"
          value={fmtMBGB(totalMB)}
          hint={`${berisi.length} akun berisi data dari ${rows.length} akun`}
        />
        <Stat
          label="Terbesar"
          value={terbesar ? fmtMBGB(terbesar.storage_used_mb ?? 0) : '—'}
          hint={terbesar ? `#${terbesar.user_id} ${terbesar.name}` : undefined}
        />
        <Stat
          label="Pemindaian"
          value={summary?.full_running ? 'Berjalan' : 'Siaga'}
          hint={
            summary?.full_finished_at
              ? `siklus penuh terakhir selesai ${timeAgo(summary.full_finished_at)}`
              : 'siklus penuh pertama sedang berjalan'
          }
        />
      </div>

      {belum.length > 0 && (
        <p className="flex items-center gap-2 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-800 ring-1 ring-sky-600/20">
          <Spinner className="!p-0" />
          {belum.length} akun masih dipindai pertama kali; total di atas belum termasuk akun tersebut.
        </p>
      )}

      <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-slate-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="px-4 py-2.5 font-medium">#</th>
              <th className="px-4 py-2.5 font-medium">ID</th>
              <th className="px-4 py-2.5 font-medium">Akun ComputeHub</th>
              <th className="px-4 py-2.5 font-medium">Role</th>
              <th className="px-4 py-2.5 text-right font-medium">Terpakai</th>
              <th className="px-4 py-2.5 text-right font-medium">Kuota</th>
              <th className="px-4 py-2.5 text-right font-medium">% kuota</th>
              <th className="px-4 py-2.5 font-medium">Proporsi</th>
              <th className="px-4 py-2.5 font-medium">Diperbarui</th>
            </tr>
          </thead>
          <tbody>
            {tampil.map((u, i) => {
              const used = u.storage_used_mb ?? 0
              const quota = u.storage_quota_mb ?? 0
              const persen = quota > 0 ? (used / quota) * 100 : null
              return (
                <tr key={u.user_id} className="border-b border-slate-50 last:border-0" data-testid="storage-account-row">
                  <td className="px-4 py-2.5 text-slate-400">{i + 1}</td>
                  <td className="px-4 py-2.5 font-mono text-xs font-semibold text-slate-600">#{u.user_id}</td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-slate-700">{u.name}</div>
                    <div className="text-[11px] text-slate-400">{u.email}</div>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={cn('badge', ROLE_BADGE[u.role])}>{u.role}</span>
                  </td>
                  <td
                    className={cn(
                      'px-4 py-2.5 text-right font-medium tabular-nums',
                      persen != null && persen >= 100
                        ? 'text-rose-600'
                        : persen != null && persen >= 90
                          ? 'text-amber-600'
                          : used > 0 ? 'text-slate-700' : 'text-slate-300',
                    )}
                  >
                    {fmtMBGB(used)}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                    {quota > 0 ? fmtMBGB(quota) : <span className="text-slate-300">tanpa batas</span>}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                    {persen != null ? `${persen.toFixed(1)}%` : '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          persen != null && persen >= 100
                            ? 'bg-rose-500'
                            : persen != null && persen >= 90
                              ? 'bg-amber-500'
                              : 'bg-brand-500',
                        )}
                        style={{ width: `${max ? (used / max) * 100 : 0}%` }}
                      />
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-400">
                    {u.storage_scanning ? (
                      <span className="inline-flex items-center gap-1 text-sky-600">
                        <span className="glow-pulse h-1.5 w-1.5 rounded-full bg-sky-500" />
                        memindai…
                      </span>
                    ) : u.storage_scanned_at ? (
                      timeAgo(u.storage_scanned_at)
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              )
            })}
            <tr className="border-y border-slate-200 bg-slate-50/70 font-semibold text-slate-700">
              <td className="px-4 py-2.5" />
              <td className="px-4 py-2.5" colSpan={3}>Total semua akun</td>
              <td className="px-4 py-2.5 text-right tabular-nums">{fmtMBGB(totalAkunMB)}</td>
              <td className="px-4 py-2.5" colSpan={4} />
            </tr>
            {(summary?.orphan_count ?? 0) > 0 && (
              <>
                <tr className="border-b border-slate-50">
                  <td className="px-4 py-2.5" />
                  <td className="px-4 py-2.5 text-slate-500" colSpan={3}>
                    Folder tanpa akun ({summary?.orphan_count} folder milik akun yang sudah dihapus)
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{fmtMBGB(orphanMB)}</td>
                  <td className="px-4 py-2.5" colSpan={4} />
                </tr>
                <tr className="border-y border-slate-200 bg-slate-50/70 font-semibold text-slate-700">
                  <td className="px-4 py-2.5" />
                  <td className="px-4 py-2.5" colSpan={3}>Total penyimpanan akun</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{fmtMBGB(totalMB)}</td>
                  <td className="px-4 py-2.5" colSpan={4} />
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>

      {kosong.length > 0 && (
        <button
          type="button"
          className="text-xs font-medium text-brand-600 hover:underline"
          onClick={() => setTampilKosong((v) => !v)}
        >
          {tampilKosong ? 'Sembunyikan' : 'Tampilkan'} {kosong.length} akun yang penyimpanannya kosong
        </button>
      )}

      <div className="space-y-0.5 text-xs text-slate-400">
        <p>
          Satuan biner mengikuti kuota &amp; halaman Penyimpanan: 1 GiB = 1024 MiB ≈ 1,07 GB. Termasuk isi Tempat
          Sampah (masih terhitung kuota).
        </p>
        <p>
          Berkas yang dihapus permanen lewat web langsung mengurangi angka. Perubahan lain
          (unggah, job, terminal, Devbox) memicu pindai ulang folder akun itu segera: akun kecil
          dalam hitungan detik, akun ber-ratusan ribu berkas ±1–3 menit. Akun lain dipindai ulang
          tiap ±5 menit.
        </p>
        <p>
          Data workspace ComputeHub disimpan di server penyimpanan terpisah (di luar hpc-ai).
        </p>
      </div>
    </div>
  )
}

function SystemInfo({ s }: { s: ReportSystem }) {
  const ramPct = pct(s.memory_used_mb, s.memory_total_mb)
  return (
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
                    <td
                      className="table-td max-w-md truncate font-mono text-xs text-slate-600"
                      title={p.container?.name ? `Container: ${p.container.name} (${p.container.id})` : undefined}
                    >
                      {p.command || p.name}
                      {p.container?.name && (
                        <div className="truncate font-sans text-[11px] text-sky-600">
                          🐳 {p.container.name}
                        </div>
                      )}
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

function OsUsersTable({
  rows,
  sampledAt,
}: {
  rows: OsUserUsage[]
  sampledAt?: string | null
}) {
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
                void unduhBerkas(
                  `/admin/report/user/${encodeURIComponent(u.username)}/download`,
                  `laporan_${u.username}`,
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
      <p className="border-t border-slate-200/70 px-4 py-2.5 text-xs leading-relaxed text-slate-500">
        {sampledAt && (
          <>
            Data diambil pukul{' '}
            <span className="font-medium text-slate-600">
              {new Date(sampledAt).toLocaleTimeString('id-ID')}
            </span>{' '}
            (diperbarui tiap ±1 detik).{' '}
          </>
        )}
        CPU = rata-rata sejak pengambilan sebelumnya (100% = 1 core penuh) · RAM = memori
        pribadi proses (tanpa memori bersama, sehingga tidak dihitung ganda) · VRAM = dari
        driver NVIDIA (sama dengan nvidia-smi) · Proses = jumlah proses, bukan thread ·
        Aktivitas = tebakan otomatis dari proses GPU/CPU terbesar.
      </p>
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
      <td
        className="table-td font-medium text-slate-700"
        title={p.container?.name ? `Container: ${p.container.name} (${p.container.id})` : undefined}
      >
        {p.name}
        {p.container?.name && (
          <div className="text-[11px] font-normal text-sky-600">🐳 {p.container.name}</div>
        )}
      </td>
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
    <div className="card overflow-hidden" data-testid="running-job-metrics">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="table-th">Job</th>
              <th className="table-th">Pemilik</th>
              <th className="table-th" title="Perangkat yang dialokasikan, bukan bukti GPU sedang bekerja">Alokasi GPU</th>
              <th className="table-th text-right" title="Devbox: lama sesi hidup, bukan waktu komputasi GPU">Runtime</th>
              <th className="table-th text-right">CPU</th>
              <th className="table-th text-right">RAM</th>
              <th className="table-th text-right">VRAM</th>
              <th className="table-th text-right" title="Devbox: utilisasi SM proses milik container, bukan keseluruhan kartu GPU">GPU util</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((job) => {
              const isDevbox = job.is_devbox ?? job.name === 'Devbox VS Code'
              const sample = job.metrics_stale ? null : job.resource_sample
              const missing = job.metrics_stale ? 'Data lama'
                : job.resource_sample ? 'Tidak tersedia' : 'Belum diukur'
              const cpu = isDevbox ? sample?.cpu_percent : job.peak_cpu_percent
              const ram = isDevbox ? sample?.memory_used_mb : job.peak_ram_mb
              const vram = isDevbox ? sample?.gpu_mem_used_mb : job.peak_vram_mb
              const gpuUtil = isDevbox ? sample?.gpu_util_percent : job.avg_gpu_util_percent
              const unavailable = isDevbox ? missing : '-'
              const measuredAt = job.resource_sample
                ? `Sampel ${formatDateTime(job.resource_sample.ts)}`
                : 'Belum ada sampel resource untuk sesi ini'
              return (
              <tr key={job.id} className="hover:bg-slate-50" data-job-id={job.id}>
                <td className="table-td font-semibold text-slate-800">
                  #{job.id} {job.name}
                  {isDevbox && (
                    <div className="mt-0.5 text-[11px] font-normal text-slate-500" title={measuredAt}>
                      {job.metrics_stale ? 'Sampel kedaluwarsa' : job.resource_sample ? `Sampel ${timeAgo(job.resource_sample.ts)}` : 'Belum diukur'}
                    </div>
                  )}
                </td>
                <td className="table-td">
                  <div className="text-slate-700">{job.owner_name}</div>
                  <div className="text-xs text-slate-500">{accountSourceLabel(job)}</div>
                  <span className={cn('badge mt-0.5', ROLE_BADGE[job.role])}>
                    {job.role}
                  </span>
                </td>
                <td className="table-td text-slate-600">
                  {job.gpu_index != null ? `GPU ${job.gpu_index}` : 'CPU'}
                </td>
                <td className="table-td text-right text-slate-600">
                  {formatDuration(job.runtime_seconds)}
                </td>
                <td className="table-td text-right text-slate-600" title={isDevbox ? measuredAt : 'CPU puncak'}>
                  {cpu != null ? `${cpu.toFixed(1)}%` : unavailable}
                </td>
                <td className="table-td text-right text-slate-600" title={isDevbox ? measuredAt : 'RAM puncak'}>
                  {ram != null ? formatMB(ram) : unavailable}
                </td>
                <td className="table-td text-right text-slate-600" title={isDevbox ? measuredAt : 'VRAM puncak'}>
                  {job.gpu_index == null ? 'Tidak berlaku' : vram != null ? formatMB(vram) : unavailable}
                </td>
                <td className="table-td text-right text-slate-600" title={isDevbox ? measuredAt : 'Rata-rata utilisasi GPU'}>
                  {job.gpu_index == null ? 'Tidak berlaku' : gpuUtil != null ? `${gpuUtil.toFixed(0)}%` : unavailable}
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PlatformUsers({ rows }: { rows: PlatformUserUsage[] }) {
  const [source, setSource] = useState('all')
  const filtered = rows.filter((u) =>
    source === 'all' || (source === 'local' ? u.is_local : !u.is_local),
  )
  const online = filtered.filter((u) => presenceOf(u.last_seen_at) === 'online').length
  const recent = filtered.filter((u) => presenceOf(u.last_seen_at) === 'recent').length
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 border-b border-slate-100 p-4">
        <select
          className="input w-auto"
          aria-label="Filter sumber akun laporan"
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="all">Semua akun platform</option>
          <option value="computehub">ComputeHub (SSO / pengelola)</option>
          <option value="local">Lokal</option>
        </select>
        <span className="flex items-center gap-3 text-xs text-slate-500" data-testid="presence-summary">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <b className="text-emerald-600">{online}</b> online
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber-400" />
            <b className="text-amber-600">{recent}</b> aktif ≤30 mnt lalu
          </span>
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="table-th" title="ID akun — folder penyimpanan users/ID, Devbox ch-devbox-ID">ID</th>
              <th className="table-th">Pengguna</th>
              <th className="table-th">Role</th>
              <th className="table-th text-right">Job</th>
              <th className="table-th text-right">Jalan</th>
              <th className="table-th text-right">Antri</th>
              <th className="table-th text-right">Batal</th>
              <th className="table-th text-right">GPU hari ini</th>
              <th className="table-th text-right">GPU total</th>
              <th className="table-th text-right">Peak CPU</th>
              <th className="table-th text-right">Peak VRAM</th>
              <th className="table-th text-right" title="Isi folder Penyimpanan (/persist) milik akun; dipindai ulang segera saat berubah (rincian di seksi Penyimpanan Akun ComputeHub)">Penyimpanan</th>
              <th className="table-th" title="Kapan akun terakhir mengirim job">Job terakhir</th>
              <th className="table-th text-right">Laporan</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map((u) => (
              <tr key={u.user_id} className="hover:bg-slate-50">
                <td className="table-td whitespace-nowrap font-mono text-sm font-semibold text-slate-700">#{u.user_id}</td>
                <td className="table-td">
                  <div className="font-semibold text-slate-800">{u.name}</div>
                  <div className="text-xs text-slate-400">{u.email}</div>
                  <div className="text-xs font-medium text-brand-600">{accountSourceLabel(u)}</div>
                  <PresenceBadge lastSeen={u.last_seen_at} className="mt-0.5" />
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
                <td className="table-td text-right" data-testid="account-storage">
                  {u.storage_used_mb == null ? (
                    <span className="text-slate-300" title="Sedang dipindai pertama kali sejak backend menyala">…</span>
                  ) : (
                    <span
                      className={cn(
                        'font-medium',
                        u.storage_quota_mb && u.storage_used_mb >= u.storage_quota_mb
                          ? 'text-rose-600'
                          : u.storage_quota_mb && u.storage_used_mb >= u.storage_quota_mb * 0.9
                            ? 'text-amber-600'
                            : u.storage_used_mb > 0 ? 'text-slate-700' : 'text-slate-300',
                      )}
                      title={u.storage_quota_mb ? `Kuota ${formatMB(u.storage_quota_mb)}` : 'Tanpa batas kuota'}
                    >
                      {u.storage_used_mb > 0 ? formatMB(u.storage_used_mb) : '0 MiB'}
                      {u.storage_quota_mb ? (
                        <span className="ml-1 text-xs font-normal text-slate-400">
                          / {formatMB(u.storage_quota_mb)}
                        </span>
                      ) : null}
                    </span>
                  )}
                </td>
                <td className="table-td text-xs text-slate-500">
                  {u.last_activity ? timeAgo(u.last_activity) : '—'}
                </td>
                <td className="table-td text-right">
                  <div className="flex items-center justify-end gap-3">
                    <Link
                      to={`/report/account/${u.user_id}`}
                      className="text-xs font-medium text-brand-600 hover:underline"
                    >
                      Lihat
                    </Link>
                    <button
                      type="button"
                      title={`Unduh laporan PDF akun ${u.name}`}
                      className="text-slate-400 transition hover:text-brand-600"
                      onClick={() =>
                        void unduhBerkas(
                          `/admin/report/account/${u.user_id}/download`,
                          `laporan_akun_${u.name || u.email}`,
                        )
                      }
                    >
                      <IconDownload className="h-4 w-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// Siapa yang memakai layanan LLM bersama. Dua sudut pandang yang saling melengkapi:
// pemilik socket (user Linux) dan pemanggil Asisten AI (akun ComputeHub).
const SUMBER_LLM: Record<string, string> = {
  chat: 'Asisten web',
  help: 'Bantuan',
  devbox: 'Devbox',
  api: 'Kunci API',
}

function LlmPemakai({
  koneksi,
  akun,
}: {
  koneksi?: LlmConnections
  akun?: LlmUserUsage[]
}) {
  const klien = koneksi?.klien ?? []
  const asal = koneksi?.server ?? []
  const pemakai = akun ?? []

  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-700">
        Beban Ollama tercatat atas nama akun layanan, bukan pemakainya. Tabel di bawah
        menutup celah itu dari dua sisi: koneksi yang sedang terbuka (cuplikan saat ini —
        permintaan yang sudah selesai tidak terlihat di sini) dan riwayat per akun ComputeHub
        (Asisten web, Copilot di devbox, kunci API).
      </p>

      <div>
        <h3 className="mb-2 text-sm font-bold text-slate-700">
          User Linux · pemilik socket{' '}
          <span className="font-normal text-slate-400">
            (saat ini, port {koneksi?.ports?.join(', ') || '-'})
          </span>
        </h3>
        {klien.length === 0 && asal.length === 0 ? (
          <p className="card-pad text-sm text-slate-400">
            Tidak ada koneksi aktif ke layanan LLM saat ini.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="table-auto w-full text-sm">
              <thead>
                <tr>
                  <th className="th">User / Asal</th>
                  <th className="th">UID</th>
                  <th className="th r">Koneksi</th>
                </tr>
              </thead>
              <tbody>
                {klien.map((k) => (
                  <tr key={`k-${k.uid}`} className="border-t border-slate-100">
                    <td className="td font-medium">{k.user}</td>
                    <td className="td text-slate-500">{k.uid >= 0 ? k.uid : '—'}</td>
                    <td className="td text-right">{k.koneksi}</td>
                  </tr>
                ))}
                {asal.map((a) => (
                  <tr key={`s-${a.asal}`} className="border-t border-slate-100">
                    <td className="td">
                      {a.asal}
                      <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                        masuk
                      </span>
                    </td>
                    <td className="td text-slate-400">—</td>
                    <td className="td text-right">{a.koneksi}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <h3 className="mb-2 text-sm font-bold text-slate-700">
          Akun ComputeHub · pemakai Asisten AI &amp; Ollama{' '}
          <span className="font-normal text-slate-400">(30 hari terakhir)</span>
        </h3>
        {pemakai.length === 0 ? (
          <p className="card-pad text-sm text-slate-400">
            Belum ada permintaan asisten tercatat. Pencatatan berjalan sejak fitur ini
            aktif — permintaan sebelumnya tidak terekam.
          </p>
        ) : (
          <div className="table-wrap max-h-80 overflow-auto">
            <table className="table-auto w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="th">Pengguna</th>
                  <th className="th r">Permintaan</th>
                  <th className="th">Lewat</th>
                  <th className="th r">Pakai gambar</th>
                  <th className="th r">Waktu proses</th>
                  <th className="th">Terakhir</th>
                </tr>
              </thead>
              <tbody>
                {pemakai.map((u) => (
                  <tr key={u.user_id} className="border-t border-slate-100">
                    <td className="td">
                      <span className="font-medium">{u.nama || u.email}</span>
                      {u.nama && (
                        <div className="text-xs text-slate-400">{u.email}</div>
                      )}
                    </td>
                    <td className="td text-right">{u.permintaan}</td>
                    <td className="td text-xs text-slate-500">
                      {Object.entries(u.sumber ?? {})
                        .sort((a, b) => b[1] - a[1])
                        .map(([k, n]) => `${SUMBER_LLM[k] ?? k} ${n}`)
                        .join(' · ') || '—'}
                    </td>
                    <td className="td text-right">
                      {u.vision > 0 ? u.vision : '—'}
                    </td>
                    <td className="td text-right">{formatDuration(u.detik)}</td>
                    <td className="td text-slate-500">
                      {u.terakhir ? timeAgo(u.terakhir) : '—'}
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

// Riwayat pemakaian harian per user — arsip permanen (server OS + ComputeHub).
const PERAN: Record<string, string> = { mahasiswa: 'Mahasiswa', dosen: 'Dosen', admin: 'Admin' }

function jamGpu(detik: number) {
  return (detik / 3600).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

function bulanIni() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function JamGpuBulanan() {
  const [bulan, setBulan] = useState(bulanIni)
  const [galat, setGalat] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['gpu-monthly', bulan],
    queryFn: () => api.getGpuMonthly(bulan),
    enabled: /^\d{4}-\d{2}$/.test(bulan),
  })
  const unduh = async () => {
    setGalat(null)
    try {
      const blob = await api.downloadReportBlob(`/admin/report/gpu-monthly.csv?month=${bulan}`)
      triggerDownload(blob, `jam-gpu-${bulan}.csv`)
    } catch (e) {
      setGalat(`Gagal mengunduh CSV: ${(e as Error)?.message || 'kesalahan tak diketahui'}`)
    }
  }
  const d = q.data
  return (
    <div className="card-pad space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Bulan
          <input
            type="month"
            value={bulan}
            max={bulanIni()}
            onChange={(e) => setBulan(e.target.value)}
            className="input w-auto py-1"
          />
        </label>
        <button type="button" onClick={unduh} className="btn-ghost" disabled={!d}>
          <IconDownload className="h-4 w-4" />
          Unduh CSV
        </button>
        {d && (
          <span className="ml-auto text-sm text-slate-600">
            Total <b>{jamGpu(d.total_gpu_seconds)} jam GPU</b> · {d.users.length} pengguna
          </span>
        )}
      </div>
      {galat && <p className="text-sm text-rose-600">{galat}</p>}
      {q.isLoading && <Spinner label="Menghitung jam GPU…" />}
      {q.isError && <p className="text-sm text-rose-600">{(q.error as Error).message}</p>}
      {d && d.users.length === 0 && (
        <p className="text-sm text-slate-500">Belum ada pemakaian GPU tercatat pada bulan ini.</p>
      )}
      {d && d.users.length > 0 && (
        <>
          <div className="flex flex-wrap gap-2">
            {d.by_role.map((r) => (
              <span key={r.role} className="badge bg-slate-50 text-slate-700 ring-slate-200">
                {PERAN[r.role] ?? r.role}: {jamGpu(r.gpu_seconds)} jam · {r.users} orang
              </span>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Pengguna</th>
                  <th className="py-2 pr-3">Peran</th>
                  <th className="py-2 pr-3 text-right">Sesi</th>
                  <th className="py-2 pr-3 text-right">Jam GPU</th>
                  <th className="py-2 pr-3 text-right">Batch</th>
                  <th className="py-2 pr-3 text-right">Notebook</th>
                  <th className="py-2 pr-3 text-right">Devbox</th>
                  <th className="py-2 text-right">Puncak VRAM</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {d.users.map((u) => (
                  <tr key={u.user_id}>
                    <td className="py-2 pr-3">
                      <div className="font-medium text-slate-800">{u.name}</div>
                      <div className="text-xs text-slate-500">{u.username || u.email}</div>
                    </td>
                    <td className="py-2 pr-3">{PERAN[u.role] ?? u.role}</td>
                    <td className="py-2 pr-3 text-right">{u.sessions}</td>
                    <td className="py-2 pr-3 text-right font-semibold">{jamGpu(u.gpu_seconds)}</td>
                    <td className="py-2 pr-3 text-right">{jamGpu(u.batch_seconds)}</td>
                    <td className="py-2 pr-3 text-right">{jamGpu(u.interactive_seconds)}</td>
                    <td className="py-2 pr-3 text-right">{jamGpu(u.devbox_seconds)}</td>
                    <td className="py-2 text-right">{formatMB(u.peak_vram_mb)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400">
            Sesi dihitung pada bulan saat selesai (zona {d.timezone}). Sesi yang sedang berjalan
            belum masuk.
          </p>
        </>
      )}
    </div>
  )
}

function RiwayatHarian({
  data,
  memuat,
  hari,
  setHari,
  sistem,
  setSistem,
  pilih,
  setPilih,
}: {
  data?: RiwayatPemakaian
  memuat: boolean
  hari: number
  setHari: (n: number) => void
  sistem: boolean
  setSistem: (v: boolean) => void
  pilih: string
  setPilih: (v: string) => void
}) {
  const osUser = pilih.startsWith('os:') ? pilih.slice(3) : ''
  // Tiga sumber data yang BERBEDA -> jangan dicampur dalam satu tabel.
  const [sumber, setSumber] = useState<'server' | 'computehub' | 'llm'>('server')
  const [cari, setCari] = useState('')

  const unduhCsv = async (perJam = false) => {
    const q = new URLSearchParams({
      days: String(hari),
      include_system: String(sistem),
    })
    const llmNama = pilih.startsWith('llm:') ? pilih.slice(4) : ''
    if (sumber === 'llm') {
      q.set('sumber', 'llm')
      if (llmNama) q.set('username', llmNama)
    } else if (osUser) {
      q.set('username', osUser)
    }
    if (perJam) q.set('per_jam', 'true')
    const blob = await api.downloadReportBlob(`/admin/report/history.csv?${q}`)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = perJam
      ? `riwayat-jam-${osUser}-${hari}hari.csv`
      : sumber === 'llm'
        ? `riwayat-llm-${llmNama || 'semua'}-${hari}hari.csv`
        : `riwayat-pemakaian-${osUser || 'semua'}-${hari}hari.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const os = data?.os_users ?? []
  const ch = data?.computehub_users ?? []
  const llm = data?.llm_harian ?? []
  const osJam = data?.os_jam ?? []
  const chJam = data?.computehub_jam ?? []
  const daftar = data?.daftar_user

  const opsi =
    sumber === 'server'
      ? (daftar?.os ?? []).map((u) => ({
          nilai: `os:${u.username}`,
          kunci: u.username,
          label: u.is_system ? 'akun layanan' : 'akun Linux',
        }))
      : sumber === 'computehub'
        ? (daftar?.computehub ?? []).map((u) => ({
            nilai: `ch:${u.user_id}`,
            kunci: u.email,
            label: `${u.nama || '-'} · ${accountSourceLabel(u)} · ${u.jobs} job`,
          }))
        : (data?.daftar_llm ?? []).map((u) => ({
            nilai: `llm:${u.nama}`,
            kunci: u.nama,
            label: u.sumber === 'masuk' ? 'koneksi masuk' : 'user Linux',
          }))

  const ketik = (t: string) => {
    setCari(t)
    const q = t.trim().toLowerCase()
    const cocok = opsi.find(
      (o) => o.kunci.toLowerCase() === q || o.label.toLowerCase() === q,
    )
    setPilih(cocok ? cocok.nilai : '')
  }
  const bersihkan = () => {
    setCari('')
    setPilih('')
  }
  const gantiSumber = (s: 'server' | 'computehub' | 'llm') => {
    setSumber(s)
    bersihkan()
  }

  const namaTerpilih =
    osUser || (daftar?.computehub ?? []).find((u) => `ch:${u.user_id}` === pilih)?.nama

  return (
    <div className="space-y-4">
      <div className="flex max-w-full flex-wrap gap-0.5 rounded-lg border border-slate-300 p-0.5">
        {(
          [
            ['server', 'Server (akun Linux)'],
            ['computehub', 'ComputeHub (akun platform)'],
            ['llm', 'Layanan LLM (Ollama)'],
          ] as const
        ).map(([nilai, teks]) => (
          <button
            key={nilai}
            type="button"
            onClick={() => gantiSumber(nilai)}
            className={cn(
              'rounded-md px-3 py-1.5 text-sm font-medium transition',
              sumber === nilai
                ? 'bg-brand-600 text-white'
                : 'text-slate-600 hover:bg-slate-100',
            )}
          >
            {teks}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-0.5 rounded-lg border border-slate-300 p-0.5">
          {[0, 7, 30, 90, 365].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setHari(n)}
              className={cn(
                'rounded-md px-3 py-1.5 text-sm font-medium transition',
                hari === n ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100',
              )}
            >
              {n === 0 ? 'Hari ini' : n === 365 ? '1 tahun' : `${n} hari`}
            </button>
          ))}
        </div>
        <div className="relative w-full sm:w-64">
          <input
            className="input h-9 w-full py-1 text-sm"
            list="daftar-user-riwayat"
            value={cari}
            onChange={(e) => ketik(e.target.value)}
            placeholder={
              sumber === 'server'
                ? 'Ketik/pilih user Linux…'
                : sumber === 'computehub'
                  ? 'Ketik/pilih email…'
                  : 'Ketik/pilih pemakai LLM…'
            }
            aria-label="Cari user"
          />
          <datalist id="daftar-user-riwayat">
            {opsi.map((o) => (
              <option key={o.nilai} value={o.kunci} label={o.label} />
            ))}
          </datalist>
          {cari && (
            <button
              type="button"
              onClick={bersihkan}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
              aria-label="Hapus pencarian"
            >
              ×
            </button>
          )}
        </div>
        {sumber === 'server' && (
          <label className="inline-flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              className="h-4 w-4 accent-brand-600"
              checked={sistem}
              onChange={(e) => setSistem(e.target.checked)}
            />
            Sertakan akun layanan
          </label>
        )}
        <div className="ml-auto flex gap-2">
          {osUser && (
            <button type="button" className="btn-ghost" onClick={() => unduhCsv(true)}>
              CSV per jam
            </button>
          )}
          <button type="button" className="btn-ghost" onClick={() => unduhCsv(false)}>
            Unduh CSV
          </button>
        </div>
      </div>

      {cari && !pilih && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
          User <b>{cari}</b> tidak ada dalam rentang ini. Pilih dari daftar yang muncul
          saat mengetik, atau perlebar rentang waktu.
        </p>
      )}

      {pilih && (
        <div className="flex items-center gap-2 rounded-lg bg-brand-50 px-3 py-2 text-xs text-brand-700">
          <span>
            Menampilkan hanya <b>{namaTerpilih}</b> — lengkap dengan rincian jam-per-jam
            di bawah.
          </span>
          <button
            type="button"
            className="ml-auto underline hover:no-underline"
            onClick={bersihkan}
          >
            Tampilkan semua
          </button>
        </div>
      )}

      {memuat && <Spinner label="Memuat riwayat…" />}

      {!memuat &&
        (sumber === 'server'
          ? os.length === 0
          : sumber === 'computehub'
            ? ch.length === 0
            : llm.length === 0) && (
          <p className="rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-700">
            Belum ada data pada rentang ini. Perekaman berjalan otomatis di latar — riwayat
            akan terisi seiring waktu dan tidak pernah dihapus.
          </p>
        )}

      {sumber === 'server' && os.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-bold text-slate-700">
            Server (akun Linux) · {os.length} baris
          </h3>
          <div className="table-wrap max-h-96 overflow-auto">
            <table className="table-auto w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="th">Tanggal</th>
                  <th className="th">User</th>
                  <th className="th r">CPU rata²</th>
                  <th className="th r">CPU puncak</th>
                  <th className="th r">RAM puncak</th>
                  <th
                    className="th r"
                    title="Termasuk bobot model AI / pustaka yang dipetakan bersama"
                  >
                    RAM+model
                  </th>
                  <th className="th r">VRAM puncak</th>
                  <th className="th r">Menit aktif</th>
                  <th className="th">Aktivitas</th>
                </tr>
              </thead>
              <tbody>
                {os.map((u, i) => (
                  <tr key={`${u.tanggal}-${u.username}-${i}`} className="border-t border-slate-100">
                    <td className="td whitespace-nowrap">{u.tanggal}</td>
                    <td className="td font-medium">
                      {u.username}
                      {u.is_system && (
                        <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                          layanan
                        </span>
                      )}
                    </td>
                    <td className="td text-right">{u.cpu_cores_avg.toFixed(2)} core</td>
                    <td className="td text-right">{u.cpu_max_percent.toFixed(0)}%</td>
                    <td className="td text-right">{formatMB(u.ram_max_mb)}</td>
                    <td className="td text-right">
                      {u.ram_model_max_mb > 0 ? formatMB(u.ram_model_max_mb) : '—'}
                    </td>
                    <td className="td text-right">
                      {u.vram_max_mb > 0 ? formatMB(u.vram_max_mb) : '—'}
                    </td>
                    <td className="td text-right">{u.menit_aktif.toFixed(0)}</td>
                    <td className="td text-slate-500">{u.aktivitas || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {sumber === 'computehub' && ch.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-bold text-slate-700">
            Platform ComputeHub (job) · {ch.length} baris
          </h3>
          <div className="table-wrap max-h-80 overflow-auto">
            <table className="table-auto w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="th">Tanggal</th>
                  <th className="th">Pengguna</th>
                  <th className="th r">Job</th>
                  <th className="th r">Sukses</th>
                  <th className="th r">Gagal</th>
                  <th className="th r">Waktu GPU</th>
                  <th className="th r">VRAM puncak</th>
                </tr>
              </thead>
              <tbody>
                {ch.map((u, i) => (
                  <tr key={`${u.tanggal}-${u.user_id}-${i}`} className="border-t border-slate-100">
                    <td className="td whitespace-nowrap">{u.tanggal}</td>
                    <td className="td font-medium">
                      {u.nama || u.email}
                      <div className="text-xs font-normal text-slate-500">{accountSourceLabel(u)}</div>
                    </td>
                    <td className="td text-right">{u.jobs}</td>
                    <td className="td text-right text-emerald-600">{u.sukses}</td>
                    <td className="td text-right text-rose-600">{u.gagal}</td>
                    <td className="td text-right">{formatDuration(u.gpu_detik)}</td>
                    <td className="td text-right">
                      {u.vram_max_mb > 0 ? formatMB(u.vram_max_mb) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {sumber === 'llm' && llm.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-bold text-slate-700">
            Layanan LLM (Ollama) · {llm.length} baris{' '}
            <span className="font-normal text-slate-400">
              (cuplikan tiap 5 menit)
            </span>
          </h3>
          <p className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <b>Beban layanan</b> = angka NYATA hasil ukur pada proses Ollama.{' '}
            <b>Waktu aktif</b> = lama socket benar-benar mengalirkan data (dicuplik
            tiap 15 detik) — inilah dasar pembagian, bukan jumlah koneksi.{' '}
            <b>Perkiraan bagian</b> tetap ESTIMASI: Ollama satu proses, VRAM-nya tak
            bisa dipecah per pemakai oleh sistem operasi.
          </p>
          <div className="table-wrap max-h-96 overflow-auto">
            <table className="table-auto w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="th">Tanggal</th>
                  <th className="th">Pihak</th>
                  <th className="th r">Koneksi</th>
                  <th className="th r">Waktu aktif</th>
                  <th className="th r">Porsi</th>
                  <th className="th r">Beban VRAM</th>
                  <th className="th r">Perkiraan VRAM</th>
                  <th className="th r">Perkiraan CPU</th>
                  <th className="th r">Perkiraan RAM</th>
                </tr>
              </thead>
              <tbody>
                {llm.map((u, i) => (
                  <tr key={`${u.tanggal}-${u.nama}-${i}`} className="border-t border-slate-100">
                    <td className="td whitespace-nowrap">{u.tanggal}</td>
                    <td className="td font-medium">
                      {u.nama}
                      {u.sumber === 'masuk' && (
                        <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                          masuk
                        </span>
                      )}
                    </td>
                    <td className="td text-right text-slate-500">{u.koneksi_max}</td>
                    <td className="td text-right font-medium">
                      {u.detik_aktif > 0 ? formatDuration(u.detik_aktif) : '—'}
                    </td>
                    <td className="td text-right">
                      {(u.pangsa_avg * 100).toFixed(0)}%
                    </td>
                    <td className="td text-right text-slate-500">
                      {u.layanan_vram_max_mb > 0 ? formatMB(u.layanan_vram_max_mb) : '—'}
                    </td>
                    <td className="td text-right font-medium">
                      {u.est_vram_max_mb > 0 ? formatMB(u.est_vram_max_mb) : '—'}
                    </td>
                    <td className="td text-right">
                      {u.est_cpu_avg_percent > 0
                        ? `${u.est_cpu_avg_percent.toFixed(0)}%`
                        : '—'}
                    </td>
                    <td className="td text-right">
                      {u.est_ram_max_mb > 0 ? formatMB(u.est_ram_max_mb) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {sumber === 'server' && osJam.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-bold text-slate-700">
            Rincian per jam · {osUser}{' '}
            <span className="font-normal text-slate-400">
              (waktu server WITA · {osJam.length} jam tercatat)
            </span>
          </h3>
          <div className="table-wrap max-h-96 overflow-auto">
            <table className="table-auto w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="th">Tanggal</th>
                  <th className="th">Jam</th>
                  <th className="th r">CPU rata²</th>
                  <th className="th r">CPU puncak</th>
                  <th className="th r">RAM puncak</th>
                  <th
                    className="th r"
                    title="Termasuk bobot model AI / pustaka yang dipetakan bersama"
                  >
                    RAM+model
                  </th>
                  <th className="th r">VRAM puncak</th>
                  <th className="th r">Menit aktif</th>
                  <th className="th">Aktivitas</th>
                </tr>
              </thead>
              <tbody>
                {osJam.map((j, i) => (
                  <tr key={`${j.tanggal}-${j.jam}-${i}`} className="border-t border-slate-100">
                    <td className="td whitespace-nowrap">{j.tanggal}</td>
                    <td className="td whitespace-nowrap font-medium">{j.rentang}</td>
                    <td className="td text-right">{j.cpu_cores_avg.toFixed(2)} core</td>
                    <td className="td text-right">{j.cpu_max_percent.toFixed(0)}%</td>
                    <td className="td text-right">{formatMB(j.ram_max_mb)}</td>
                    <td className="td text-right">
                      {j.ram_model_max_mb > 0 ? formatMB(j.ram_model_max_mb) : '—'}
                    </td>
                    <td className="td text-right">
                      {j.vram_max_mb > 0 ? formatMB(j.vram_max_mb) : '—'}
                    </td>
                    <td className="td text-right">{j.menit_aktif.toFixed(0)}</td>
                    <td className="td text-slate-500">{j.aktivitas || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {sumber === 'computehub' && chJam.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-bold text-slate-700">
            Rincian per jam · job ComputeHub{' '}
            <span className="font-normal text-slate-400">
              (dihitung pada jam job SELESAI · {chJam.length} jam tercatat)
            </span>
          </h3>
          <div className="table-wrap max-h-80 overflow-auto">
            <table className="table-auto w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="th">Tanggal</th>
                  <th className="th">Jam</th>
                  <th className="th r">Job</th>
                  <th className="th r">Sukses</th>
                  <th className="th r">Gagal</th>
                  <th className="th r">Waktu GPU</th>
                  <th className="th r">VRAM puncak</th>
                </tr>
              </thead>
              <tbody>
                {chJam.map((j, i) => (
                  <tr key={`${j.tanggal}-${j.jam}-${i}`} className="border-t border-slate-100">
                    <td className="td whitespace-nowrap">{j.tanggal}</td>
                    <td className="td whitespace-nowrap font-medium">{j.rentang}</td>
                    <td className="td text-right">{j.jobs}</td>
                    <td className="td text-right text-emerald-600">{j.sukses}</td>
                    <td className="td text-right text-rose-600">{j.gagal}</td>
                    <td className="td text-right">{formatDuration(j.gpu_detik)}</td>
                    <td className="td text-right">
                      {j.vram_max_mb > 0 ? formatMB(j.vram_max_mb) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
