import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import RefreshButton from '../components/RefreshButton'
import Spinner from '../components/Spinner'
import { IconActivity, IconShield } from '../components/icons'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import type { AssistantModelInfo, SystemSettings, UserRole } from '../lib/types'

type FieldType = 'number' | 'bool'
type FieldUnit = 'time' | 'mem'
type FieldGroup = 'umum' | 'mahasiswa' | 'dosen' | 'admin'

const FIELDS: {
  key: keyof SystemSettings
  label: string
  type: FieldType
  unit?: FieldUnit
  group: FieldGroup
}[] = [
  // Umum & sistem
  { key: 'enforce_gpu', label: 'Wajib GPU (tolak CPU)', type: 'bool', group: 'umum' },
  {
    key: 'auto_pip_install',
    label: 'Auto install requirements.txt',
    type: 'bool',
    group: 'umum',
  },
  {
    key: 'max_concurrent_jobs',
    label: 'Maks job paralel (total sistem)',
    type: 'number',
    group: 'umum',
  },
  {
    key: 'default_job_time_limit_seconds',
    label: 'Batas waktu default',
    type: 'number',
    unit: 'time',
    group: 'umum',
  },
  {
    key: 'min_job_time_limit_seconds',
    label: 'Batas waktu minimum',
    type: 'number',
    unit: 'time',
    group: 'umum',
  },
  {
    key: 'max_job_time_limit_seconds',
    label: 'Batas waktu maksimum',
    type: 'number',
    unit: 'time',
    group: 'umum',
  },
  {
    key: 'runtime_safety_factor',
    label: 'Faktor pengaman estimasi (×)',
    type: 'number',
    group: 'umum',
  },
  // Mahasiswa
  {
    key: 'student_max_concurrent_jobs',
    label: 'Maks job/sesi paralel',
    type: 'number',
    group: 'mahasiswa',
  },
  {
    key: 'student_daily_gpu_seconds_quota',
    label: 'Kuota GPU / 24 jam (0 = off)',
    type: 'number',
    unit: 'time',
    group: 'mahasiswa',
  },
  {
    key: 'student_max_gpu_memory_mb',
    label: 'Plafon VRAM (0 = penuh)',
    type: 'number',
    unit: 'mem',
    group: 'mahasiswa',
  },
  {
    key: 'student_max_ram_mb',
    label: 'Plafon RAM (0 = penuh)',
    type: 'number',
    unit: 'mem',
    group: 'mahasiswa',
  },
  {
    key: 'student_max_cpu_threads',
    label: 'Maks thread CPU (0 = default)',
    type: 'number',
    group: 'mahasiswa',
  },
  // Dosen
  {
    key: 'dosen_max_concurrent_jobs',
    label: 'Maks job/sesi paralel',
    type: 'number',
    group: 'dosen',
  },
  {
    key: 'dosen_daily_gpu_seconds_quota',
    label: 'Kuota GPU / 24 jam (0 = off)',
    type: 'number',
    unit: 'time',
    group: 'dosen',
  },
  {
    key: 'dosen_max_gpu_memory_mb',
    label: 'Plafon VRAM (0 = penuh)',
    type: 'number',
    unit: 'mem',
    group: 'dosen',
  },
  {
    key: 'dosen_max_ram_mb',
    label: 'Plafon RAM (0 = penuh)',
    type: 'number',
    unit: 'mem',
    group: 'dosen',
  },
  {
    key: 'dosen_max_cpu_threads',
    label: 'Maks thread CPU (0 = default)',
    type: 'number',
    group: 'dosen',
  },
  // Admin biasa (super admin selalu bebas)
  {
    key: 'admin_max_concurrent_jobs',
    label: 'Maks job/sesi paralel (0 = off)',
    type: 'number',
    group: 'admin',
  },
  {
    key: 'admin_daily_gpu_seconds_quota',
    label: 'Kuota GPU / 24 jam (0 = off)',
    type: 'number',
    unit: 'time',
    group: 'admin',
  },
  {
    key: 'admin_max_gpu_memory_mb',
    label: 'Plafon VRAM (0 = penuh)',
    type: 'number',
    unit: 'mem',
    group: 'admin',
  },
  {
    key: 'admin_max_ram_mb',
    label: 'Plafon RAM (0 = penuh)',
    type: 'number',
    unit: 'mem',
    group: 'admin',
  },
  {
    key: 'admin_max_cpu_threads',
    label: 'Maks thread CPU (0 = default)',
    type: 'number',
    group: 'admin',
  },
]

