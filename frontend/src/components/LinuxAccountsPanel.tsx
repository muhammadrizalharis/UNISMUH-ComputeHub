import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import RefreshButton from './RefreshButton'
import Spinner from './Spinner'
import { IconChevron, IconShield } from './icons'
import { ApiError, api } from '../lib/api'
import { cn, formatDateTime } from '../lib/format'
import type { LinuxAccountLimits, LinuxResourceLimit } from '../lib/types'

type Resource = keyof NonNullable<LinuxAccountLimits['limits']>

const RESOURCES: { key: Resource; label: string; title: string }[] = [
  { key: 'cpu_cores', label: 'Kuota CPU', title: 'Kuota waktu CPU dalam core-equivalent (cpu.max), bukan jumlah thread.' },
  { key: 'memory_high_bytes', label: 'RAM lunak', title: 'Ambang tekanan memori memory.high, bukan batas keras.' },
  { key: 'memory_max_bytes', label: 'RAM maksimum', title: 'Batas keras memory.max pada slice ini dan induknya.' },
  { key: 'tasks', label: 'Tugas', title: 'Batas PID, termasuk thread (pids.max).' },
]

function formatLimitValue(value: number, resource: Resource): string {
  if (resource === 'cpu_cores') return `${value.toLocaleString('id-ID', { maximumFractionDigits: 2 })} core`
  if (resource === 'tasks') return value.toLocaleString('id-ID')
  const gib = value >= 1024 ** 3
  return `${(value / 1024 ** (gib ? 3 : 2)).toLocaleString('id-ID', { maximumFractionDigits: 2 })} ${gib ? 'GiB' : 'MiB'}`
}

function LimitValue({ limit, resource }: { limit?: LinuxResourceLimit; resource: Resource }) {
  if (!limit || limit.state === 'unavailable') return <span className="text-slate-400">Belum terbaca</span>
  if (limit.state === 'unlimited') return <span className="text-slate-500">Tanpa batas</span>
  if (limit.value == null) return <span className="text-slate-400">Belum terbaca</span>
  return (
    <div>
      <span className="font-semibold tabular-nums text-slate-700 dark:text-slate-200">
        {formatLimitValue(limit.value, resource)}
      </span>
      <span className="block text-xs text-slate-500" title={limit.source ?? undefined}>
        {limit.inherited ? 'Dibatasi induk' : 'Batas slice akun'}
      </span>
    </div>
  )
}

