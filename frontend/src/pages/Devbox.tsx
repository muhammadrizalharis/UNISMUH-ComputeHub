// Devbox — ngoding di VS Code sendiri, sumber daya (CPU/RAM/GPU) dari server kampus.
// Jalur UTAMA: VS Code Desktop di laptop sendiri lewat Remote-SSH yang di-proxy domain
// kampus (tanpa LAN/VPN kampus, tanpa GitHub). Pelengkap: VS Code di BROWSER lewat domain
// yang sama. Cadangan lama: tunnel Microsoft (butuh GitHub sekali).
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  IconChip,
  IconCheck,
  IconCopy,
  IconCpu,
  IconDownload,
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

/** Buka IDE di tab baru: tab dibuka SINKRON saat klik (lolos pemblokir pop-up),
 *  lalu diarahkan ke URL tiket sekali-pakai begitu diterima dari server. */
async function bukaIde(onError: (e: unknown) => void) {
  const tab = window.open('', '_blank')
  try {
    const t = await api.devboxWebTicket()
    if (tab) tab.location.href = t.url
    else window.location.assign(t.url)
  } catch (e) {
    tab?.close()
    onError(e)
  }
}

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

/** VS Code Desktop lewat Remote-SSH: satu pemasang, lalu cukup Connect to Host. */
function DesktopSSH({
  status,
  onError,
}: {
  status: DevboxStatus
  onError: (e: unknown) => void
}) {
  const [sibuk, setSibuk] = useState<'windows' | 'unix' | 'rotate' | null>(null)
  const [pesan, setPesan] = useState<string | null>(null)
  const alias = status.ssh_host ?? 'computehub'

  const unduh = async (os: 'windows' | 'unix') => {
    setSibuk(os)
    setPesan(null)
    try {
      const blob = await api.downloadDevboxSetup(os)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${alias}-setup.${os === 'windows' ? 'ps1' : 'sh'}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setPesan('Pemasang terunduh. Jalankan sekali di laptop ini, lalu buka VS Code.')
    } catch (e) {
      onError(e)
    } finally {
      setSibuk(null)
    }
  }

  const rotasi = async () => {
    if (
      !window.confirm(
        'Buat kunci baru? Laptop yang sudah dipasang sebelumnya akan kehilangan akses ' +
          'dan perlu mengunduh pemasang lagi. Berkas Anda tidak terpengaruh.',
      )
    )
      return
    setSibuk('rotate')
    setPesan(null)
    try {
      await api.rotateDevboxKey()
      setPesan('Kunci baru dibuat. Unduh pemasang lagi di laptop yang ingin dipakai.')
    } catch (e) {
      onError(e)
    } finally {
      setSibuk(null)
    }
  }

  return (
    <div className="space-y-3 text-sm text-slate-600">
      <p>
        Ngoding di <b>VS Code laptop sendiri</b>, tenaganya tetap dari server kampus.
        Tanpa akun GitHub, tanpa layanan luar, dan <b>tanpa perlu WiFi kampus atau VPN</b> —
        bisa dari rumah, kos, atau tethering. Cukup sekali pasang per laptop.
      </p>
      <ol className="space-y-1">
        <li>
          1. Unduh pemasang lalu jalankan sekali (tidak perlu hak administrator):
        </li>
      </ol>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void unduh('windows')}
          disabled={sibuk !== null}
          data-testid="devbox-setup-windows"
        >
          {sibuk === 'windows' ? <Spinner /> : <IconDownload className="h-4 w-4" />}
          Windows
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void unduh('unix')}
          disabled={sibuk !== null}
          data-testid="devbox-setup-unix"
        >
          {sibuk === 'unix' ? <Spinner /> : <IconDownload className="h-4 w-4" />}
          macOS / Linux
        </button>
      </div>
      <ol className="space-y-1" start={2}>
        <li>
          2. Di VS Code: pasang extension <b>Remote - SSH</b> (sekali saja), lalu tekan{' '}
          <kbd className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">F1</kbd> →{' '}
          <b>Remote-SSH: Connect to Host</b> →{' '}
          <code className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">{alias}</code>
        </li>
        <li>
          3. <b>File › Open Folder</b> →{' '}
          <code className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">
            /{status.folder || 'persist'}
          </code>
        </li>
      </ol>
      {pesan && (
        <p role="status" className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800 ring-1 ring-inset ring-emerald-600/20">
          {pesan}
        </p>
      )}
      <p className="text-xs text-slate-500">
        Devbox yang sedang mati akan menyala sendiri saat Anda menyambung dari VS Code.
        {' '}Ganti laptop? Jalankan pemasang di laptop baru.{' '}
        <button
          type="button"
          className="underline hover:text-slate-700"
          onClick={() => void rotasi()}
          disabled={sibuk !== null}
          data-testid="devbox-rotate-key"
        >
          Laptop hilang — buat kunci baru
        </button>
        .
      </p>
    </div>
  )
}