const GROUPS: { id: FieldGroup; title: string; note?: string }[] = [
  { id: 'umum', title: 'Umum & Sistem' },
  { id: 'mahasiswa', title: 'Batas Mahasiswa' },
  { id: 'dosen', title: 'Batas Dosen' },
  {
    id: 'admin',
    title: 'Batas Admin (biasa)',
    note: 'Super admin selalu bebas dari semua batas & merupakan pengendalinya.',
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

function ModelSelect({
  label,
  value,
  models,
  onChange,
}: {
  label: string
  value: string
  models: AssistantModelInfo[]
  onChange: (v: string) => void
}) {
  const known = models.some((m) => m.name === value)
  return (
    <div>
      <label className="label">{label}</label>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {value && !known && <option value={value}>{value} (saat ini)</option>}
        {models.map((m) => (
          <option key={m.name} value={m.name}>
            {m.name} — {m.size_gb} GB{m.parameter_size ? ` · ${m.parameter_size}` : ''}
          </option>
        ))}
      </select>
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
  const modelsQ = useQuery({
    queryKey: ['assistant-models'],
    queryFn: api.getAssistantModels,
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

  const setField = (key: keyof SystemSettings, value: number | boolean | string) =>
    setForm({ ...form, [key]: value })
  const models = modelsQ.data ?? []

  const renderField = (f: (typeof FIELDS)[number]) =>
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
          min={0}
          step={f.key === 'runtime_safety_factor' ? 0.1 : 1}
          value={Number(form[f.key])}
          onChange={(e) => setField(f.key, Number(e.target.value))}
        />
      </div>
    )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="gradient-text text-2xl font-bold">Pengaturan Sistem</h1>
        <p className="text-sm text-slate-500">
          Hanya admin. Batas waktu, VRAM, RAM, CPU &amp; kuota GPU per peran —
          perubahan berlaku langsung tanpa restart.
        </p>
      </div>

      {/* Pengumuman platform (banner semua user) */}
      <section className="card-pad space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">Pengumuman Platform</h2>
          <p className="text-xs text-slate-500">
            Tampil sebagai banner untuk SEMUA user (mis. jadwal maintenance).
            Kosongkan lalu simpan untuk menghapus.
          </p>
        </div>
        <textarea
          className="textarea min-h-20 w-full"
          placeholder="mis. Server maintenance Jumat 22.00–23.00 WITA — job yang antri akan dilanjutkan otomatis."
          value={String(form.announcement_text ?? '')}
          onChange={(e) => setField('announcement_text', e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <label className="label mb-0">Level:</label>
          {(['info', 'warning', 'danger'] as const).map((lv) => (
            <button
              key={lv}
              type="button"
              onClick={() => setField('announcement_level', lv)}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset transition',
                lv === 'info' && 'bg-brand-50 text-brand-700 ring-brand-600/20',
                lv === 'warning' && 'bg-amber-50 text-amber-700 ring-amber-600/20',
                lv === 'danger' && 'bg-rose-50 text-rose-700 ring-rose-600/20',
                form.announcement_level === lv
                  ? 'ring-2 brightness-110'
                  : 'opacity-60 hover:opacity-100',
              )}
            >
              {lv === 'info' ? 'Info' : lv === 'warning' ? 'Peringatan' : 'Penting'}
            </button>
          ))}
          <button
            type="button"
            onClick={() =>
              mutation.mutate({
                announcement_text: String(form.announcement_text ?? ''),
                announcement_level: String(form.announcement_level ?? 'info'),
              })
            }
            disabled={mutation.isPending}
            className="btn-primary ml-auto !px-4 !py-1.5 text-sm"
          >
            Simpan pengumuman
          </button>
        </div>
      </section>

      {GROUPS.map((g) => (
        <section key={g.id} className="card-pad space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">{g.title}</h2>
            {g.note && <p className="text-xs text-slate-500">{g.note}</p>}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {FIELDS.filter((f) => f.group === g.id).map(renderField)}
          </div>
        </section>
      ))}

      <section className="card-pad space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">Model Asisten AI (per peran)</h2>
          <p className="text-xs text-slate-500">
            Model Ollama untuk Asisten AI notebook. Makin besar = makin pintar tapi makin berat
            VRAM. Ukuran ditampilkan agar tak salah pilih. Berlaku langsung setelah disimpan.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <ModelSelect
            label="Mahasiswa (disarankan ringan)"
            value={form.assistant_model_student}
            models={models}
            onChange={(v) => setField('assistant_model_student', v)}
          />
          <ModelSelect
            label="Dosen"
            value={form.assistant_model_dosen}
            models={models}
            onChange={(v) => setField('assistant_model_dosen', v)}
          />
          <ModelSelect
            label="Admin / Super Admin"
            value={form.assistant_model_admin}
            models={models}
            onChange={(v) => setField('assistant_model_admin', v)}
          />
          <ModelSelect
            label="Vision (input gambar) — dipakai otomatis saat ada gambar"
            value={form.assistant_model_vision}
            models={models}
            onChange={(v) => setField('assistant_model_vision', v)}
          />
        </div>
        {modelsQ.isError && (
          <p className="text-xs text-amber-600">
            Tak bisa memuat daftar model (Ollama tak terjangkau). Nilai saat ini tetap dipakai.
          </p>
        )}
      </section>

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
        <RefreshButton onRefresh={() => settingsQ.refetch()} label="Muat ulang" />
      </div>

      <UsageStats />

      <AuditTrail />
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
        <RefreshButton onRefresh={() => usageQ.refetch()} />
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

// Label aksi audit yang ramah dibaca.
const AUDIT_LABEL: Record<string, string> = {
  'user.create': 'Buat akun',
  'user.update': 'Ubah akun',
  'user.delete': 'Hapus akun',
  'password.reset': 'Reset password',
  'policy.update': 'Ubah kebijakan user',
  'settings.update': 'Ubah pengaturan global',
  'job.purge': 'Hapus permanen job',
}

function AuditTrail() {
  const auditQ = useQuery({
    queryKey: ['admin-audit'],
    queryFn: () => api.listAudit(100),
    refetchInterval: 30000,
  })
  const rows = auditQ.data ?? []

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconShield className="h-5 w-5 text-brand-600" />
          Log Aktivitas Admin
        </h2>
        <RefreshButton onRefresh={() => auditQ.refetch()} />
      </div>

      <div className="card overflow-hidden">
        {auditQ.isLoading ? (
          <Spinner label="Memuat log…" className="p-6" />
        ) : rows.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">
            Belum ada aktivitas tercatat. Aksi penting admin (buat/ubah/hapus akun, reset
            password, ubah kebijakan, hapus permanen job) akan muncul di sini.
          </p>
        ) : (
          <div className="max-h-[28rem] overflow-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="sticky top-0 bg-slate-50">
                <tr>
                  <th className="table-th">Waktu</th>
                  <th className="table-th">Aktor</th>
                  <th className="table-th">Aksi</th>
                  <th className="table-th">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50">
                    <td className="table-td whitespace-nowrap text-slate-500">
                      {formatDateTime(a.created_at)}
                    </td>
                    <td className="table-td text-slate-600">{a.actor_email || '—'}</td>
                    <td className="table-td">
                      <span className="badge bg-slate-100 text-slate-700 ring-slate-500/20">
                        {AUDIT_LABEL[a.action] || a.action}
                      </span>
                    </td>
                    <td className="table-td max-w-[28rem] truncate text-slate-600" title={a.detail}>
                      {a.detail || '—'}
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
