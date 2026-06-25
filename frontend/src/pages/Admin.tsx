import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import Spinner from '../components/Spinner'
import { IconActivity, IconRefresh } from '../components/icons'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import type { SystemSettings, UserRole } from '../lib/types'

type FieldType = 'number' | 'bool'
type FieldUnit = 'time' | 'mem'

const FIELDS: {
  key: keyof SystemSettings
  label: string
  type: FieldType
  unit?: FieldUnit
}[] = [
  { key: 'enforce_gpu', label: 'Wajib GPU (tolak CPU)', type: 'bool' },
  { key: 'auto_pip_install', label: 'Auto install requirements.txt', type: 'bool' },
  { key: 'max_concurrent_jobs', label: 'Maks job paralel (total)', type: 'number' },
  {
    key: 'student_max_concurrent_jobs',
    label: 'Maks job paralel / mahasiswa',
    type: 'number',
  },
  {
    key: 'student_daily_gpu_seconds_quota',
    label: 'Kuota GPU mahasiswa / 24 jam (0 = off)',
    type: 'number',
    unit: 'time',
  },
  {
    key: 'student_max_gpu_memory_mb',
    label: 'Plafon VRAM mahasiswa (0 = penuh)',
    type: 'number',
    unit: 'mem',
  },
  {
    key: 'student_max_ram_mb',
    label: 'Plafon RAM mahasiswa (0 = penuh)',
    type: 'number',
    unit: 'mem',
  },
  {
    key: 'dosen_max_concurrent_jobs',
    label: 'Maks job paralel / dosen',
    type: 'number',
  },
  {
    key: 'dosen_daily_gpu_seconds_quota',
    label: 'Kuota GPU dosen / 24 jam (0 = off)',
    type: 'number',
    unit: 'time',
  },
  {
    key: 'dosen_max_gpu_memory_mb',
    label: 'Plafon VRAM dosen (0 = penuh)',
    type: 'number',
    unit: 'mem',
  },
  {
    key: 'default_job_time_limit_seconds',
    label: 'Batas waktu default',
    type: 'number',
    unit: 'time',
  },
  {
    key: 'min_job_time_limit_seconds',
    label: 'Batas waktu minimum',
    type: 'number',
    unit: 'time',
  },
  {
    key: 'max_job_time_limit_seconds',
    label: 'Batas waktu maksimum',
    type: 'number',
    unit: 'time',
  },
  {
    key: 'runtime_safety_factor',
    label: 'Faktor pengaman estimasi (×)',
    type: 'number',
  },
]

const TIME_UNITS: { label: string; factor: number }[] = [
  { label: 'detik', factor: 1 },
  { label: 'menit', factor: 60 },
  { label: 'jam', factor: 3600 },
]
const MEM_UNITS: { label: string; factor: number }[] = [
  { label: 'MB', factor: 1 },
  { label: 'GB', factor: 1024 },
]

