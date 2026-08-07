// Halaman LIHAT laporan satu akun ComputeHub. Padanan UserReportPage yang melihat
// akun Linux -- keduanya perlu ada karena satu orang bisa punya akun di dua sisi.
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import Spinner from '../components/Spinner'
import {
  IconActivity,
  IconArrowLeft,
  IconChart,
  IconDownload,
  IconUsers,
} from '../components/icons'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDuration, formatMB, timeAgo } from '../lib/format'
import type { AccountReport } from '../lib/types'

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function Card({
  title,
  icon,
  sub,
  children,
}: {
  title: string
  icon: React.ReactNode
  sub?: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-brand-600">{icon}</span>
        <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
        {sub && <span className="text-xs text-slate-400">· {sub}</span>}
      </div>
      {children}
    </section>
  )
}

function Baris({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-slate-100 py-1.5">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm font-medium text-slate-800">{value}</span>
    </div>
  )
}

function batas(v: number, satuan: 'mb' | 'jam' | 'menit' | 'angka'): string {
  if (!v) return 'tanpa batas'
  if (satuan === 'mb') return formatMB(v)
  if (satuan === 'jam') return `${(v / 3600).toFixed(1)} jam`
  if (satuan === 'menit') return `${(v / 60).toFixed(0)} menit`
  return String(v)
}

