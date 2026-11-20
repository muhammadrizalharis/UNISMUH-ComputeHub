// Tombol "Lihat grafik" + modal pemilih folder log TensorBoard (dipakai di Penyimpanan,
// Detail job, dan Notebook). TensorBoard berjalan di container CPU milik user, dibuka di tab baru.
import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, api } from '../lib/api'
import { cn } from '../lib/format'
import type { TensorBoardRuns, TensorBoardSource, TensorBoardStatus } from '../lib/types'
import { IconChart, IconRefresh, IconX } from './icons'

interface Props {
  source?: TensorBoardSource
  jobId?: number
  /** Folder awal (relatif /persist atau folder job). */
  path?: string
  /** Detail job: izinkan pindah antara folder job dan /persist. */
  allowPersist?: boolean
  className?: string
  iconClassName?: string
  label?: string
}

/** Tab dibuka SINKRON saat klik (lolos pemblokir pop-up), lalu diarahkan ke URL tiket. */
function bukaTab(): Window | null {
  const tab = window.open('', '_blank')
  if (tab) {
    tab.document.title = 'TensorBoard'
    tab.document.body.innerHTML =
      '<p style="font-family:system-ui,sans-serif;padding:2rem;color:#475569">Menyiapkan TensorBoard… (±15 detik)</p>'
  }
  return tab
}

function arahkan(tab: Window | null, url: string) {
  if (tab) tab.location.href = url
  else window.location.assign(url)
}

function pesan(e: unknown, cadangan: string): string {
  return e instanceof ApiError ? e.message : cadangan
}

function waktu(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString('id-ID', { dateStyle: 'short', timeStyle: 'short' })
}

export default function TensorBoardButton({
  source = 'persist',
  jobId,
  path = '',
  allowPersist = false,
  className,
  iconClassName = 'h-4 w-4',
  label = 'Lihat grafik',
}: Props) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={className ?? 'btn-ghost'}
        title="Buka TensorBoard untuk melihat grafik loss/akurasi training"
      >
        <IconChart className={iconClassName} />
        {label}
      </button>
      {open &&
        createPortal(
        <TensorBoardModal
          initialSource={source}
          jobId={jobId}
          initialPath={path}
          allowPersist={allowPersist}
          onClose={() => setOpen(false)}
        />,
        document.body,
      )}
    </>
  )
}

