import { useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import type { JobCreate, JobDevice, JobSource, PoolStatus } from '../lib/types'

export const SOURCE_LABELS: Record<JobSource, string> = {
  paste: 'Tempel Kode',
  notebook: 'Notebook (.ipynb)',
  upload: 'Upload ZIP',
  git: 'GitHub',
  command: 'Perintah',
}

export default function SubmitJobForm({
  initialSource = 'paste',
  onDone,
  onCancel,
}: {
  initialSource?: JobSource
  onDone: () => void
  onCancel?: () => void
}) {
  const { user } = useAuth()
  const isAdvanced = user?.role === 'dosen' || user?.role === 'admin'

  const capQ = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities })
  const maxUploadMb = capQ.data?.policy?.max_upload_size_mb ?? 200

  const poolsQ = useQuery({
    queryKey: ['pools'],
    queryFn: api.getPools,
    refetchInterval: 10_000,
  })
  const pools = poolsQ.data
  const allowCpu = pools?.allow_cpu_jobs ?? true

  const [name, setName] = useState('')
  const [sourceType, setSourceType] = useState<JobSource>(initialSource)
  const [device, setDevice] = useState<JobDevice>('gpu')
  const [code, setCode] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [repoRef, setRepoRef] = useState('')
  const [command, setCommand] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [priority, setPriority] = useState(20)
  const [vram, setVram] = useState(0)
  const [timeLimitMin, setTimeLimitMin] = useState(0)
  const [autoInstall, setAutoInstall] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const isUploadKind = sourceType === 'upload' || sourceType === 'notebook'
  const sources: JobSource[] = isAdvanced
    ? ['paste', 'notebook', 'upload', 'git', 'command']
    : ['paste', 'notebook', 'upload', 'git']

  const mutation = useMutation({
    mutationFn: async () => {
      const tlSec = isAdvanced && timeLimitMin > 0 ? timeLimitMin * 60 : undefined
      if (isUploadKind) {
        if (!file) {
          throw new ApiError(
            400,
            sourceType === 'notebook' ? 'Pilih file .ipynb.' : 'Pilih file .zip.',
          )
        }
        const fd = new FormData()
        if (name.trim()) fd.append('name', name.trim())
        fd.append('device', device)
        if (isAdvanced) {
          if (command.trim()) fd.append('command', command.trim())
          if (tlSec) fd.append('time_limit_seconds', String(tlSec))
          fd.append('requested_gpu_memory_mb', String(vram))
          fd.append('auto_install', String(autoInstall))
        }
        fd.append('file', file)
        return api.uploadJob(fd)
      }
      const payload: JobCreate = {
        source_type: sourceType,
        name: name.trim() || null,
        device,
      }
      if (sourceType === 'paste') payload.code = code
      if (sourceType === 'git') {
        payload.repo_url = repoUrl.trim()
        if (repoRef.trim()) payload.repo_ref = repoRef.trim()
      }
      if (sourceType === 'command') payload.command = command.trim()
      if (isAdvanced) {
        payload.priority = priority
        if (tlSec) payload.time_limit_seconds = tlSec
        payload.requested_gpu_memory_mb = vram
        payload.auto_install = autoInstall
      }
      return api.submitJob(payload)
    },
    onSuccess: onDone,
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : 'Gagal submit job.'),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    mutation.mutate()
  }

  return (
    <form onSubmit={submit} className="card-pad space-y-4">
      <h2 className="font-semibold text-slate-800">Submit job baru</h2>

      {/* Sumber program */}
      <div>
        <label className="label">Sumber program</label>
        <div className="inline-flex flex-wrap gap-0.5 rounded-lg border border-slate-300 p-0.5">
          {sources.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSourceType(s)}
              className={cn(
                'rounded-md px-3 py-1.5 text-sm font-medium transition',
                sourceType === s
                  ? 'bg-brand-600 text-white'
                  : 'text-slate-600 hover:bg-slate-100',
              )}
            >
              {SOURCE_LABELS[s]}
            </button>
          ))}
        </div>
      </div>

      {/* Pilih perangkat komputasi (GPU / CPU) + status pool */}
      {allowCpu && (
        <div>
          <label className="label">Perangkat komputasi</label>
          <div className="inline-flex flex-wrap gap-0.5 rounded-lg border border-slate-300 p-0.5">
            {(['gpu', 'cpu'] as JobDevice[]).map((d) => {
              const full = d === 'gpu' ? pools?.gpu.full : pools?.cpu.full
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDevice(d)}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-sm font-medium transition',
                    device === d
                      ? 'bg-brand-600 text-white'
                      : 'text-slate-600 hover:bg-slate-100',
                  )}
                >
                  {d === 'gpu' ? 'GPU' : 'CPU'}
                  {full && (
                    <span
                      className={cn(
                        'ml-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle',
                        device === d ? 'bg-amber-300' : 'bg-amber-500',
                      )}
                    />
                  )}
                </button>
              )
            })}
          </div>
          <PoolStatusHint pools={pools} device={device} />
        </div>
      )}

      <div>
        <label className="label">
          Nama job <span className="text-slate-400">(opsional)</span>
        </label>
        <input
          className="input"
          placeholder="mis. latihan-cnn"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {sourceType === 'paste' && (
        <div>
          <label className="label">Kode Python</label>
          <textarea
            className="textarea h-44"
            placeholder={'import torch\nprint(torch.cuda.get_device_name(0))'}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
        </div>
      )}

      {sourceType === 'notebook' && (
        <FilePick
          label="Notebook (.ipynb)"
          accept=".ipynb"
          onPick={setFile}
          hint={`Unggah 1 file notebook .ipynb (maks ${maxUploadMb} MB). Sel kode dijalankan otomatis.`}
        />
      )}

      {sourceType === 'upload' && (
        <FilePick
          label="Folder project (.zip)"
          accept=".zip"
          onPick={setFile}
          hint={`Zip seluruh folder project (maks ${maxUploadMb} MB). Entrypoint (main.py / notebook) dideteksi otomatis.`}
        />
      )}

      {sourceType === 'git' && (
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="label">URL repo GitHub</label>
            <input
              className="input"
              placeholder="https://github.com/owner/repo"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="label">Branch / tag / commit (opsional)</label>
            <input
              className="input"
              placeholder="main"
              value={repoRef}
              onChange={(e) => setRepoRef(e.target.value)}
            />
          </div>
        </div>
      )}

      {sourceType === 'command' && (
        <div>
          <label className="label">Perintah</label>
          <textarea
            className="textarea h-20"
            placeholder="/path/ke/.venv/bin/python train.py --epochs 10"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            required
          />
        </div>
      )}

      {!isAdvanced && (
        <div className="rounded-lg bg-brand-50 px-3 py-2 text-xs text-brand-700 ring-1 ring-inset ring-brand-600/15">
          Batas waktu, VRAM, &amp; GPU diatur <b>otomatis</b> oleh sistem. Job
          masuk antrian; jika ada GPU bebas langsung dijalankan.
        </div>
      )}

      {isAdvanced && (
        <div className="rounded-xl border border-slate-200 p-3">
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="text-sm font-medium text-slate-600"
          >
            {showAdvanced ? '▾' : '▸'} Opsi lanjutan (dosen/admin)
          </button>
          {showAdvanced && (
            <div className="mt-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <label className="label">Prioritas</label>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    className="input"
                    value={priority}
                    onChange={(e) => setPriority(Number(e.target.value))}
                  />
                </div>
                <div>
                  <label className="label">VRAM (MB)</label>
                  <input
                    type="number"
                    min={0}
                    className="input"
                    value={vram}
                    onChange={(e) => setVram(Number(e.target.value))}
                  />
                </div>
                <div>
                  <label className="label">Batas waktu (menit, 0=auto)</label>
                  <input
                    type="number"
                    min={0}
                    className="input"
                    value={timeLimitMin}
                    onChange={(e) => setTimeLimitMin(Number(e.target.value))}
                  />
                </div>
              </div>
              {(sourceType === 'git' ||
                sourceType === 'upload' ||
                sourceType === 'notebook') && (
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input
                    type="checkbox"
                    checked={autoInstall}
                    onChange={(e) => setAutoInstall(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300"
                  />
                  Install <code className="text-xs">requirements.txt</code> otomatis
                </label>
              )}
              {(sourceType === 'git' ||
                sourceType === 'upload' ||
                sourceType === 'notebook') && (
                <div>
                  <label className="label">Perintah override (opsional)</label>
                  <input
                    className="input"
                    placeholder="kosong = deteksi otomatis"
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          {error}
        </div>
      )}

      <div className="flex gap-2">
        <button type="submit" className="btn-primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Mengirim…' : 'Submit'}
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={onCancel ?? onDone}
        >
          Batal
        </button>
      </div>
    </form>
  )
}

function PoolStatusHint({
  pools,
  device,
}: {
  pools?: PoolStatus
  device: JobDevice
}) {
  if (!pools) return null
  if (device === 'cpu') {
    const { used, total, full } = pools.cpu
    return (
      <p
        className={cn(
          'mt-1 text-xs',
          full ? 'text-amber-600' : 'text-emerald-600',
        )}
      >
        {full
          ? `CPU sedang penuh (${used}/${total} core terpakai) — job masuk antrian.`
          : `CPU tersedia (${total - used}/${total} core bebas).`}
      </p>
    )
  }
  const { full, available, count } = pools.gpu
  return (
    <p
      className={cn(
        'mt-1 text-xs',
        full ? 'text-amber-600' : 'text-emerald-600',
      )}
    >
      {full
        ? `GPU sedang penuh — job masuk antrian.`
        : `GPU tersedia (${available ? count : 0}/${count} GPU siap).`}
    </p>
  )
}

function FilePick({
  label,
  accept,
  onPick,
  hint,
}: {
  label: string
  accept: string
  onPick: (f: File | null) => void
  hint: string
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type="file"
        accept={accept}
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
        className="block w-full rounded-lg border border-slate-300 text-sm file:mr-3 file:border-0 file:bg-brand-50 file:px-4 file:py-2 file:text-brand-700 hover:file:bg-brand-100"
        required
      />
      <p className="mt-1 text-xs text-slate-400">{hint}</p>
    </div>
  )
}
