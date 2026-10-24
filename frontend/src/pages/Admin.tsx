import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import RefreshButton from '../components/RefreshButton'
import LinuxAccountsPanel from '../components/LinuxAccountsPanel'
import Spinner from '../components/Spinner'
import { IconActivity, IconShield, IconTerminal } from '../components/icons'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import type { AssistantModelInfo, AuditFilter, OllamaKey, OllamaKeyCreated, SystemSettings, User, UserRole } from '../lib/types'

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
    label: 'Kuota GPU / hari (0 = off)',
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
  {
    key: 'student_max_storage_mb',
    label: 'Kuota penyimpanan (0 = tanpa batas)',
    type: 'number',
    unit: 'mem',
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
    label: 'Kuota GPU / hari (0 = off)',
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
  {
    key: 'dosen_max_storage_mb',
    label: 'Kuota penyimpanan (0 = tanpa batas)',
    type: 'number',
    unit: 'mem',
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
    label: 'Kuota GPU / hari (0 = off)',
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
  {
    key: 'admin_max_storage_mb',
    label: 'Kuota penyimpanan (0 = tanpa batas)',
    type: 'number',
    unit: 'mem',
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
  const maintQ = useQuery({
    queryKey: ['maintenance-mode'],
    queryFn: api.getMaintenanceMode,
    enabled: user?.role === 'admin',
    refetchInterval: 30_000,
  })
  const maintMutation = useMutation({
    mutationFn: ({ active, message }: { active: boolean; message?: string }) =>
      api.setMaintenanceMode(active, message),
    onSuccess: (data) => {
      setMsg(
        data.active
          ? 'Mode pemeliharaan AKTIF — pekerjaan baru ditahan.'
          : 'Mode pemeliharaan dimatikan — platform normal kembali.',
      )
      setError(null)
      void qc.invalidateQueries({ queryKey: ['maintenance-mode'] })
      void qc.invalidateQueries({ queryKey: ['announcement'] })
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : 'Gagal mengubah mode pemeliharaan.'),
  })

  const [form, setForm] = useState<SystemSettings | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [maintMsg, setMaintMsg] = useState('')

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

      {/* Mode pemeliharaan: tahan pekerjaan BARU tanpa mengganggu yang berjalan */}
      <section
        className={cn(
          'card-pad space-y-3',
          maintQ.data?.active && 'ring-2 ring-inset ring-amber-500/40',
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">Mode Pemeliharaan</h2>
            <p className="text-xs text-slate-500">
              Menahan job &amp; sesi interaktif BARU (admin tetap bisa). Job dan kernel
              yang sedang berjalan TIDAK diganggu — pakai ini agar server sepi sebelum
              restart atau pembaruan.
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              maintMutation.mutate({ active: !maintQ.data?.active, message: maintMsg })
            }
            disabled={maintMutation.isPending || maintQ.isLoading}
            className={cn(
              'btn-primary !px-4 !py-1.5 text-sm',
              maintQ.data?.active && '!bg-rose-600 hover:!bg-rose-700',
            )}
          >
            {maintQ.data?.active ? 'Matikan pemeliharaan' : 'Nyalakan pemeliharaan'}
          </button>
        </div>
        {maintQ.data?.active ? (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-inset ring-amber-600/20">
            AKTIF sejak{' '}
            {maintQ.data.since
              ? new Date(maintQ.data.since).toLocaleString('id-ID')
              : '—'}
            . Pesan yang dilihat pengguna: “{maintQ.data.message}”
          </p>
        ) : (
          <input
            className="input w-full"
            placeholder="Pesan untuk pengguna (opsional — kosongkan untuk memakai teks bawaan)"
            value={maintMsg}
            onChange={(e) => setMaintMsg(e.target.value)}
          />
        )}
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

      <LinuxAccountsPanel />

      <DevboxSummary />

      <StorageRequestsPanel />

      <OllamaKeysPanel />

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
                  <th className="table-th text-right">GPU hari ini</th>
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

/** Ringkasan singkat: pemantauan & tombol Hentikan dipindah ke halaman Laporan. */
function DevboxSummary() {
  const boxesQ = useQuery({
    queryKey: ['admin-devbox'],
    queryFn: api.listDevboxes,
    refetchInterval: 30000,
  })
  const rows = boxesQ.data ?? []
  const pakaiGpu = rows.filter((b) => b.device === 'gpu').length
  return (
    <div className="space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
        <IconTerminal className="h-5 w-5 text-brand-600" />
        Devbox VS Code
      </h2>
      <div className="card card-pad flex flex-wrap items-center justify-between gap-3 text-sm">
        <span className="text-slate-600">
          {boxesQ.isLoading
            ? 'Memuat…'
            : rows.length === 0
              ? 'Tidak ada devbox yang menyala saat ini.'
              : `${rows.length} devbox menyala · ${pakaiGpu} memakai GPU`}
        </span>
        <Link to="/report#devbox" className="btn-ghost">
          Pantau &amp; hentikan di Laporan
        </Link>
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
  'maintenance.set': 'Mode pemeliharaan',
  'linux_limits.set': 'Atur batas akun Linux',
  'linux_limits.revert': 'Kembalikan batas akun Linux',
  'local_access.approve': 'Setujui akses lokal',
  'local_access.reject': 'Tolak akses lokal',
  'storage_quota.approve': 'Setujui kuota penyimpanan',
  'storage_quota.reject': 'Tolak kuota penyimpanan',
  'audit.export': 'Ekspor log audit',
  'ollama_key.create': 'Buat kunci Ollama',
  'ollama_key.update': 'Ubah kunci Ollama',
  'ollama_key.delete': 'Hapus kunci Ollama',
}

const AUDIT_GROUP_LABEL: Record<string, string> = {
  user: 'Akun (semua)',
  linux_limits: 'Batas akun Linux (semua)',
  local_access: 'Akses lokal (semua)',
  storage_quota: 'Kuota penyimpanan (semua)',
}

const AUDIT_PAGE = 100

// ----- Permintaan tambahan kuota penyimpanan (user -> admin) -----
function StorageRequestsPanel() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'pending' | 'all'>('pending')
  const [err, setErr] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['admin-storage-requests', tab],
    queryFn: () => api.listStorageRequests(tab, 100),
    refetchInterval: 30000,
    retry: false,
  })
  const segarkan = () => {
    void qc.invalidateQueries({ queryKey: ['admin-storage-requests'] })
    void qc.invalidateQueries({ queryKey: ['admin-audit'] })
  }
  const approve = useMutation({
    mutationFn: (v: { id: number; gb: number }) => api.approveStorageRequest(v.id, Math.round(v.gb * 1024)),
    onSuccess: () => { setErr(null); segarkan() },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal menyetujui.'),
  })
  const reject = useMutation({
    mutationFn: (v: { id: number; note: string }) => api.rejectStorageRequest(v.id, v.note),
    onSuccess: () => { setErr(null); segarkan() },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal menolak.'),
  })
  const rows = q.data ?? []
  const gb = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`)
  const belumAda = q.error instanceof ApiError && q.error.status === 404
  return (
    <div className="space-y-3" id="kuota" data-testid="storage-requests">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconActivity className="h-5 w-5 text-brand-600" />
          Permintaan Kuota Penyimpanan
          {tab === 'pending' && rows.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 text-xs font-semibold text-amber-700">{rows.length}</span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          <select value={tab} onChange={(e) => setTab(e.target.value as 'pending' | 'all')} className="input w-auto py-1 text-xs" aria-label="Saring permintaan kuota">
            <option value="pending">Menunggu</option>
            <option value="all">Semua</option>
          </select>
          <RefreshButton onRefresh={() => q.refetch()} />
        </div>
      </div>
      {err && <p className="text-sm text-rose-600">{err}</p>}
      <div className="card overflow-hidden">
        {q.isLoading ? (
          <Spinner label="Memuat permintaan…" className="p-6" />
        ) : belumAda ? (
          <p className="p-6 text-sm text-amber-700">Backend belum memuat modul permintaan kuota; aktif setelah backend diperbarui.</p>
        ) : rows.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">
            {tab === 'pending' ? 'Tidak ada permintaan yang menunggu.' : 'Belum ada permintaan.'}
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm" data-request-id={r.id}>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-slate-800">
                    #{r.user_id} {r.user_name || r.user_email}
                    <span className="ml-2 text-xs font-normal text-slate-400">{r.user_role} · {formatDateTime(r.created_at)}</span>
                  </p>
                  <p className="text-slate-600">
                    Minta <b>{gb(r.requested_mb)}</b> (sekarang {gb(r.current_quota_mb)}, terpakai {gb(r.used_mb)})
                  </p>
                  <p className="mt-0.5 whitespace-pre-wrap text-xs text-slate-500">{r.reason}</p>
                  {r.status !== 'pending' && (
                    <p className="mt-1 text-xs">
                      <span className={cn('badge', r.status === 'approved' ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-rose-50 text-rose-700 ring-rose-600/20')}>
                        {r.status === 'approved' ? `Disetujui ${gb(r.granted_mb ?? 0)}` : 'Ditolak'}
                      </span>
                      <span className="ml-2 text-slate-400">oleh {r.decided_by_email}{r.decision_note ? ` — ${r.decision_note}` : ''}</span>
                    </p>
                  )}
                </div>
                {r.status === 'pending' && (
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      className="btn-primary px-3 py-1.5 text-xs"
                      disabled={approve.isPending}
                      onClick={() => {
                        const v = window.prompt(`Setujui: kuota baru untuk ${r.user_name || r.user_email} (GB)`, String(Math.round(r.requested_mb / 1024)))
                        if (v == null) return
                        const n = Number(v)
                        if (!Number.isFinite(n) || n <= 0) { setErr('Angka GB tidak valid.'); return }
                        approve.mutate({ id: r.id, gb: n })
                      }}
                    >
                      Setujui
                    </button>
                    <button
                      type="button"
                      className="btn-ghost px-3 py-1.5 text-xs text-rose-600"
                      disabled={reject.isPending}
                      onClick={() => {
                        const note = window.prompt('Alasan penolakan (dikirim ke pemohon):', 'Rapikan berkas yang tidak terpakai terlebih dahulu.')
                        if (note == null) return
                        reject.mutate({ id: r.id, note: note.trim() })
                      }}
                    >
                      Tolak
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function OllamaKeysPanel() {
  const qc = useQueryClient()
  const [err, setErr] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [newKey, setNewKey] = useState<OllamaKeyCreated | null>(null)
  const [copied, setCopied] = useState(false)
  const [ownerId, setOwnerId] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [maxConcurrent, setMaxConcurrent] = useState(2)
  const [ratePerMin, setRatePerMin] = useState(30)
  const [maxTokens, setMaxTokens] = useState(4096)
  const [expiresAt, setExpiresAt] = useState('')
  const [note, setNote] = useState('')

  const q = useQuery({
    queryKey: ['admin-ollama-keys'],
    queryFn: () => api.listOllamaKeys(),
    refetchInterval: 60000,
    retry: false,
  })
  const modelsQ = useQuery({
    queryKey: ['admin-ollama-models'],
    queryFn: () => api.ollamaModelsAvailable(),
    retry: false,
  })
  const usersQ = useQuery({
    queryKey: ['admin-users-for-ollama'],
    queryFn: () => api.listUsers(),
    retry: false,
  })

  const segarkan = () => {
    void qc.invalidateQueries({ queryKey: ['admin-ollama-keys'] })
    void qc.invalidateQueries({ queryKey: ['admin-audit'] })
  }
  const resetForm = () => {
    setOwnerId(''); setModels([]); setMaxConcurrent(2); setRatePerMin(30)
    setMaxTokens(4096); setExpiresAt(''); setNote('')
  }
  const create = useMutation({
    mutationFn: () => api.createOllamaKey({
      name: '',
      owner_user_id: ownerId ? Number(ownerId) : null,
      allowed_models: models,
      max_concurrent: maxConcurrent,
      rate_per_min: ratePerMin,
      max_tokens: maxTokens,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      note: note.trim(),
    }),
    onSuccess: (k) => {
      setErr(null); setNewKey(k); setCopied(false)
      setShowForm(false); resetForm(); segarkan()
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal membuat kunci.'),
  })
  const toggle = useMutation({
    mutationFn: (v: { id: number; enabled: boolean }) => api.updateOllamaKey(v.id, { enabled: v.enabled }),
    onSuccess: () => { setErr(null); segarkan() },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal mengubah kunci.'),
  })
  const del = useMutation({
    mutationFn: (id: number) => api.deleteOllamaKey(id),
    onSuccess: () => { setErr(null); segarkan() },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal menghapus kunci.'),
  })

  const rows: OllamaKey[] = q.data ?? []
  const availModels = modelsQ.data ?? []
  const users: User[] = usersQ.data ?? []
  const belumAda = q.error instanceof ApiError && q.error.status === 404

  const buildShareText = (k: OllamaKeyCreated): string => {
    const base = window.location.origin
    const modelList = k.allowed_models.length > 0 ? k.allowed_models.join(', ') : '(semua model)'
    const firstModel = k.allowed_models[0] || 'qwen2.5:7b-instruct'
    const lines = [
      '=== Akses Ollama ComputeHub ===',
      `Pemilik   : ${k.owner_name || k.name || '-'}`,
    ]
    if (k.owner_role) lines.push(`Role      : ${k.owner_role}`)
    if (k.owner_nim) lines.push(`NIM       : ${k.owner_nim}`)
    if (k.owner_email) lines.push(`Email     : ${k.owner_email}`)
    lines.push(
      '',
      `Alamat    : ${base}/v1   (OpenAI-compatible)`,
      `API Key   : ${k.key}`,
      `Model     : ${modelList}`,
      '',
      'Contoh (Python OpenAI SDK):',
      'from openai import OpenAI',
      `client = OpenAI(base_url="${base}/v1", api_key="${k.key}")`,
      'r = client.chat.completions.create(',
      `    model="${firstModel}",`,
      '    messages=[{"role": "user", "content": "Halo"}],',
      ')',
      'print(r.choices[0].message.content)',
      '',
      'Contoh (curl):',
      `curl ${base}/v1/chat/completions \\`,
      `  -H "Authorization: Bearer ${k.key}" \\`,
      `  -H "Content-Type: application/json" \\`,
      `  -d '{"model":"${firstModel}","messages":[{"role":"user","content":"Halo"}]}'`,
    )
    return lines.join('\n')
  }

  return (
    <div className="space-y-3" id="ollama-keys">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconTerminal className="h-5 w-5 text-brand-600" />
          Akses Ollama (API key)
          {rows.length > 0 && (
            <span className="rounded-full bg-slate-100 px-2 text-xs font-semibold text-slate-600">{rows.length}</span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          <button type="button" className="btn-primary px-3 py-1.5 text-xs" onClick={() => { setNewKey(null); setShowForm((s) => !s) }}>
            {showForm ? 'Tutup' : '+ Kunci baru'}
          </button>
          <RefreshButton onRefresh={() => q.refetch()} />
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Beri teman Anda akses Ollama dari luar tanpa akun server. Tiap kunci dibatasi daftar model, laju, dan token.
      </p>
      {err && <p className="text-sm text-rose-600">{err}</p>}

      {newKey && (
        <div className="card-pad space-y-2 border border-emerald-200 bg-emerald-50">
          <p className="text-sm font-semibold text-emerald-800">Kunci untuk “{newKey.owner_name || newKey.name}” berhasil dibuat.</p>
          <p className="text-xs text-emerald-700">
            Salin <b>satu blok</b> di bawah lalu kirim ke pemilik — kunci ini <b>hanya ditampilkan sekali</b>.
          </p>
          <textarea
            readOnly
            className="h-56 w-full rounded border border-emerald-200 bg-white p-2 font-mono text-xs text-slate-800"
            value={buildShareText(newKey)}
            onFocus={(e) => e.currentTarget.select()}
          />
          <div className="flex items-center gap-2">
            <button type="button" className="btn-primary px-3 py-1 text-xs"
              onClick={() => { void navigator.clipboard?.writeText(buildShareText(newKey)); setCopied(true) }}>
              {copied ? 'Tersalin ✓' : 'Salin semua'}
            </button>
            <button type="button" className="btn-ghost px-2 py-1 text-xs"
              onClick={() => void navigator.clipboard?.writeText(newKey.key)}>Salin kunci saja</button>
            <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setNewKey(null)}>Tutup</button>
          </div>
        </div>
      )}

      {showForm && (
        <div className="card-pad space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-600">Pemilik (pengguna web)</span>
              {usersQ.isLoading ? (
                <Spinner label="Memuat pengguna…" className="py-2" />
              ) : (
                <select className="input" value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
                  <option value="">— pilih pengguna —</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} · {u.role}{u.role === 'mahasiswa' ? ` · ${u.email.split('@')[0]}` : ''}
                    </option>
                  ))}
                </select>
              )}
              <span className="mt-1 block text-xs text-slate-400">NIM & role ikut otomatis dari akun.</span>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-600">Kedaluwarsa (opsional)</span>
              <input type="date" className="input" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
            </label>
          </div>
          <div className="text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Model yang diizinkan {models.length > 0 && `(${models.length})`}</span>
            {modelsQ.isLoading ? (
              <Spinner label="Memuat daftar model…" className="py-2" />
            ) : availModels.length === 0 ? (
              <p className="text-xs text-amber-700">Daftar model belum tersedia (backend perlu diperbarui).</p>
            ) : (
              <div className="flex max-h-40 flex-wrap gap-1 overflow-y-auto rounded border border-slate-200 p-2">
                {availModels.map((m) => {
                  const on = models.includes(m)
                  return (
                    <button key={m} type="button"
                      className={cn('rounded-full px-2 py-0.5 text-xs ring-1', on ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-600 ring-slate-300')}
                      onClick={() => setModels((cur) => on ? cur.filter((x) => x !== m) : [...cur, m])}>
                      {m}
                    </button>
                  )
                })}
              </div>
            )}
            <p className="mt-1 text-xs text-slate-400">Kosong = semua model diizinkan.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-600">Maks. paralel</span>
              <input type="number" min={1} className="input" value={maxConcurrent} onChange={(e) => setMaxConcurrent(Math.max(1, Number(e.target.value) || 1))} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-600">Laju (req/menit)</span>
              <input type="number" min={1} className="input" value={ratePerMin} onChange={(e) => setRatePerMin(Math.max(1, Number(e.target.value) || 1))} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-600">Maks. token/respons</span>
              <input type="number" min={1} className="input" value={maxTokens} onChange={(e) => setMaxTokens(Math.max(1, Number(e.target.value) || 1))} />
            </label>
          </div>
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Catatan (opsional)</span>
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="flex items-center gap-2">
            <button type="button" className="btn-primary px-4 py-1.5 text-sm" disabled={create.isPending || !ownerId}
              onClick={() => { setErr(null); create.mutate() }}>
              {create.isPending ? 'Membuat…' : 'Buat kunci'}
            </button>
            <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={() => { setShowForm(false); resetForm() }}>Batal</button>
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        {q.isLoading ? (
          <Spinner label="Memuat kunci…" className="p-6" />
        ) : belumAda ? (
          <p className="p-6 text-sm text-amber-700">Backend belum memuat modul Akses Ollama; aktif setelah backend diperbarui.</p>
        ) : rows.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">Belum ada kunci. Klik “+ Kunci baru” untuk membuat.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map((k) => {
              const expired = k.expires_at != null && new Date(k.expires_at) < new Date()
              return (
                <li key={k.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm">
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-slate-800">
                      {k.name}
                      <span className="ml-2 font-mono text-xs font-normal text-slate-400">{k.key_prefix}…</span>
                      {!k.enabled && <span className="badge ml-2 bg-slate-100 text-slate-500 ring-slate-300">nonaktif</span>}
                      {expired && <span className="badge ml-2 bg-rose-50 text-rose-700 ring-rose-600/20">kedaluwarsa</span>}
                    </p>
                    <p className="text-xs text-slate-500">
                      {k.allowed_models.length === 0 ? 'Semua model' : k.allowed_models.join(', ')}
                    </p>
                    {(k.owner_nim || k.owner_role || k.owner_email) && (
                      <p className="mt-0.5 text-xs text-slate-500">
                        {k.owner_role ? `${k.owner_role}` : ''}
                        {k.owner_nim ? ` · NIM ${k.owner_nim}` : ''}
                        {k.owner_email ? ` · ${k.owner_email}` : ''}
                      </p>
                    )}
                    <p className="mt-0.5 text-xs text-slate-400">
                      {k.max_concurrent}× paralel · {k.rate_per_min} req/mnt · maks {k.max_tokens} token · {k.request_count} permintaan
                      {k.last_used_at ? ` · terakhir ${formatDateTime(k.last_used_at)}` : ' · belum dipakai'}
                      {k.expires_at ? ` · s/d ${formatDateTime(k.expires_at)}` : ''}
                      {k.note ? ` · ${k.note}` : ''}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button type="button" className="btn-ghost px-3 py-1.5 text-xs" disabled={toggle.isPending}
                      onClick={() => toggle.mutate({ id: k.id, enabled: !k.enabled })}>
                      {k.enabled ? 'Nonaktifkan' : 'Aktifkan'}
                    </button>
                    <button type="button" className="btn-ghost px-3 py-1.5 text-xs text-rose-600" disabled={del.isPending}
                      onClick={() => { if (window.confirm(`Hapus kunci “${k.name}”? Tidak bisa dibatalkan.`)) del.mutate(k.id) }}>
                      Hapus
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

function AuditTrail() {
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [exportErr, setExportErr] = useState('')

  useEffect(() => {
    const t = window.setTimeout(() => setQ(qInput.trim()), 400)
    return () => window.clearTimeout(t)
  }, [qInput])

  const filter: AuditFilter = { action, actor, q, date_from: dateFrom, date_to: dateTo }
  const filterKey = JSON.stringify(filter)
  useEffect(() => setPage(0), [filterKey])

  const auditQ = useQuery({
    queryKey: ['admin-audit', filterKey, page],
    queryFn: () => api.listAudit(filter, page * AUDIT_PAGE, AUDIT_PAGE),
    refetchInterval: page === 0 ? 30000 : false,
    placeholderData: (prev) => prev,
  })
  const summaryQ = useQuery({
    queryKey: ['admin-audit-summary', filterKey],
    queryFn: () => api.auditSummary(filter),
    refetchInterval: 30000,
  })
  const rows = auditQ.data ?? []
  const total = summaryQ.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / AUDIT_PAGE))
  const groups = Array.from(
    new Set((summaryQ.data?.actions ?? []).map((x) => x.action.split('.')[0])),
  ).filter((g) => (summaryQ.data?.actions ?? []).filter((x) => x.action.startsWith(`${g}.`)).length > 1)
  const hasFilter = Boolean(action || actor || qInput || dateFrom || dateTo)

  const resetFilter = () => {
    setAction('')
    setActor('')
    setQInput('')
    setQ('')
    setDateFrom('')
    setDateTo('')
  }

  const exportCsv = async () => {
    setExporting(true)
    setExportErr('')
    try {
      const blob = await api.downloadReportBlob(api.auditCsvPath(filter))
      const url = URL.createObjectURL(blob)
      const el = document.createElement('a')
      el.href = url
      el.download = `log-audit-admin-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.csv`
      document.body.appendChild(el)
      el.click()
      el.remove()
      URL.revokeObjectURL(url)
      summaryQ.refetch()
      if (page === 0) auditQ.refetch()
    } catch (e) {
      setExportErr(e instanceof Error ? e.message : 'Gagal mengekspor CSV')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconShield className="h-5 w-5 text-brand-600" />
          Log Aktivitas Admin
        </h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            onClick={exportCsv}
            disabled={exporting || total === 0}
            title="Unduh semua entri sesuai filter (maks. 50.000 baris) untuk keperluan audit"
          >
            {exporting ? 'Mengekspor…' : 'Ekspor CSV'}
          </button>
          <RefreshButton
            onRefresh={() => {
              auditQ.refetch()
              summaryQ.refetch()
            }}
          />
        </div>
      </div>

      <div className="card grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-6">
        <select
          className="input py-1 text-xs lg:col-span-2"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          aria-label="Saring aksi"
        >
          <option value="">Semua aksi</option>
          {groups.map((g) => (
            <option key={`g-${g}`} value={g}>
              {AUDIT_GROUP_LABEL[g] || `${g}.* (semua)`}
            </option>
          ))}
          {(summaryQ.data?.actions ?? []).map((x) => (
            <option key={x.action} value={x.action}>
              {AUDIT_LABEL[x.action] || x.action} ({x.count})
            </option>
          ))}
        </select>
        <select
          className="input py-1 text-xs"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          aria-label="Saring admin"
        >
          <option value="">Semua admin</option>
          {(summaryQ.data?.actors ?? []).map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
        <input
          className="input py-1 text-xs"
          placeholder="Cari detail / target…"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          aria-label="Kata kunci"
        />
        <input
          type="date"
          className="input py-1 text-xs"
          value={dateFrom}
          max={dateTo || undefined}
          onChange={(e) => setDateFrom(e.target.value)}
          aria-label="Dari tanggal"
          title="Dari tanggal (WITA)"
        />
        <input
          type="date"
          className="input py-1 text-xs"
          value={dateTo}
          min={dateFrom || undefined}
          onChange={(e) => setDateTo(e.target.value)}
          aria-label="Sampai tanggal"
          title="Sampai tanggal (WITA, inklusif)"
        />
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 sm:col-span-2 lg:col-span-6">
          <span>
            {total === 0
              ? 'Tidak ada entri'
              : `Menampilkan ${page * AUDIT_PAGE + 1}–${Math.min(total, page * AUDIT_PAGE + rows.length)} dari ${total.toLocaleString('id-ID')} entri`}
          </span>
          {hasFilter && (
            <button type="button" className="text-brand-600 hover:underline" onClick={resetFilter}>
              Reset filter
            </button>
          )}
          {exportErr && <span className="text-rose-600">{exportErr}</span>}
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              ‹ Lebih baru
            </button>
            <span>
              Hal. {page + 1}/{pages}
            </span>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              disabled={page + 1 >= pages}
              onClick={() => setPage((p) => p + 1)}
            >
              Lebih lama ›
            </button>
          </div>
        </div>
      </div>

      <div className="card overflow-hidden">
        {auditQ.isLoading ? (
          <Spinner label="Memuat log…" className="p-6" />
        ) : rows.length === 0 && hasFilter ? (
          <p className="p-6 text-sm text-slate-500">Tidak ada entri yang cocok dengan filter.</p>
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