function TensorBoardModal({
  initialSource,
  jobId,
  initialPath,
  allowPersist,
  onClose,
}: {
  initialSource: TensorBoardSource
  jobId?: number
  initialPath: string
  allowPersist: boolean
  onClose: () => void
}) {
  const [source, setSource] = useState<TensorBoardSource>(initialSource)
  const [folder, setFolder] = useState(initialPath)
  const [runs, setRuns] = useState<TensorBoardRuns | null>(null)
  const [status, setStatus] = useState<TensorBoardStatus | null>(null)
  const [pilih, setPilih] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const muat = useCallback(async () => {
    setLoading(true)
    setError(null)
    setPilih(null)
    try {
      const [r, s] = await Promise.all([
        api.tensorboardRuns(source, source === 'job' ? jobId : undefined, folder),
        api.tensorboardStatus(),
      ])
      setRuns(r)
      setStatus(s)
    } catch (e) {
      setRuns(null)
      setError(pesan(e, 'Gagal memuat daftar log.'))
    } finally {
      setLoading(false)
    }
  }, [source, jobId, folder])

  useEffect(() => {
    const t = window.setTimeout(() => void muat(), 400)
    return () => window.clearTimeout(t)
  }, [muat])

  const mulai = async () => {
    const tab = bukaTab()
    setBusy(true)
    setError(null)
    try {
      const target = pilih ?? runs?.path ?? folder
      const r = await api.tensorboardStart(source, source === 'job' ? jobId : undefined, target)
      setStatus(r)
      arahkan(tab, r.ticket_url)
    } catch (e) {
      tab?.close()
      setError(pesan(e, 'Gagal menyalakan TensorBoard.'))
    } finally {
      setBusy(false)
    }
  }

  const bukaLagi = async () => {
    const tab = bukaTab()
    try {
      arahkan(tab, (await api.tensorboardTicket()).ticket_url)
    } catch (e) {
      tab?.close()
      setError(pesan(e, 'TensorBoard sudah mati — nyalakan lagi.'))
      void muat()
    }
  }

  const matikan = async () => {
    setBusy(true)
    try {
      await api.tensorboardStop()
      setStatus({ running: false })
    } catch (e) {
      setError(pesan(e, 'Gagal mematikan TensorBoard.'))
    } finally {
      setBusy(false)
    }
  }

  const daftar = runs?.runs ?? []
  const lokasi = source === 'job' ? 'folder job' : '/persist'
  const idleMenit = Math.round((status?.idle_timeout_seconds ?? 900) / 60)

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5 dark:border-slate-800">
          <IconChart className="h-4 w-4 text-brand-500" />
          <span className="flex-1 text-sm font-semibold text-slate-700 dark:text-slate-200">
            Lihat grafik training (TensorBoard)
          </span>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <IconX className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 overflow-y-auto p-4 text-sm">
          {status?.running && (
            <div className="rounded-lg bg-emerald-50 p-3 text-emerald-800 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900">
              <p>
                TensorBoard Anda sedang menyala
                {status.path ? (
                  <>
                    {' '}
                    untuk <code className="text-xs">{status.path}</code>
                  </>
                ) : null}{' '}
                ({status.source === 'persist' ? '/persist' : status.source}).
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" onClick={bukaLagi} className="btn-primary">
                  Buka tab TensorBoard
                </button>
                <button type="button" onClick={matikan} disabled={busy} className="btn-ghost">
                  Matikan
                </button>
              </div>
            </div>
          )}

          {allowPersist && (
            <div className="flex gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
              {(['job', 'persist'] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => {
                    setSource(s)
                    setFolder('')
                  }}
                  className={cn(
                    'flex-1 rounded-md px-2 py-1 text-xs font-medium',
                    source === s
                      ? 'bg-white text-slate-800 shadow dark:bg-slate-700 dark:text-slate-100'
                      : 'text-slate-500',
                  )}
                >
                  {s === 'job' ? 'Folder job ini' : 'Penyimpanan (/persist)'}
                </button>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            <label className="shrink-0 text-xs font-medium text-slate-500">Folder</label>
            <input
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              placeholder={source === 'job' ? '(seluruh folder job)' : '(seluruh /persist)'}
              className="input w-full text-xs"
            />
            <button type="button" onClick={() => void muat()} className="btn-ghost" title="Cari ulang">
              <IconRefresh className={cn('h-4 w-4', loading && 'animate-spin')} />
            </button>
          </div>

          {loading ? (
            <p className="text-slate-500">Mencari log TensorBoard…</p>
          ) : daftar.length > 0 ? (
            <div className="space-y-1">
              <p className="text-xs text-slate-500">
                Ditemukan {daftar.length} run{runs?.truncated ? ' (dipotong — persempit folder)' : ''}. Pilih
                satu, atau tampilkan semuanya untuk dibandingkan.
              </p>
              <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 hover:bg-slate-50 dark:hover:bg-slate-800">
                <input type="radio" checked={pilih === null} onChange={() => setPilih(null)} />
                <span className="font-medium">Semua run di folder ini</span>
              </label>
              <div className="max-h-56 overflow-y-auto">
                {daftar.map((r) => (
                  <label
                    key={r.path}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <input type="radio" checked={pilih === r.path} onChange={() => setPilih(r.path)} />
                    <code className="flex-1 truncate text-xs">{r.path || '(folder ini)'}</code>
                    <span className="shrink-0 text-[11px] text-slate-400">{waktu(r.modified)}</span>
                  </label>
                ))}
              </div>
            </div>
          ) : (
            !error && (
              <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800 ring-1 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900">
                Belum ada log TensorBoard di {lokasi}
                {folder ? ` / ${folder}` : ''}. Contoh PyTorch:
                <pre className="mt-1 whitespace-pre-wrap rounded bg-white/70 p-2 dark:bg-slate-900/60">
                  {"from torch.utils.tensorboard import SummaryWriter\nw = SummaryWriter('/persist/runs/exp1')\nw.add_scalar('loss', loss, step)"}
                </pre>
              </div>
            )
          )}

          {error && <p className="text-rose-600">{error}</p>}

          <p className="text-[11px] text-slate-400">
            TensorBoard berjalan di CPU (tidak memakai GPU) dan mati otomatis setelah {idleMenit} menit tidak
            dibuka. Grafik diperbarui tiap ±30 detik selama training berjalan.
          </p>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-4 py-2.5 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Tutup
          </button>
          <button
            type="button"
            onClick={mulai}
            disabled={busy || loading || daftar.length === 0}
            className="btn-primary"
          >
            {busy ? 'Menyiapkan…' : status?.running ? 'Ganti & buka' : 'Buka TensorBoard'}
          </button>
        </div>
      </div>
    </div>
  )
}