export default function AccountReportPage() {
  const { userId = '' } = useParams<{ userId: string }>()
  const { user } = useAuth()

  const q = useQuery({
    queryKey: ['admin-account-report', userId],
    queryFn: () => api.getAccountReport(Number(userId)),
    enabled: user?.role === 'admin' && !!userId,
    refetchInterval: 30000,
  })

  const dl = useMutation({
    mutationFn: async () => {
      const blob = await api.downloadReportBlob(
        `/admin/report/account/${userId}/download?days=30`,
      )
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')
      triggerDownload(blob, `laporan_akun_${userId}_${stamp}.pdf`)
    },
  })

  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  if (q.isLoading || !q.data) {
    return <Spinner label="Menyusun laporan akun…" className="p-6" />
  }

  const r: AccountReport = q.data
  const a = r.akun
  const k = r.kuota
  const j = r.job

  return (
    <div className="space-y-5">
      <Link
        to="/report#akun"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600"
      >
        <IconArrowLeft className="h-4 w-4" />
        Kembali ke Laporan
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">
            Laporan Akun — {a.nama || a.email}
          </h1>
          <p className="text-sm text-slate-500">
            {a.email} · peran {a.role} ·{' '}
            {a.aktif ? 'aktif' : <b className="text-rose-600">NONAKTIF</b>} ·{' '}
            {a.sso ? 'SSO kampus' : 'login lokal'} · dibuat {r.generated_at}
          </p>
        </div>
        <button
          onClick={() => dl.mutate()}
          className="btn-primary"
          disabled={dl.isPending}
        >
          <IconDownload className="h-4 w-4" />
          {dl.isPending ? 'Menyiapkan…' : 'Unduh PDF'}
        </button>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Identitas & Kuota" icon={<IconUsers className="h-5 w-5" />}>
          <div className="card-pad">
            <Baris label="Akun Linux terkait" value={a.username_os || '—'} />
            <Baris label="Hak pintu admin" value={a.pintu_admin ? 'ya' : 'tidak'} />
            <Baris label="VRAM per job" value={batas(k.vram_mb, 'mb')} />
            <Baris label="RAM per job" value={batas(k.ram_mb, 'mb')} />
            <Baris label="Thread CPU" value={batas(k.cpu_threads, 'angka')} />
            <Baris label="Job serempak" value={batas(k.job_serempak, 'angka')} />
            <Baris label="Kuota GPU harian" value={batas(k.gpu_detik_harian, 'jam')} />
            <Baris label="Batas waktu job" value={batas(k.batas_waktu_detik, 'menit')} />
            <Baris label="Penyimpanan" value={batas(k.storage_mb, 'mb')} />
            <Baris label="Izin 2 GPU" value={k.boleh_multi_gpu ? 'ya' : 'tidak'} />
          </div>
        </Card>

        <Card title="Ringkasan Pemakaian" icon={<IconChart className="h-5 w-5" />}>
          <div className="card-pad">
            <Baris
              label="Job"
              value={`${j.total} total · ${j.sukses} sukses · ${j.gagal} gagal`}
            />
            <Baris label="Waktu GPU" value={formatDuration(j.gpu_detik)} />
            <Baris label="Waktu komputasi" value={formatDuration(j.total_detik)} />
            <Baris
              label="VRAM puncak"
              value={j.vram_max_mb ? formatMB(j.vram_max_mb) : '—'}
            />
            <Baris
              label="RAM puncak"
              value={j.ram_max_mb ? formatMB(j.ram_max_mb) : '—'}
            />
            <Baris
              label="CPU puncak"
              value={j.cpu_max_percent ? `${j.cpu_max_percent.toFixed(0)}%` : '—'}
            />
            <Baris
              label="Penyimpanan dipakai"
              value={`${formatMB(r.penyimpanan.dipakai_mb)}${
                r.penyimpanan.kuota_mb ? ` / ${formatMB(r.penyimpanan.kuota_mb)}` : ''
              }`}
            />
            <Baris
              label="Asisten AI"
              value={
                r.asisten?.permintaan
                  ? `${r.asisten.permintaan} permintaan · ${formatDuration(r.asisten.detik)}`
                  : 'belum pernah'
              }
            />
          </div>
        </Card>
      </div>

      <Card
        title="Riwayat Harian: Job & Resource"
        icon={<IconActivity className="h-5 w-5" />}
        sub={`${r.days} hari terakhir`}
      >
        <p className="mb-2 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-700">
          Resource diukur langsung pada proses job milik akun ini. Akun Linux di atas
          hanya nama logis (bukan akun sistem), jadi pemakaiannya tidak muncul pada
          cuplikan per-user OS.
        </p>
        <Tabel
          kolom={['Tanggal', 'Job', 'Sukses', 'Gagal', 'Waktu GPU', 'VRAM puncak', 'RAM puncak', 'CPU puncak']}
          baris={r.harian.map((x) => [
            x.tanggal,
            String(x.jobs),
            String(x.sukses),
            String(x.gagal),
            formatDuration(x.gpu_detik),
            x.vram_max_mb ? formatMB(x.vram_max_mb) : '—',
            x.ram_max_mb ? formatMB(x.ram_max_mb) : '—',
            x.cpu_max_percent ? `${x.cpu_max_percent.toFixed(0)}%` : '—',
          ])}
          kosong="Belum ada job pada rentang ini."
        />
      </Card>

      <Card title="Status Resource Saat Ini" icon={<IconActivity className="h-5 w-5" />}>
        <Tabel
          kolom={['ID', 'Nama', 'Status', 'Jenis', 'GPU', 'VRAM', 'RAM']}
          baris={r.sekarang.map((x) => [
            String(x.id),
            x.nama,
            x.status,
            x.interaktif ? 'interaktif' : 'batch',
            x.gpu_index != null ? String(x.gpu_index) : '—',
            x.vram_mb ? formatMB(x.vram_mb) : '—',
            x.ram_mb ? formatMB(x.ram_mb) : '—',
          ])}
          kosong="Tidak ada job atau sesi milik akun ini yang sedang berjalan/antre."
        />
      </Card>

      <Card title="Job Terakhir" icon={<IconChart className="h-5 w-5" />}>
        <Tabel
          kolom={['ID', 'Nama', 'Status', 'Device', 'Durasi', 'VRAM puncak', 'Selesai']}
          baris={r.job_terakhir.map((x) => [
            String(x.id),
            x.nama,
            x.status,
            x.device,
            formatDuration(x.detik),
            x.vram_mb ? formatMB(x.vram_mb) : '—',
            x.selesai ? timeAgo(x.selesai) : '—',
          ])}
          kosong="Belum ada job."
        />
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Temuan" icon={<IconActivity className="h-5 w-5" />}>
          <div className="card-pad space-y-2">
            {r.temuan.length === 0 && (
              <p className="text-sm text-slate-400">Tidak ada temuan.</p>
            )}
            {r.temuan.map((t, i) => (
              <div key={i} className="flex gap-2 text-sm">
                <span
                  className={cn(
                    'badge shrink-0',
                    t.level === 'warn'
                      ? 'bg-amber-50 text-amber-700 ring-amber-600/20'
                      : 'bg-sky-50 text-sky-700 ring-sky-600/20',
                  )}
                >
                  {t.level}
                </span>
                <span className="text-slate-700">{t.text}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Rekomendasi" icon={<IconChart className="h-5 w-5" />}>
          <div className="card-pad space-y-3">
            {(
              [
                ['Prioritas Tinggi', r.rekomendasi.high, 'text-rose-600'],
                ['Prioritas Sedang', r.rekomendasi.medium, 'text-amber-600'],
                ['Prioritas Rendah', r.rekomendasi.low, 'text-slate-500'],
              ] as const
            ).map(([judul, isi, warna]) =>
              isi.length ? (
                <div key={judul}>
                  <p className={cn('text-xs font-semibold', warna)}>{judul}</p>
                  <ul className="ml-4 list-disc text-sm text-slate-700">
                    {isi.map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
          </div>
        </Card>
      </div>

      <Card
        title="Perbandingan dengan Akun Lain"
        icon={<IconUsers className="h-5 w-5" />}
        sub="sepuluh akun dengan waktu GPU terbanyak"
      >
        <div className="table-wrap">
          <table className="table-auto w-full text-sm">
            <thead>
              <tr>
                <th className="th">Pengguna</th>
                <th className="th r">Job</th>
                <th className="th r">Waktu GPU</th>
              </tr>
            </thead>
            <tbody>
              {r.perbandingan.map((b) => (
                <tr
                  key={b.user_id}
                  className={cn(
                    'border-t border-slate-100',
                    b.ini && 'bg-brand-50 font-semibold text-brand-700',
                  )}
                >
                  <td className="td">
                    {b.ini && '▸ '}
                    {b.nama}
                  </td>
                  <td className="td text-right">{b.jobs}</td>
                  <td className="td text-right">{formatDuration(b.gpu_detik)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Kesimpulan" icon={<IconChart className="h-5 w-5" />}>
        <p className="card-pad text-sm leading-relaxed text-slate-700">{r.kesimpulan}</p>
      </Card>
    </div>
  )
}

function Tabel({
  kolom,
  baris,
  kosong,
}: {
  kolom: string[]
  baris: string[][]
  kosong: string
}) {
  if (baris.length === 0) {
    return <p className="card-pad text-sm text-slate-400">{kosong}</p>
  }
  return (
    <div className="table-wrap max-h-96 overflow-auto">
      <table className="table-auto w-full text-sm">
        <thead className="sticky top-0 bg-white">
          <tr>
            {kolom.map((h, i) => (
              <th key={h} className={cn('th', i > 0 && 'r')}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {baris.map((row, i) => (
            <tr key={i} className="border-t border-slate-100">
              {row.map((sel, k) => (
                <td key={k} className={cn('td', k > 0 && 'text-right')}>
                  {sel}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
