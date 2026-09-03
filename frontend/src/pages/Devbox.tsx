// Devbox — ngoding di VS Code sendiri, sumber daya (CPU/RAM/GPU) dari server kampus.
// Alur: Nyalakan -> (sekali saja) otorisasi akun GitHub via kode perangkat -> buka tunnel.
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  IconChip,
  IconCheck,
  IconCopy,
  IconCpu,
  IconGithub,
  IconPlay,
  IconRefresh,
  IconStop,
  IconTerminal,
  IconTrash,
} from '../components/icons'
import Spinner from '../components/Spinner'
import { ApiError, api } from '../lib/api'
import { cn } from '../lib/format'
import type { DevboxStatus } from '../lib/types'

const AKTIF = ['starting', 'needs_login', 'running', 'queued']

function durasi(detik?: number): string {
  if (!detik || detik <= 0) return '0 menit'
  const j = Math.floor(detik / 3600)
  const m = Math.floor((detik % 3600) / 60)
  if (j > 0) return m > 0 ? `${j} jam ${m} menit` : `${j} jam`
  return `${m} menit`
}

/** Kode perangkat GitHub: besar, mudah dibaca, sekali klik salin. */
function KodeLogin({ status }: { status: DevboxStatus }) {
  const [tersalin, setTersalin] = useState(false)
  const kode = status.device_code ?? ''
  const salin = async () => {
    try {
      await navigator.clipboard.writeText(kode)
      setTersalin(true)
      setTimeout(() => setTersalin(false), 1800)
    } catch {
      /* clipboard bisa ditolak browser — kode tetap terlihat untuk diketik manual */
    }
  }
  return (
    <div className="rounded-xl bg-amber-50 p-4 ring-1 ring-inset ring-amber-500/20 dark:bg-amber-500/10">
      <p className="text-sm font-semibold text-amber-800">
        Satu langkah lagi — hubungkan akun GitHub Anda
      </p>
      <p className="mt-1 text-sm text-amber-700">
        Cukup sekali. Setelah ini devbox Anda langsung menyala tanpa diminta lagi.
      </p>
      <ol className="mt-3 space-y-2 text-sm text-amber-800">
        <li>
          1. Buka{' '}
          <a
            className="font-semibold underline"
            href={status.verification_url || 'https://github.com/login/device'}
            target="_blank"
            rel="noreferrer noopener"
          >
            github.com/login/device
          </a>
        </li>
        <li>2. Masukkan kode di bawah, lalu klik Authorize.</li>
      </ol>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code className="rounded-lg bg-white px-4 py-2 font-mono text-2xl font-bold tracking-[0.3em] text-slate-800 ring-1 ring-inset ring-amber-500/25">
          {kode || '••••-••••'}
        </code>
        <button type="button" className="btn-ghost" onClick={salin} disabled={!kode}>
          {tersalin ? (
            <IconCheck className="h-4 w-4 text-emerald-600" />
          ) : (
            <IconCopy className="h-4 w-4" />
          )}
          {tersalin ? 'Tersalin' : 'Salin kode'}
        </button>
      </div>
    </div>
  )
}

/** Devbox siap: tautan buka di browser + petunjuk VS Code desktop. */
function SiapDipakai({ status }: { status: DevboxStatus }) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-emerald-50 p-4 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-500/10">
        <p className="text-sm font-semibold text-emerald-800">Devbox Anda siap dipakai.</p>
        <p className="mt-1 text-sm text-emerald-700">
          Kode dan berkas tersimpan di ruang kerja Anda (sama dengan menu Penyimpanan).
        </p>
        {status.tunnel_url && (
          <a
            href={status.tunnel_url}
            target="_blank"
            rel="noreferrer noopener"
            className="btn btn-primary mt-3"
          >
            <IconTerminal className="h-4 w-4" />
            Buka di VS Code (browser)
          </a>
        )}
      </div>

      <div className="rounded-xl bg-slate-50 p-4 text-sm ring-1 ring-inset ring-slate-900/5 dark:bg-white/5">
        <p className="font-semibold text-slate-700">Pakai VS Code di komputer Anda</p>
        <ol className="mt-2 space-y-1 text-slate-600">
          <li>1. Buka VS Code (Windows, macOS, atau Linux).</li>
          <li>
            2. Tekan <kbd className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">Ctrl</kbd>
            <span className="px-1">+</span>
            <kbd className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">Shift</kbd>
            <span className="px-1">+</span>
            <kbd className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">P</kbd>{' '}
            lalu pilih <b>Remote Tunnels: Connect to Tunnel</b>.
          </li>
          <li>
            3. Masuk dengan akun GitHub yang sama, lalu pilih tunnel{' '}
            <code className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">
              {status.tunnel_name}
            </code>
            .
          </li>
        </ol>
      </div>
    </div>
  )
}