function UnitField({
  label,
  value,
  kind,
  onChange,
}: {
  label: string
  value: number
  kind: FieldUnit
  onChange: (base: number) => void
}) {
  const units = kind === 'time' ? TIME_UNITS : MEM_UNITS
  // Default tampilan: jam untuk waktu, GB untuk memori.
  const [unitIdx, setUnitIdx] = useState(units.length - 1)
  const factor = units[unitIdx].factor
  const display = value === 0 ? 0 : value / factor
  return (
    <div>
      <label className="label">{label}</label>
      <div className="flex gap-2">
        <input
          type="number"
          min={0}
          step="any"
          className="input flex-1"
          value={Number.isFinite(display) ? display : 0}
          onChange={(e) => onChange(Math.max(0, Number(e.target.value)) * factor)}
        />
        <select
          className="input w-24"
          value={unitIdx}
          onChange={(e) => setUnitIdx(Number(e.target.value))}
        >
          {units.map((u, i) => (
            <option key={u.label} value={i}>
              {u.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

export default function Admin() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const settingsQ = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
    enabled: user?.role === 'admin',
  })

  const [form, setForm] = useState<SystemSettings | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settingsQ.data) setForm(settingsQ.data)
  }, [settingsQ.data])

  const mutation = useMutation({
    mutationFn: (payload: Partial<SystemSettings>) => api.updateSettings(payload),
    onSuccess: (data) => {
      setForm(data)
      setMsg('Tersimpan & berlaku langsung.')
      setError(null)
      void qc.invalidateQueries({ queryKey: ['settings'] })
      void qc.invalidateQueries({ queryKey: ['capabilities'] })
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : 'Gagal menyimpan.'),
  })

  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  if (!form) return <Spinner label="Memuat pengaturan…" className="p-6" />

  const setField = (key: keyof SystemSettings, value: number | boolean) =>
    setForm({ ...form, [key]: value })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="gradient-text text-2xl font-bold">Pengaturan Sistem</h1>
        <p className="text-sm text-slate-500">
          Hanya admin. Batas waktu, VRAM, RAM, GPU &amp; kuota — perubahan berlaku
          langsung tanpa restart.
        </p>
      </div>

      <div className="card-pad grid gap-4 md:grid-cols-2">
        {FIELDS.map((f) =>
          f.type === 'bool' ? (
            <label key={f.key} className="flex items-center gap-3 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={Boolean(form[f.key])}
                onChange={(e) => setField(f.key, e.target.checked)}
                className="h-4 w-4 rounded border-slate-300"
              />
              {f.label}
            </label>
          ) : f.unit ? (
            <UnitField
              key={f.key}
              label={f.label}
              kind={f.unit}
              value={Number(form[f.key])}
              onChange={(base) => setField(f.key, base)}
            />
          ) : (
            <div key={f.key}>
              <label className="label">{f.label}</label>
              <input
                type="number"
                className="input"
                step={f.key === 'runtime_safety_factor' ? 0.1 : 1}
                value={Number(form[f.key])}
                onChange={(e) => setField(f.key, Number(e.target.value))}
              />
            </div>
          ),
        )}
      </div>

      {error && (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          {error}
        </div>
      )}
      {msg && (
        <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
          {msg}
        </div>
      )}

      <div className="flex gap-2">
        <button
          className="btn-primary"
          disabled={mutation.isPending}
          onClick={() => {
            setMsg(null)
            mutation.mutate(form)
          }}
        >
          {mutation.isPending ? 'Menyimpan…' : 'Simpan'}
        </button>
        <button className="btn-ghost" onClick={() => void settingsQ.refetch()}>
          Muat ulang
        </button>
      </div>

      <UsageStats />
    </div>
  )
}

const ROLE_BADGE: Record<UserRole, string> = {
  admin: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  dosen: 'bg-violet-50 text-violet-700 ring-violet-600/20',
  mahasiswa: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

function fmtDur(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} dtk`
  if (s < 3600) return `${Math.round(s / 60)} mnt`
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return m ? `${h}j ${m}m` : `${h}j`
}

function UsageStats() {
  const usageQ = useQuery({
    queryKey: ['admin-usage'],
    queryFn: api.getAdminUsage,
    refetchInterval: 20000,
  })

  const rows = usageQ.data ?? []
  const totalJobs = rows.reduce((s, u) => s + u.jobs_total, 0)
  const totalGpu = rows.reduce((s, u) => s + u.gpu_seconds_total, 0)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconActivity className="h-5 w-5 text-brand-600" />
          Statistik Pemakaian
        </h2>
        <button onClick={() => void usageQ.refetch()} className="btn-ghost">
          <IconRefresh className="h-4 w-4" />
          Refresh
        </button>
      </div>

      <div className="card overflow-hidden">
        {usageQ.isLoading ? (
          <Spinner label="Memuat statistik…" className="p-6" />
        ) : rows.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">Belum ada data.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="table-th">Pengguna</th>
                  <th className="table-th">Role</th>
                  <th className="table-th text-right">Job</th>
                  <th className="table-th text-right">Sukses</th>
                  <th className="table-th text-right">Gagal</th>
                  <th className="table-th text-right">GPU 24 jam</th>
                  <th className="table-th text-right">GPU total</th>
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
                    </td>
                    <td className="table-td text-right text-emerald-600">
                      {u.jobs_succeeded}
                    </td>
                    <td className="table-td text-right text-rose-600">
                      {u.jobs_failed}
                    </td>
                    <td className="table-td text-right text-slate-600">
                      {fmtDur(u.gpu_seconds_24h)}
                    </td>
                    <td className="table-td text-right text-slate-600">
                      {fmtDur(u.gpu_seconds_total)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="bg-slate-50">
                <tr>
                  <td className="table-td font-semibold text-slate-700" colSpan={2}>
                    Total
                  </td>
                  <td className="table-td text-right font-semibold text-slate-700">
                    {totalJobs}
                  </td>
                  <td className="table-td" colSpan={2} />
                  <td className="table-td text-right font-semibold text-slate-700" colSpan={2}>
                    {fmtDur(totalGpu)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
