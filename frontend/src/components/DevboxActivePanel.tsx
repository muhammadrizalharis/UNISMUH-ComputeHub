import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import RefreshButton from './RefreshButton'
import Spinner from './Spinner'
import { IconChip, IconCpu, IconStop, IconTerminal } from './icons'
import { api } from '../lib/api'
import { cn } from '../lib/format'

const DEVBOX_STATE_LABEL: Record<string, { teks: string; kelas: string }> = {
  running: { teks: 'Berjalan', kelas: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' },
  starting: { teks: 'Menyiapkan', kelas: 'bg-amber-50 text-amber-700 ring-amber-600/20' },
  needs_login: { teks: 'Menunggu login', kelas: 'bg-amber-50 text-amber-700 ring-amber-600/20' },
  error: { teks: 'Bermasalah', kelas: 'bg-rose-50 text-rose-700 ring-rose-600/20' },
  stopped: { teks: 'Berhenti', kelas: 'bg-slate-100 text-slate-600 ring-slate-500/20' },
}

function fmtDur(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} dtk`
  if (s < 3600) return `${Math.round(s / 60)} mnt`
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return m ? `${h}j ${m}m` : `${h}j`
}

/** Pemantau devbox aktif: siapa yang sedang memakai + tombol hentikan (admin). */
export default function DevboxActivePanel({ showHeading = true }: { showHeading?: boolean }) {
  const qc = useQueryClient()
  const boxesQ = useQuery({
    queryKey: ['admin-devbox'],
    queryFn: api.listDevboxes,
    refetchInterval: 15000,
  })
  const stopMut = useMutation({
    mutationFn: (userId: number) => api.stopUserDevbox(userId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin-devbox'] }),
  })
  const diskQ = useQuery({ queryKey: ['admin-devbox-disk'], queryFn: api.devboxDisk })

  const rows = boxesQ.data ?? []
  const pakaiGpu = rows.filter((b) => b.device === 'gpu').length
  const diskMb = (diskQ.data?.total_bytes ?? 0) / 1024 / 1024

  return (
    <div className="space-y-3" data-testid="devbox-active-panel">
      {showHeading && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
            <IconTerminal className="h-5 w-5 text-brand-600" />
            Devbox VS Code Aktif
          </h2>
          <RefreshButton onRefresh={() => boxesQ.refetch()} />
        </div>
      )}

      <div className="card overflow-hidden">
        {boxesQ.isLoading ? (
          <Spinner label="Memuat devbox…" className="p-6" />
        ) : rows.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">
            Tidak ada devbox yang menyala. Devbox mati otomatis saat menganggur.
          </p>
        ) : (
          <>
            <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-600">
              {rows.length} devbox menyala · {pakaiGpu} memakai GPU
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="table-th">Pengguna</th>
                    <th className="table-th">Status</th>
                    <th className="table-th">Perangkat</th>
                    <th className="table-th">Menyala</th>
                    <th className="table-th">Menganggur</th>
                    <th className="table-th">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {rows.map((b) => {
                    const st = DEVBOX_STATE_LABEL[b.state] ?? DEVBOX_STATE_LABEL.stopped
                    return (
                      <tr key={b.user_id}>
                        <td className="table-td">
                          <span className="font-medium text-slate-700">#{b.user_id}</span>
                          {b.tunnel_name && (
                            <span className="ml-2 text-xs text-slate-400">{b.tunnel_name}</span>
                          )}
                        </td>
                        <td className="table-td">
                          <span
                            className={cn(
                              'inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
                              st.kelas,
                            )}
                          >
                            {st.teks}
                          </span>
                        </td>
                        <td className="table-td">
                          <span className="inline-flex items-center gap-1.5 text-xs">
                            {b.device === 'gpu' ? (
                              <>
                                <IconChip className="h-3.5 w-3.5 text-brand-600" />
                                GPU {b.gpu_index ?? '-'}
                              </>
                            ) : (
                              <>
                                <IconCpu className="h-3.5 w-3.5 text-slate-500" />
                                CPU
                              </>
                            )}
                          </span>
                        </td>
                        <td className="table-td">{fmtDur(b.uptime_seconds ?? 0)}</td>
                        <td className="table-td">{fmtDur(b.idle_seconds ?? 0)}</td>
                        <td className="table-td">
                          <button
                            className="inline-flex items-center gap-1.5 text-xs font-medium text-rose-600 hover:text-rose-700 disabled:opacity-50"
                            disabled={stopMut.isPending}
                            onClick={() => stopMut.mutate(b.user_id)}
                          >
                            <IconStop className="h-3.5 w-3.5" />
                            Hentikan
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <p className="text-xs text-slate-500">
        Penyimpanan devbox (server VS Code &amp; extension per pengguna):{' '}
        <b>{diskMb >= 1024 ? `${(diskMb / 1024).toFixed(1)} GB` : `${Math.round(diskMb)} MB`}</b>
        {' · '}
        {diskQ.data?.users.length ?? 0} pengguna
        {(diskQ.data?.retention_days ?? 0) > 0 && (
          <> · dibersihkan otomatis setelah {diskQ.data?.retention_days} hari tak dipakai</>
        )}
        . Terpisah dari kuota Penyimpanan pengguna.
      </p>
    </div>
  )
}