export default function LinuxAccountsPanel() {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [expanded, setExpanded] = useState<number | null>(null)
  const query = useQuery({
    queryKey: ['admin-linux-limits'],
    queryFn: api.getLinuxAccountLimits,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    retry: false,
  })
  const snapshot = query.data
  const term = search.trim().toLowerCase()
  const accounts = (snapshot?.users ?? []).filter((account) =>
    (account.username.toLowerCase().includes(term) || String(account.uid).includes(term)) &&
    (filter === 'all' || account.active === (filter === 'active')),
  )

  return (
    <section id="linux-accounts" aria-labelledby="linux-accounts-title" className="min-w-0 space-y-4 border-t border-slate-200 pt-6 dark:border-slate-700">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="linux-accounts-title" className="text-base font-semibold text-slate-800 dark:text-slate-100">Akun Linux</h2>
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-300">
              <IconShield className="h-3.5 w-3.5" /> Baca saja
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Sumber: Linux / cgroup v2
            {snapshot && <> · Pembacaan {formatDateTime(snapshot.collected_at)}</>}
          </p>
        </div>
        <RefreshButton onRefresh={() => query.refetch()} label="Segarkan batas Linux" />
      </div>

      <p className="text-sm text-slate-600 dark:text-slate-300">
        Aturan aktif sistem, tanpa pengaturan pengganti dari ComputeHub. Perubahan admin IT
        terbaca pada pembaruan berikutnya, setiap 30 detik selama halaman aktif.
      </p>

      {query.isPending && <Spinner label="Membaca batas Linux…" />}
      {query.isError && (
        <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">
          {query.error instanceof ApiError ? query.error.message : 'Batas Linux tidak dapat diperbarui.'}
          {snapshot ? ' Data di bawah adalah pembacaan terakhir, bukan kondisi terkini.' : ''}
        </p>
      )}
      {snapshot?.available === false && (
        <p role="status" className="text-sm text-amber-700 dark:text-amber-300">
          {snapshot.reason === 'cgroup_v2_unavailable'
            ? 'Hierarki cgroup v2 tidak tersedia.'
            : 'Pembaca batas Linux belum tersedia.'}
          {' '}Tidak ada nilai batas yang diasumsikan atau aturan sistem yang diubah.
        </p>
      )}

      {snapshot?.available && (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <label className="w-full min-w-0 text-xs font-medium text-slate-600 dark:text-slate-300 sm:w-auto sm:flex-1">
              Akun / UID
              <input className="input mt-1 w-full" type="search" placeholder="Cari akun Linux atau UID" value={search} onChange={(event) => setSearch(event.target.value)} />
            </label>
            <label className="min-w-0 flex-1 text-xs font-medium text-slate-600 dark:text-slate-300 sm:flex-none">
              Status slice
              <select className="input mt-1 w-full" value={filter} onChange={(event) => setFilter(event.target.value)}>
                <option value="all">Semua akun</option>
                <option value="active">Slice aktif</option>
                <option value="inactive">Slice tidak aktif</option>
              </select>
            </label>
            <span className="shrink-0 whitespace-nowrap py-2 text-xs tabular-nums text-slate-500">{accounts.length} / {snapshot.users.length} akun</span>
          </div>

          <div className="max-w-full overflow-x-auto">
            <table className="w-full min-w-[48rem] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700">
                <tr>
                  <th className="py-3 pr-4 font-medium">Akun Linux</th>
                  <th className="px-3 py-3 font-medium">Status slice</th>
                  {RESOURCES.map((resource) => <th key={resource.key} className="px-3 py-3 font-medium" title={resource.title}>{resource.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <Fragment key={account.uid}>
                    <tr className="border-b border-slate-100 dark:border-slate-800">
                      <td className="max-w-[15rem] py-3 pr-4">
                        <button type="button" onClick={() => setExpanded(expanded === account.uid ? null : account.uid)} aria-expanded={expanded === account.uid} aria-controls={`linux-account-${account.uid}`} aria-label={`Rincian akun ${account.username}`} className="flex max-w-full items-start gap-1.5 text-left font-semibold text-brand-700 dark:text-brand-300">
                          <IconChevron className={cn('mt-0.5 h-4 w-4 shrink-0 transition-transform', expanded !== account.uid && '-rotate-90')} />
                          <span className="break-all">{account.username}</span>
                        </button>
                        <span className="ml-[22px] text-xs text-slate-400">UID {account.uid}</span>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500">{account.active ? 'Aktif' : 'Tidak aktif'}</td>
                      {RESOURCES.map((resource) => (
                        <td key={resource.key} className="px-3 py-3"><LimitValue limit={account.limits?.[resource.key]} resource={resource.key} /></td>
                      ))}
                    </tr>
                    {expanded === account.uid && (
                      <tr id={`linux-account-${account.uid}`} className="border-b border-slate-200 bg-slate-50/60 dark:border-slate-700 dark:bg-white/5">
                        <td colSpan={6} className="px-4 py-4">
                          <dl className="grid gap-3 text-xs sm:grid-cols-2">
                            <div><dt className="text-slate-500">Cgroup akun</dt><dd className="mt-1 break-all font-mono text-slate-700 dark:text-slate-200">{account.cgroup}</dd></div>
                            <div><dt className="text-slate-500">Indeks CPU efektif (cpuset)</dt><dd className="mt-1 font-mono text-slate-700 dark:text-slate-200">{account.allowed_cpus ?? 'Belum terbaca'}</dd></div>
                            {RESOURCES.map((resource) => {
                              const limit = account.limits?.[resource.key]
                              return (
                                <div key={resource.key}>
                                  <dt className="text-slate-500">Sumber {resource.label}</dt>
                                  <dd className="mt-1 break-all text-slate-700 dark:text-slate-200">
                                    {limit?.state === 'limited' ? limit.source : limit?.state === 'unlimited' ? 'Tidak ada batas numerik pada slice akun atau induknya' : 'Belum terbaca'}
                                    {limit?.inherited && <span className="block text-slate-500">Nilai lokal: {limit.local_value == null ? 'Tanpa batas' : formatLimitValue(limit.local_value, resource.key)}</span>}
                                  </dd>
                                </div>
                              )
                            })}
                          </dl>
                          {!account.active && <p className="mt-3 text-xs text-slate-500">Slice belum aktif. Konfigurasi tersimpan untuk sesi berikutnya tidak ditafsirkan sebagai batas yang sedang berlaku.</p>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {accounts.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-slate-500">Tidak ada akun Linux yang sesuai.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className="text-xs leading-relaxed text-slate-500">
        Cakupan: proses di slice akun beserta subkelompoknya. Docker dan layanan di luar slice
        tidak tercakup. VRAM GPU bukan batas yang disediakan cgroup v2. Tugas mencakup PID dan thread.
      </p>
    </section>
  )
}