/** Devbox siap: VS Code Desktop (utama) + buka di browser (pelengkap). */
function SiapDipakai({
  status,
  onError,
}: {
  status: DevboxStatus
  onError: (e: unknown) => void
}) {
  const webAktif = status.web_enabled !== false
  const sshAktif = status.ssh_enabled !== false
  const [bukaTunnel, setBukaTunnel] = useState(false)
  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-emerald-50 p-4 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-500/10">
        <p className="text-sm font-semibold text-emerald-800">Devbox Anda siap dipakai.</p>
        <p className="mt-1 text-sm text-emerald-700">
          Koneksi VS Code: {status.client_connected == null
            ? 'Belum terdeteksi'
            : status.client_connected ? 'Tersambung' : 'Terputus'}
        </p>
        <p className="mt-1 text-sm text-emerald-700">
          Kode dan berkas tersimpan di ruang kerja Anda (sama dengan menu Penyimpanan)
          {status.folder ? (
            <>
              , folder{' '}
              <code className="rounded bg-white/70 px-1.5 py-0.5 text-xs">/{status.folder}</code>
            </>
          ) : null}
          .
        </p>
      </div>

      {sshAktif && (
        <div className="rounded-xl bg-white p-4 ring-1 ring-inset ring-indigo-600/20 dark:bg-white/5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-slate-800">Pakai VS Code di komputer Anda</p>
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-700 ring-1 ring-inset ring-indigo-600/20">
              Cara utama
            </span>
          </div>
          <div className="mt-2">
            <DesktopSSH status={status} onError={onError} />
          </div>
        </div>
      )}

      <div className="rounded-xl bg-slate-50 p-4 text-sm ring-1 ring-inset ring-slate-900/5 dark:bg-white/5">
        {webAktif && status.web_url ? (
          <>
            <p className="font-semibold text-slate-700">
              {sshAktif ? 'Sedang di komputer lain? Buka di browser' : 'Buka VS Code di browser'}
            </p>
            <button
              type="button"
              className={`mt-2 ${sshAktif ? 'btn-ghost' : 'btn btn-primary'}`}
              onClick={() => void bukaIde(onError)}
              data-testid="devbox-open-web"
            >
              <IconTerminal className="h-4 w-4" />
              Buka VS Code di browser
            </button>
            <p className="mt-2 text-xs text-slate-500">
              Tanpa memasang apa pun — cocok untuk komputer lab atau pinjaman. Terbuka di tab
              baru lewat alamat kampus ini: tanpa login GitHub, tanpa layanan Microsoft.
              Kalau tab tidak muncul, izinkan pop-up untuk situs ini.
            </p>
          </>
        ) : webAktif ? (
          <p className="flex items-center gap-2 text-slate-600">
            <Spinner /> {status.message || 'VS Code di server sedang dinyalakan ulang…'}
          </p>
        ) : (
          <p className="font-semibold text-slate-700">Jalur browser sedang dimatikan admin.</p>
        )}
      </div>

      {sshAktif ? (
        <details className="rounded-xl bg-slate-50 p-4 text-xs ring-1 ring-inset ring-slate-900/5 dark:bg-white/5">
          <summary className="cursor-pointer font-semibold text-slate-600">
            Cara lama: tunnel Microsoft (butuh akun GitHub)
          </summary>
          <div className="mt-2 space-y-2">
            <TunnelDesktop status={status} onError={onError} />
          </div>
        </details>
      ) : (
        <div className="rounded-xl bg-slate-50 p-4 text-sm ring-1 ring-inset ring-slate-900/5 dark:bg-white/5">
          {webAktif ? (
            <button
              type="button"
              className="flex w-full items-center justify-between text-left font-semibold text-slate-700"
              onClick={() => setBukaTunnel((v) => !v)}
              aria-expanded={bukaTunnel}
            >
              <span>Pakai VS Code Desktop di komputer Anda (opsional)</span>
              <span className="text-xs font-normal text-slate-500">
                {bukaTunnel ? 'Tutup' : 'Lihat cara'}
              </span>
            </button>
          ) : (
            <p className="font-semibold text-slate-700">Pakai VS Code di komputer Anda</p>
          )}
          {(bukaTunnel || !webAktif) && (
            <div className="mt-2 space-y-3 text-slate-600">
              <TunnelDesktop status={status} onError={onError} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Cara lama: VS Code Desktop lewat tunnel Microsoft (butuh GitHub, lewat relay Azure). */
function TunnelDesktop({
  status,
  onError,
}: {
  status: DevboxStatus
  onError: (e: unknown) => void
}) {
  const qc = useQueryClient()
  const webAktif = status.web_enabled !== false
  const tunnelMut = useMutation({
    mutationFn: () => api.startDevboxTunnel(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devbox'] }),
    onError,
  })
  const tunnel = status.tunnel_state ?? 'off'
  const tunnelSiap = tunnel === 'running' && !!status.tunnel_url
  return (
    <div className="space-y-3 text-slate-600">
      {webAktif && (
        <p className="text-xs text-slate-500">
          Jalur ini melewati layanan tunnel Microsoft dan butuh akun GitHub (sekali).
          Dari dalam kampus koneksinya bisa tersendat; dua cara di atas tidak.
        </p>
      )}
      {webAktif && (tunnel === 'off' || tunnel === 'error') && (
        <div className="space-y-2">
          {tunnel === 'error' && status.tunnel_message && (
            <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-inset ring-rose-600/15">
              {status.tunnel_message}
            </p>
          )}
          <button
            type="button"
            className="btn-ghost"
            onClick={() => tunnelMut.mutate()}
            disabled={tunnelMut.isPending}
            data-testid="devbox-start-tunnel"
          >
            {tunnelMut.isPending ? <Spinner /> : <IconGithub className="h-4 w-4" />}
            {tunnel === 'error' ? 'Coba siapkan tunnel lagi' : 'Siapkan tunnel VS Code Desktop'}
          </button>
        </div>
      )}
      {webAktif && tunnel === 'starting' && (
        <p className="flex items-center gap-2 text-sm">
          <Spinner /> {status.tunnel_message || 'Menyiapkan tunnel…'}
        </p>
      )}
      {webAktif && tunnel === 'needs_login' && <KodeLogin status={status} />}
      {(tunnelSiap || !webAktif) && (
        <ol className="space-y-1">
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
          <li>
            4. Jendela terbuka kosong — itu normal. Pilih <b>File › Open Folder</b>, lalu buka{' '}
            <code className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-300">
              /{status.folder || 'persist'}
            </code>{' '}
            untuk melihat berkas Anda.
          </li>
          {webAktif && status.tunnel_url && (
            <li className="pt-1 text-xs text-slate-500">
              Tunnel aktif: <code className="rounded bg-white px-1 py-0.5 ring-1 ring-slate-300">{status.tunnel_name}</code>
              {' '}·{' '}
              <a className="underline" href={status.tunnel_url} target="_blank" rel="noreferrer noopener">
                vscode.dev (lewat Microsoft)
              </a>
            </li>
          )}
        </ol>
      )}
    </div>
  )
}

export default function Devbox() {
  const qc = useQueryClient()
  const [pesan, setPesan] = useState<string | null>(null)

  const q = useQuery({
    queryKey: ['devbox'],
    queryFn: () => api.getDevbox(),
    // Saat sedang disiapkan/menunggu otorisasi (termasuk tunnel opsional), pantau lebih sering.
    refetchInterval: (query) => {
      const d = query.state.data
      const sibuk =
        (AKTIF.includes(d?.state ?? '') && d?.state !== 'running') ||
        (d?.state === 'running' && (!d.web_url && d.web_enabled !== false)) ||
        d?.tunnel_state === 'starting' ||
        d?.tunnel_state === 'needs_login'
      return sibuk ? 3000 : 15000
    },
  })
  const status = q.data
  const state = status?.state ?? 'stopped'
  const berjalan = AKTIF.includes(state)

  const segarkan = () => qc.invalidateQueries({ queryKey: ['devbox'] })
  const gagal = (e: unknown, fallback: string) =>
    setPesan(e instanceof ApiError ? e.message : fallback)

  const startMut = useMutation({
    mutationFn: (gpu?: boolean) => api.startDevbox(gpu),
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
              Nyalakan, lalu buka VS Code langsung di browser lewat alamat kampus ini — tanpa
              akun GitHub, tanpa layanan luar. GPU diberikan otomatis selama masih tersedia dan
              kuota harian Anda belum habis — tidak perlu memilih apa pun. Devbox berhenti
              sendiri saat lama tidak dipakai supaya server tetap lega.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => startMut.mutate(undefined)}
              disabled={sibuk}
            >
              {startMut.isPending ? <Spinner /> : <IconPlay className="h-4 w-4" />}
              Nyalakan devbox
            </button>
          </div>
        )}

        {berjalan && state !== 'queued' && status?.device === 'cpu' && status.message && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-inset ring-amber-500/20">
            {status.message}
          </p>
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
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <Spinner /> {status?.message || 'Menyiapkan lingkungan Anda…'}
            </div>
            <p className="text-xs text-slate-500">
              Biasanya hanya beberapa detik. Pemakaian pertama bisa lebih lama karena VS Code
              menyiapkan servernya di sisi kampus. Biarkan halaman ini terbuka.
            </p>
          </div>
        )}

        {state === 'needs_login' && status && <KodeLogin status={status} />}

        {state === 'running' && status?.disconnect_remaining_seconds != null && (
          <p role="status" className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-inset ring-amber-500/20">
            VS Code terputus. Penghentian otomatis dalam sekitar{' '}
            <b className="tabular-nums">{Math.ceil(status.disconnect_remaining_seconds)} detik</b>.
            {' '}Sambungkan kembali untuk membatalkan penghentian.
          </p>
        )}

        {state === 'running' && status && (
          <SiapDipakai status={status} onError={(e) => gagal(e, 'Gagal membuka VS Code.')} />
        )}

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
                      'dan sambungan GitHub (bila pernah dibuat) perlu diulang. Berkas di Penyimpanan TIDAK terhapus.',
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
          {(status?.disconnect_timeout_seconds ?? 0) > 0 && (
            <li>
              Devbox mati otomatis setelah semua koneksi VS Code terputus selama{' '}
              <b>{durasi(status?.disconnect_timeout_seconds)}</b>, diperiksa berkala.
              {' '}Program di dalamnya ikut berhenti; berkas yang sudah disimpan tetap ada.
              {' '}Untuk pekerjaan yang ditinggal setelah VS Code ditutup, gunakan Job Batch.
            </li>
          )}
          <li>
            Devbox berhenti otomatis saat menganggur
            {status?.max_lifetime_seconds
              ? ` atau melewati ${durasi(status.max_lifetime_seconds)}`
              : ''}
            . Berkas tetap aman.
          </li>
          {status?.web_enabled !== false ? (
            <li>
              VS Code dibuka lewat alamat kampus ini, bukan lewat layanan Microsoft — jadi
              tidak terpengaruh gangguan jaringan kampus ke luar. Tunnel Microsoft hanya
              dipakai bila Anda memilih VS Code Desktop (opsional).
            </li>
          ) : (
            <li>
              Menyalakan devbox melewati layanan tunnel Microsoft. Bila jaringan kampus ke
              sana sedang tersendat, ComputeHub mengulanginya sendiri beberapa kali dulu
              sebelum menyerah — jadi tunggu saja prosesnya.
            </li>
          )}
        </ul>
        <p className="flex items-center gap-1.5 pt-1 text-xs text-slate-500">
          <IconGithub className="h-3.5 w-3.5" />
          Akun GitHub hanya diminta bila Anda memakai VS Code Desktop lewat tunnel.
        </p>
      </div>
    </div>
  )
}
