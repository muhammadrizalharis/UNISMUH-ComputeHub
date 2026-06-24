import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import Spinner from '../components/Spinner'
import {
  IconBell,
  IconDownload,
  IconMail,
  IconRefresh,
} from '../components/icons'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import type { AlertConfig } from '../lib/types'

const METRIC_LABEL: Record<string, string> = {
  cpu: 'CPU (core)',
  ram: 'RAM (GB)',
  vram: 'VRAM (GB)',
  disk: 'Disk (%)',
  manual: 'Manual',
}

const THRESHOLDS: { key: keyof AlertConfig; label: string; step: number }[] = [
  { key: 'cpu_cores', label: 'Batas CPU (core-equivalent)', step: 1 },
  { key: 'ram_gb', label: 'Batas RAM (GB)', step: 1 },
  { key: 'vram_gb', label: 'Batas VRAM (GB)', step: 1 },
  { key: 'disk_percent', label: 'Batas Disk (%)', step: 1 },
  { key: 'cooldown_minutes', label: 'Cooldown (menit)', step: 5 },
]

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

export default function Alerts() {
  const { user } = useAuth()
  const qc = useQueryClient()

  const configQ = useQuery({
    queryKey: ['alert-config'],
    queryFn: api.getAlertConfig,
    enabled: user?.role === 'admin',
  })
  const alertsQ = useQuery({
    queryKey: ['alerts'],
    queryFn: () => api.listAlerts(50),
    enabled: user?.role === 'admin',
    refetchInterval: 8000,
  })

  const [form, setForm] = useState<AlertConfig | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    if (configQ.data) setForm(configQ.data)
  }, [configQ.data])

  const save = useMutation({
    mutationFn: (payload: Partial<AlertConfig>) => api.updateAlertConfig(payload),
    onSuccess: (data) => {
      setForm(data)
      setMsg('Tersimpan & berlaku langsung.')
      void qc.invalidateQueries({ queryKey: ['alert-config'] })
    },
  })

  const run = useMutation({
    mutationFn: api.runAlerts,
    onSuccess: (res) => {
      setMsg(
        res.created > 0
          ? `${res.created} pelanggaran terdeteksi.`
          : 'Tidak ada pelanggaran batas saat ini.',
      )
      void qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  const testEmail = useMutation({
    mutationFn: api.testAlertEmail,
    onSuccess: (res) =>
      setMsg(res.ok ? `Email uji terkirim ke ${res.recipients.join(', ')}.` : res.detail),
  })

  const dlPdf = useMutation({
    mutationFn: async (id: number) => {
      const blob = await api.downloadReportBlob(`/admin/alerts/${id}/pdf`)
      triggerDownload(blob, `peringatan_${id}.pdf`)
    },
  })

  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  if (!form) return <Spinner label="Memuat pengaturan peringatan…" className="p-6" />

  const setField = (key: keyof AlertConfig, value: number | boolean | string) =>
    setForm({ ...form, [key]: value })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">Peringatan & Batas Resource</h1>
          <p className="text-sm text-slate-500">
            Otomatis kirim laporan PDF ke email saat user melewati batas CPU/RAM/GPU/disk.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => run.mutate()}
            className="btn-ghost"
            disabled={run.isPending}
          >
            <IconRefresh className="h-4 w-4" />
            {run.isPending ? 'Mengecek…' : 'Cek sekarang'}
          </button>
          <button
            onClick={() => testEmail.mutate()}
            className="btn-ghost"
            disabled={testEmail.isPending}
          >
            <IconMail className="h-4 w-4" />
            Kirim email uji
          </button>
        </div>
      </div>

      {/* Status SMTP */}
      <div
        className={cn(
          'card-pad flex flex-wrap items-center gap-3 text-sm',
          form.smtp_configured ? 'text-emerald-700' : 'text-amber-700',
        )}
      >
        <span
          className={cn(
            'badge',
            form.smtp_configured
              ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
              : 'bg-amber-50 text-amber-700 ring-amber-600/20',
          )}
        >
          <IconMail className="h-3.5 w-3.5" />
          {form.smtp_configured ? 'SMTP aktif' : 'SMTP belum dikonfigurasi'}
        </span>
        <span className="text-slate-500">
          {form.smtp_configured
            ? `Pengirim: ${form.smtp_from || '—'}`
            : 'Set SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD di .env agar email terkirim.'}
        </span>
        <span className="ml-auto text-slate-500">
          Penerima: <b>{form.recipients.join(', ') || '—'}</b>
        </span>
      </div>

      {/* Konfigurasi ambang */}
      <div className="card-pad space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 font-semibold text-slate-800">
            <IconBell className="h-5 w-5 text-brand-600" />
            Ambang Batas
          </h2>
          <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setField('enabled', e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Aktifkan peringatan otomatis
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {THRESHOLDS.map((t) => (
            <div key={t.key}>
              <label className="label">{t.label}</label>
              <input
                type="number"
                min={0}
                step={t.step}
                className="input"
                value={Number(form[t.key])}
                onChange={(e) => setField(t.key, Number(e.target.value))}
              />
              <p className="mt-1 text-xs text-slate-400">0 = nonaktifkan metrik ini</p>
            </div>
          ))}
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.email_on_breach}
                onChange={(e) => setField('email_on_breach', e.target.checked)}
                className="h-4 w-4 rounded border-slate-300"
              />
              Kirim email saat melanggar
            </label>
          </div>
        </div>

        <div>
          <label className="label">
            Email penerima <span className="text-slate-400">(pisahkan dengan koma; kosong = semua admin)</span>
          </label>
          <input
            className="input"
            placeholder="dosen@unismuh.ac.id, admin@unismuh.ac.id"
            value={form.email_to}
            onChange={(e) => setField('email_to', e.target.value)}
          />
        </div>

        {msg && (
          <div className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700 ring-1 ring-inset ring-brand-600/15">
            {msg}
          </div>
        )}

        <div className="flex gap-2">
          <button
            className="btn-primary"
            disabled={save.isPending}
            onClick={() => {
              setMsg(null)
              save.mutate({
                enabled: form.enabled,
                cpu_cores: form.cpu_cores,
                ram_gb: form.ram_gb,
                vram_gb: form.vram_gb,
                disk_percent: form.disk_percent,
                cooldown_minutes: form.cooldown_minutes,
                email_on_breach: form.email_on_breach,
                email_to: form.email_to,
              })
            }}
          >
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </button>
          <button className="btn-ghost" onClick={() => void configQ.refetch()}>
            Muat ulang
          </button>
        </div>
      </div>

      {/* Riwayat peringatan */}
      <div className="space-y-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
          <IconBell className="h-5 w-5 text-brand-600" />
          Riwayat Peringatan
        </h2>
        <div className="card overflow-hidden">
          {alertsQ.isLoading ? (
            <Spinner label="Memuat riwayat…" className="p-6" />
          ) : !alertsQ.data || alertsQ.data.length === 0 ? (
            <p className="p-6 text-sm text-slate-500">Belum ada peringatan.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="table-th">Waktu</th>
                    <th className="table-th">Subjek</th>
                    <th className="table-th">Metrik</th>
                    <th className="table-th text-right">Nilai / Batas</th>
                    <th className="table-th">Email</th>
                    <th className="table-th text-right">PDF</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {alertsQ.data.map((a) => (
                    <tr key={a.id} className="hover:bg-slate-50">
                      <td className="table-td whitespace-nowrap text-slate-500">
                        {formatDateTime(a.created_at)}
                      </td>
                      <td className="table-td font-semibold text-slate-800">
                        {a.subject}
                      </td>
                      <td className="table-td text-slate-600">
                        {METRIC_LABEL[a.metric] ?? a.metric}
                      </td>
                      <td className="table-td text-right font-medium text-rose-600">
                        {a.value} / {a.threshold}
                      </td>
                      <td className="table-td">
                        {a.emailed ? (
                          <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                            terkirim
                          </span>
                        ) : (
                          <span
                            className="badge bg-slate-100 text-slate-500 ring-slate-500/20"
                            title={a.email_error ?? ''}
                          >
                            tidak terkirim
                          </span>
                        )}
                      </td>
                      <td className="table-td text-right">
                        {a.pdf_path ? (
                          <button
                            onClick={() => dlPdf.mutate(a.id)}
                            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-brand-50 hover:text-brand-600"
                            title="Unduh PDF"
                          >
                            <IconDownload className="h-4 w-4" />
                          </button>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