export default function Devbox() {
  const qc = useQueryClient()
  const [pakaiGpu, setPakaiGpu] = useState(false)
  const [pesan, setPesan] = useState<string | null>(null)

  const q = useQuery({
    queryKey: ['devbox'],
    queryFn: () => api.getDevbox(),
    // Saat sedang disiapkan/menunggu otorisasi, pantau lebih sering.
    refetchInterval: (query) =>
      AKTIF.includes(query.state.data?.state ?? '') &&
      query.state.data?.state !== 'running'
        ? 3000
        : 15000,
  })
  const status = q.data
  const state = status?.state ?? 'stopped'
  const berjalan = AKTIF.includes(state)

  useEffect(() => {
    if (status?.device) setPakaiGpu(status.device === 'gpu')
  }, [status?.device])

  const segarkan = () => qc.invalidateQueries({ queryKey: ['devbox'] })
  const gagal = (e: unknown, fallback: string) =>
    setPesan(e instanceof ApiError ? e.message : fallback)

  const startMut = useMutation({
    mutationFn: (gpu: boolean) => api.startDevbox(gpu),
    onSuccess: () => {
      setPesan(null)
      segarkan()
    },
    onError: (e) => gagal(e, 'Gagal menyalakan devbox.'),
  })
  const stopMut = useMutation({
    mutationFn: () => api.stopDevbox(),
    onSuccess: () => {
      setPesan(null)
      segarkan()
    },
    onError: (e) => gagal(e, 'Gagal menghentikan devbox.'),
  })
  const resetMut = useMutation({
    mutationFn: () => api.resetDevbox(),
    onSuccess: () => {
      setPesan(null)
      segarkan()
    },
    onError: (e) => gagal(e, 'Gagal menyetel ulang devbox.'),
  })

  const sibuk = startMut.isPending || stopMut.isPending || resetMut.isPending

  // Giliran antrian tiba -> langsung nyalakan supaya jatah tak kedaluwarsa.
  useEffect(() => {
    if (status?.state === 'queued' && status.queue_ready && !startMut.isPending) {
      startMut.mutate(status.device === 'gpu')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.state, status?.queue_ready])

  if (status && status.enabled === false) {
    return (
      <div className="card card-pad">
        <h1 className="text-lg font-bold text-slate-800">Devbox belum tersedia</h1>
        <p className="mt-1 text-sm text-slate-500">
          Fitur ini belum diaktifkan administrator. Sementara itu Anda tetap bisa memakai
          Notebook interaktif di menu Submit.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 text-white shadow">
          <IconTerminal className="h-6 w-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-bold leading-tight text-slate-800">
            Devbox — VS Code Anda, Sumber Daya Kampus
          </h1>
          <p className="text-sm text-slate-500">
            Ngoding di VS Code milik Anda sendiri, tapi CPU, RAM, dan GPU-nya milik server
            ComputeHub. Laptop spesifikasi rendah pun tetap dapat GPU.
          </p>
        </div>
      </div>

      {pesan && (
        <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/15">
          {pesan}
        </div>
      )}

      <div className="card card-pad space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
                state === 'running' && 'bg-emerald-100 text-emerald-700',
                (state === 'starting' || state === 'needs_login' || state === 'queued') &&
                  'bg-amber-100 text-amber-700',
                state === 'stopped' && 'bg-slate-100 text-slate-600',
                state === 'error' && 'bg-rose-100 text-rose-700',
              )}
            >
              {state === 'running'
                ? 'Menyala'
                : state === 'starting'
                  ? 'Menyiapkan…'
                  : state === 'needs_login'
                    ? 'Menunggu otorisasi'
                    : state === 'queued'
                      ? 'Dalam antrian'
                      : state === 'error'
                        ? 'Bermasalah'
                        : 'Mati'}
            </span>
            {berjalan && status?.device && (
              <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2.5 py-1 text-xs font-semibold text-brand-700">
                {status.device === 'gpu' ? (
                  <IconChip className="h-3.5 w-3.5" />
                ) : (
                  <IconCpu className="h-3.5 w-3.5" />
                )}
                {status.device === 'gpu' ? 'GPU' : 'CPU'}
              </span>
            )}
          </div>
          <button type="button" className="btn-ghost" onClick={segarkan} disabled={q.isFetching}>
            <IconRefresh className={cn('h-4 w-4', q.isFetching && 'animate-spin')} />
            Segarkan
          </button>
        </div>

        {q.isLoading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Spinner /> Memuat status…
          </div>
        )}

        {!berjalan && !q.isLoading && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Pilih sumber daya yang dibutuhkan, lalu nyalakan. Devbox otomatis berhenti
              saat lama tidak dipakai supaya tidak memboroskan server bersama.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setPakaiGpu(false)}
                className={cn(
                  'flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold ring-1 ring-inset transition',
                  !pakaiGpu
                    ? 'bg-brand-50 text-brand-700 ring-brand-500/30'
                    : 'text-slate-600 ring-slate-900/10 hover:bg-slate-50',
                )}
              >
                <IconCpu className="h-4 w-4" />
                CPU saja
              </button>
              {status?.allow_gpu !== false && (
                <button
                  type="button"
                  onClick={() => setPakaiGpu(true)}
                  className={cn(
                    'flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold ring-1 ring-inset transition',
                    pakaiGpu
                      ? 'bg-brand-50 text-brand-700 ring-brand-500/30'
                      : 'text-slate-600 ring-slate-900/10 hover:bg-slate-50',
                  )}
                >
                  <IconChip className="h-4 w-4" />
                  Dengan GPU
                </button>
              )}
            </div>
            {pakaiGpu && (
              <p className="text-xs text-slate-500">
                Mode GPU memakai kuota GPU harian Anda dan berhenti lebih cepat saat
                menganggur, karena GPU dipakai bersama-sama.
              </p>
            )}
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => startMut.mutate(pakaiGpu)}
              disabled={sibuk}
            >
              {startMut.isPending ? <Spinner /> : <IconPlay className="h-4 w-4" />}
              Nyalakan devbox
            </button>
          </div>
        )}

        {state === 'queued' && status && (
          <div className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-inset ring-amber-500/20">
            <p className="font-semibold">
              {status.queue_ready
                ? 'Giliran Anda tiba — devbox sedang dinyalakan.'
                : `Antrian ke-${status.queue_position ?? 1} dari ${status.queue_waiting ?? 1} penunggu`}
            </p>
            <p className="mt-1 text-amber-800">
              {status.message ??
                'Kapasitas devbox sedang penuh. Biarkan halaman ini terbuka — giliran Anda otomatis diberikan begitu ada yang selesai.'}
            </p>
          </div>
        )}

        {state === 'starting' && (
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <Spinner /> Menyiapkan lingkungan Anda…
          </div>
        )}

        {state === 'needs_login' && status && <KodeLogin status={status} />}

        {state === 'running' && status && <SiapDipakai status={status} />}

        {state === 'error' && (
          <div className="rounded-xl bg-rose-50 p-4 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/15">
            {status?.message || 'Devbox bermasalah. Coba nyalakan ulang.'}
          </div>
        )}

        {berjalan && (
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-900/5 pt-4">
            <button
              type="button"
              className="btn-ghost text-rose-600"
              onClick={() => stopMut.mutate()}
              disabled={sibuk}
            >
              <IconStop className="h-4 w-4" />
              Hentikan
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                if (
                  window.confirm(
                    'Setel ulang lingkungan devbox? Paket yang Anda pasang akan hilang ' +
                      'dan Anda perlu menghubungkan GitHub lagi. Berkas di Penyimpanan TIDAK terhapus.',
                  )
                )
                  resetMut.mutate()
              }}
              disabled={sibuk}
            >
              <IconTrash className="h-4 w-4" />
              Setel ulang
            </button>
            <span className="ml-auto text-xs text-slate-500">
              Menyala {durasi(status?.uptime_seconds)} · berhenti otomatis setelah{' '}
              {durasi(status?.idle_timeout_seconds)} menganggur
            </span>
          </div>
        )}
      </div>

      <div className="card card-pad space-y-2 text-sm text-slate-600">
        <p className="font-semibold text-slate-700">Yang perlu diketahui</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Berkas Anda berada di ruang kerja yang sama dengan menu Penyimpanan dan
            Notebook — tidak ada salinan terpisah.
          </li>
          <li>
            Bisa dipakai dari Windows, macOS, Linux, bahkan hanya lewat browser — termasuk
            dari luar kampus.
          </li>
          <li>
            Batas CPU, RAM, dan GPU mengikuti kebijakan akun Anda, sama seperti job dan
            notebook.
          </li>
          <li>
            Devbox berhenti otomatis saat menganggur
            {status?.max_lifetime_seconds
              ? ` atau melewati ${durasi(status.max_lifetime_seconds)}`
              : ''}
            . Berkas tetap aman.
          </li>
        </ul>
        <p className="flex items-center gap-1.5 pt-1 text-xs text-slate-500">
          <IconGithub className="h-3.5 w-3.5" />
          Otorisasi GitHub hanya dipakai untuk menyambungkan VS Code ke devbox Anda.
        </p>
      </div>
    </div>
  )
}
