import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import Avatar from '../components/Avatar'
import Spinner from '../components/Spinner'
import {
  IconChevron,
  IconKey,
  IconMail,
  IconPlus,
  IconSettings,
  IconTrash,
  IconUsers,
  IconX,
} from '../components/icons'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import { ROLE_META } from '../lib/roles'
import type { User, UserCreateResult, UserPolicy, UserRole } from '../lib/types'

const ROLES: UserRole[] = ['admin', 'dosen', 'mahasiswa']

const ROLE_STYLE: Record<UserRole, string> = {
  admin: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  dosen: 'bg-violet-50 text-violet-700 ring-violet-600/20',
  mahasiswa: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

export default function Users() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [policyUser, setPolicyUser] = useState<User | null>(null)
  const [credInfo, setCredInfo] = useState<UserCreateResult | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState<UserRole | 'all'>('all')

  const usersQ = useQuery({
    queryKey: ['users'],
    queryFn: api.listUsers,
    enabled: user?.role === 'admin',
  })

  const onActionError = (err: unknown) =>
    setActionError(err instanceof ApiError ? err.message : 'Operasi gagal.')

  const updateMutation = useMutation({
    mutationFn: (args: {
      id: number
      payload: Partial<{ role: UserRole; is_active: boolean }>
    }) => api.updateUser(args.id, args.payload),
    onSuccess: () => {
      setActionError(null)
      void qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: onActionError,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteUser(id),
    onSuccess: () => {
      setActionError(null)
      void qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: onActionError,
  })

  const resetMutation = useMutation({
    mutationFn: (id: number) => api.resetPassword(id),
    onSuccess: (res) => {
      setActionError(null)
      setCredInfo(res)
      void qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: onActionError,
  })

  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }

  const currentIsSuper = !!user.is_superadmin
  const list = usersQ.data ?? []
  const counts = {
    total: list.length,
    active: list.filter((u) => u.is_active).length,
    admin: list.filter((u) => u.role === 'admin').length,
    dosen: list.filter((u) => u.role === 'dosen').length,
    mahasiswa: list.filter((u) => u.role === 'mahasiswa').length,
  }
  const q = search.trim().toLowerCase()
  const filtered = list.filter((u) => {
    if (roleFilter !== 'all' && u.role !== roleFilter) return false
    if (!q) return true
    return (
      u.name.toLowerCase().includes(q) ||
      u.email.toLowerCase().includes(q) ||
      (u.username ?? '').toLowerCase().includes(q)
    )
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="gradient-text text-2xl font-bold">Users</h1>
          <p className="text-sm text-slate-500">Kelola akun &amp; role pengguna.</p>
        </div>
        <button onClick={() => setShowForm((v) => !v)} className="btn-primary">
          <IconPlus className="h-4 w-4" />
          Tambah User
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <UserStat
          label="Total Pengguna"
          value={counts.total}
          sub={`${counts.active} aktif`}
          gradient="from-slate-700 to-slate-900"
          Icon={IconUsers}
          active={roleFilter === 'all' && !search}
          onClick={() => {
            setRoleFilter('all')
            setSearch('')
          }}
        />
        <UserStat
          label="Administrator"
          value={counts.admin}
          gradient={ROLE_META.admin.avatar}
          Icon={ROLE_META.admin.Icon}
          active={roleFilter === 'admin'}
          onClick={() => setRoleFilter((r) => (r === 'admin' ? 'all' : 'admin'))}
        />
        <UserStat
          label="Dosen"
          value={counts.dosen}
          gradient={ROLE_META.dosen.avatar}
          Icon={ROLE_META.dosen.Icon}
          active={roleFilter === 'dosen'}
          onClick={() => setRoleFilter((r) => (r === 'dosen' ? 'all' : 'dosen'))}
        />
        <UserStat
          label="Mahasiswa"
          value={counts.mahasiswa}
          gradient={ROLE_META.mahasiswa.avatar}
          Icon={ROLE_META.mahasiswa.Icon}
          active={roleFilter === 'mahasiswa'}
          onClick={() =>
            setRoleFilter((r) => (r === 'mahasiswa' ? 'all' : 'mahasiswa'))
          }
        />
      </div>

      {actionError && (
        <div className="flex items-start justify-between gap-3 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          <span>
            <b>Gagal:</b> {actionError}
          </span>
          <button
            onClick={() => setActionError(null)}
            className="shrink-0 text-rose-400 transition hover:text-rose-600"
            title="Tutup"
          >
            <IconX className="h-4 w-4" />
          </button>
        </div>
      )}

      {showForm && (
        <CreateUserForm
          canCreateAdmin={currentIsSuper}
          onDone={(result) => {
            setShowForm(false)
            if (result) setCredInfo(result)
            void qc.invalidateQueries({ queryKey: ['users'] })
          }}
        />
      )}

      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
          <input
            className="input max-w-xs"
            placeholder="Cari nama, email, atau username…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <span className="text-xs text-slate-500">
            {filtered.length} dari {counts.total} pengguna
            {roleFilter !== 'all' && ` · ${ROLE_META[roleFilter].label}`}
          </span>
        </div>
        {usersQ.isLoading ? (
          <Spinner label="Memuat user…" className="p-6" />
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            Tidak ada pengguna yang cocok.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="table-th">Nama</th>
                  <th className="table-th">Email</th>
                  <th className="table-th">Username</th>
                  <th className="table-th">Role</th>
                  <th className="table-th">Status</th>
                  <th className="table-th">Dibuat</th>
                  <th className="table-th"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((u) => {
                  const self = u.id === user.id
                  const locked =
                    self ||
                    !!u.is_superadmin ||
                    (u.role === 'admin' && !currentIsSuper)
                  // Admin biasa tak boleh mengangkat akun ke 'admin' (hanya admin utama).
                  const roleOptions = currentIsSuper
                    ? ROLES
                    : ROLES.filter((r) => r !== 'admin' || r === u.role)
                  return (
                    <tr key={u.id} className="hover:bg-slate-50">
                      <td className="table-td">
                        <div className="flex items-center gap-2.5">
                          <div
                            className={cn(
                              'shrink-0 rounded-full bg-gradient-to-br p-[2px] shadow-sm',
                              ROLE_META[u.role].avatar,
                            )}
                          >
                            <Avatar
                              src={u.avatar}
                              name={u.name}
                              gradient={ROLE_META[u.role].avatar}
                              className="h-8 w-8 rounded-full text-xs ring-2 ring-white"
                            />
                          </div>
                          <span className="font-semibold text-slate-800">
                            {u.name}
                            {self && (
                              <span className="ml-2 text-xs text-slate-400">(Anda)</span>
                            )}
                            {u.is_superadmin && (
                              <span className="ml-2 text-xs text-brand-500">
                                (admin utama)
                              </span>
                            )}
                          </span>
                        </div>
                      </td>
                      <td className="table-td text-slate-600">{u.email}</td>
                      <td className="table-td">
                        {u.username ? (
                          <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600 ring-1 ring-inset ring-slate-200">
                            {u.username}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-300">—</span>
                        )}
                      </td>
                      <td className="table-td">
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              'grid h-6 w-6 shrink-0 place-items-center rounded-md ring-1 ring-inset',
                              ROLE_META[u.role].badge,
                            )}
                          >
                            <RoleIcon role={u.role} className="h-3.5 w-3.5" />
                          </span>
                          <select
                            className={cn('badge cursor-pointer', ROLE_STYLE[u.role])}
                            value={u.role}
                            disabled={locked || updateMutation.isPending}
                            onChange={(e) =>
                              updateMutation.mutate({
                                id: u.id,
                                payload: { role: e.target.value as UserRole },
                              })
                            }
                          >
                            {roleOptions.map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        </div>
                      </td>
                      <td className="table-td">
                        <button
                          disabled={locked || updateMutation.isPending}
                          onClick={() =>
                            updateMutation.mutate({
                              id: u.id,
                              payload: { is_active: !u.is_active },
                            })
                          }
                          className={cn(
                            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition',
                            u.is_active
                              ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
                              : 'bg-slate-100 text-slate-500 ring-slate-500/20',
                            !locked && 'cursor-pointer hover:brightness-95',
                          )}
                        >
                          <span
                            className={cn(
                              'h-1.5 w-1.5 rounded-full',
                              u.is_active ? 'bg-emerald-500' : 'bg-slate-400',
                            )}
                          />
                          {u.is_active ? 'aktif' : 'nonaktif'}
                        </button>
                      </td>
                      <td className="table-td text-slate-500">
                        {formatDateTime(u.created_at)}
                      </td>
                      <td className="table-td text-right">
                        {!locked && (
                          <RowActions
                            busy={resetMutation.isPending || deleteMutation.isPending}
                            onPolicy={() => setPolicyUser(u)}
                            onReset={() => {
                              if (
                                window.confirm(
                                  `Reset password untuk ${u.name}? Password baru akan dibuat & dikirim ke email user.`,
                                )
                              ) {
                                resetMutation.mutate(u.id)
                              }
                            }}
                            onDelete={() => {
                              if (
                                window.confirm(
                                  `Hapus akun ${u.name} (${u.email})? Tindakan ini permanen.`,
                                )
                              ) {
                                deleteMutation.mutate(u.id)
                              }
                            }}
                          />
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {policyUser && (
        <PolicyEditorModal
          user={policyUser}
          onClose={() => setPolicyUser(null)}
          onSaved={() => {
            setPolicyUser(null)
            void qc.invalidateQueries({ queryKey: ['admin-usage'] })
          }}
        />
      )}

      {credInfo && (
        <CredentialsModal info={credInfo} onClose={() => setCredInfo(null)} />
      )}
    </div>
  )
}

function CreateUserForm({
  onDone,
  canCreateAdmin,
}: {
  onDone: (result?: UserCreateResult) => void
  canCreateAdmin: boolean
}) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<UserRole>('mahasiswa')
  const [error, setError] = useState<string | null>(null)
  const roleOptions = canCreateAdmin ? ROLES : ROLES.filter((r) => r !== 'admin')

  const mutation = useMutation({
    mutationFn: () =>
      api.createUser({ name: name.trim(), email: email.trim(), role }),
    onSuccess: (result) => onDone(result),
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : 'Gagal membuat user.'),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    mutation.mutate()
  }

  return (
    <form onSubmit={submit} className="card-pad space-y-4">
      <h2 className="font-semibold text-slate-800">Tambah user baru</h2>
      <p className="text-sm text-slate-500">
        Cukup isi nama, email, &amp; role. Username &amp; password dibuat otomatis —
        password ditampilkan sekali setelah simpan dan dikirim ke email user.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="label">Nama</label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="label">Email</label>
          <input
            type="email"
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="label">Role</label>
          <select
            className="input"
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
          >
            {roleOptions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          {error}
        </div>
      )}

      <div className="flex gap-2">
        <button type="submit" className="btn-primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Menyimpan…' : 'Simpan'}
        </button>
        <button type="button" className="btn-ghost" onClick={() => onDone()}>
          Batal
        </button>
      </div>
    </form>
  )
}

function PolicyEditorModal({
  user,
  onClose,
  onSaved,
}: {
  user: User
  onClose: () => void
  onSaved: () => void
}) {
  const policyQ = useQuery({
    queryKey: ['user-policy', user.id],
    queryFn: () => api.getUserPolicy(user.id),
  })

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-900/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-lg animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="font-semibold text-slate-800">
              Limit khusus — {user.name}
            </h2>
            <p className="text-xs text-slate-500">
              Kosongkan sebuah kolom = ikut pengaturan global.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100"
            title="Tutup"
          >
            <IconX className="h-5 w-5" />
          </button>
        </div>
        {policyQ.isLoading || !policyQ.data ? (
          <Spinner label="Memuat limit…" className="p-8" />
        ) : (
          <PolicyForm userId={user.id} policy={policyQ.data} onSaved={onSaved} />
        )}
      </div>
    </div>
  )
}

function PolicyForm({
  userId,
  policy,
  onSaved,
}: {
  userId: number
  policy: UserPolicy
  onSaved: () => void
}) {
  const qc = useQueryClient()
  const ov = policy.overrides
  const eff = policy.effective

  const [quota, setQuota] = useState(
    ov.daily_gpu_seconds_quota != null
      ? String(ov.daily_gpu_seconds_quota / 3600)
      : '',
  )
  const [conc, setConc] = useState(
    ov.max_concurrent_jobs != null ? String(ov.max_concurrent_jobs) : '',
  )
  const [tlim, setTlim] = useState(
    ov.max_time_limit_seconds != null
      ? String(Math.round(ov.max_time_limit_seconds / 60))
      : '',
  )
  const [vram, setVram] = useState(
    ov.max_gpu_memory_mb != null ? String(ov.max_gpu_memory_mb) : '',
  )
  const [ram, setRam] = useState(ov.max_ram_mb != null ? String(ov.max_ram_mb) : '')
  const [cpu, setCpu] = useState(
    ov.max_cpu_threads != null ? String(ov.max_cpu_threads) : '',
  )
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => {
      const num = (s: string) => (s.trim() === '' ? null : Number(s))
      return api.updateUserPolicy(userId, {
        daily_gpu_seconds_quota:
          quota.trim() === '' ? null : Math.round(Number(quota) * 3600),
        max_concurrent_jobs: num(conc),
        max_time_limit_seconds:
          tlim.trim() === '' ? null : Math.round(Number(tlim) * 60),
        max_gpu_memory_mb: num(vram),
        max_ram_mb: num(ram),
        max_cpu_threads: num(cpu),
      })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['user-policy', userId] })
      onSaved()
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : 'Gagal menyimpan limit.'),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    mutation.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-4 p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label">Kuota GPU harian (jam)</label>
          <input
            type="number"
            min={0}
            step="0.5"
            className="input"
            value={quota}
            onChange={(e) => setQuota(e.target.value)}
            placeholder={`global: ${(eff.daily_gpu_seconds_quota / 3600).toFixed(1)} jam`}
          />
        </div>
        <div>
          <label className="label">Maks job paralel</label>
          <input
            type="number"
            min={0}
            step="1"
            className="input"
            value={conc}
            onChange={(e) => setConc(e.target.value)}
            placeholder={`global: ${eff.max_concurrent_jobs}`}
          />
        </div>
        <div>
          <label className="label">Batas waktu / job (menit)</label>
          <input
            type="number"
            min={0}
            step="1"
            className="input"
            value={tlim}
            onChange={(e) => setTlim(e.target.value)}
            placeholder={`global: ${Math.round(eff.max_time_limit_seconds / 60)} mnt`}
          />
        </div>
        <div>
          <label className="label">Maks VRAM (MB)</label>
          <input
            type="number"
            min={0}
            step="512"
            className="input"
            value={vram}
            onChange={(e) => setVram(e.target.value)}
            placeholder={`global: ${eff.max_gpu_memory_mb}`}
          />
        </div>
        <div>
          <label className="label">Maks RAM (MB)</label>
          <input
            type="number"
            min={0}
            step="512"
            className="input"
            value={ram}
            onChange={(e) => setRam(e.target.value)}
            placeholder={`global: ${eff.max_ram_mb}`}
          />
        </div>
        <div>
          <label className="label">Maks thread CPU</label>
          <input
            type="number"
            min={0}
            step="1"
            className="input"
            value={cpu}
            onChange={(e) => setCpu(e.target.value)}
            placeholder={`global: ${eff.max_cpu_threads || 'default'}`}
          />
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20">
          {error}
        </div>
      )}

      <div className="flex gap-2">
        <button type="submit" className="btn-primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Menyimpan…' : 'Simpan limit'}
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => {
            setQuota('')
            setConc('')
            setTlim('')
            setVram('')
            setRam('')
          }}
        >
          Reset ke global
        </button>
      </div>
    </form>
  )
}

function RoleIcon({ role, className }: { role: UserRole; className?: string }) {
  const I = ROLE_META[role].Icon
  return <I className={className} />
}

function UserStat({
  label,
  value,
  sub,
  gradient,
  Icon,
  active,
  onClick,
}: {
  label: string
  value: number
  sub?: string
  gradient: string
  Icon: (p: { className?: string }) => JSX.Element
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'card flex items-center gap-3 p-4 text-left transition hover-lift',
        active && 'ring-2 ring-brand-400',
      )}
    >
      <span
        className={cn(
          'grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br shadow-sm',
          gradient,
        )}
      >
        <Icon className="h-5 w-5 text-white" />
      </span>
      <div className="min-w-0">
        <div className="text-2xl font-bold leading-tight text-slate-800">{value}</div>
        <div className="truncate text-xs font-medium text-slate-500">{label}</div>
        {sub && (
          <div className="text-[11px] font-medium text-emerald-600">{sub}</div>
        )}
      </div>
    </button>
  )
}

function RowActions({
  busy,
  onPolicy,
  onReset,
  onDelete,
}: {
  busy: boolean
  onPolicy: () => void
  onReset: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative inline-block text-left">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm text-slate-600 ring-1 ring-inset ring-slate-200 transition hover:bg-slate-50 hover:text-slate-800 disabled:opacity-50"
      >
        Aksi
        <IconChevron className={cn('h-3.5 w-3.5 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-1 w-52 overflow-hidden rounded-xl bg-white py-1 text-left shadow-lg ring-1 ring-slate-200 animate-fade-in">
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                onPolicy()
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              <IconSettings className="h-4 w-4 text-slate-400" />
              Kelola Kebijakan
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                onReset()
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              <IconKey className="h-4 w-4 text-slate-400" />
              Reset Password
            </button>
            <div className="my-1 border-t border-slate-100" />
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                onDelete()
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-rose-600 transition hover:bg-rose-50"
            >
              <IconTrash className="h-4 w-4" />
              Hapus Akun
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function CredentialsModal({
  info,
  onClose,
}: {
  info: UserCreateResult
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    if (!info.generated_password) return
    try {
      await navigator.clipboard.writeText(info.generated_password)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-900/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-md animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="font-semibold text-slate-800">Kredensial akun</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100"
            title="Tutup"
          >
            <IconX className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-4 p-5">
          <p className="text-sm text-slate-600">
            Simpan kredensial ini — <b>password hanya ditampilkan sekali</b>.
          </p>
          <div className="space-y-1">
            <label className="label">Username</label>
            <div className="rounded-lg bg-slate-50 px-3 py-2 font-mono text-sm text-slate-800 ring-1 ring-inset ring-slate-200">
              {info.username ?? '—'}
            </div>
          </div>
          <div className="space-y-1">
            <label className="label">Password</label>
            <div className="flex items-center gap-2">
              <div className="flex-1 break-all rounded-lg bg-slate-50 px-3 py-2 font-mono text-sm text-slate-800 ring-1 ring-inset ring-slate-200">
                {info.generated_password ?? '—'}
              </div>
              <button type="button" onClick={copy} className="btn-ghost shrink-0">
                {copied ? 'Tersalin' : 'Salin'}
              </button>
            </div>
          </div>
          <div
            className={cn(
              'flex items-center gap-2 rounded-lg px-3 py-2 text-sm ring-1 ring-inset',
              info.email_sent
                ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
                : 'bg-amber-50 text-amber-700 ring-amber-600/20',
            )}
          >
            <IconMail className="h-4 w-4 shrink-0" />
            {info.email_sent
              ? `Email kredensial terkirim ke ${info.email}`
              : 'Email tidak terkirim (SMTP) — berikan password ini ke user secara manual.'}
          </div>
          <div className="flex justify-end">
            <button type="button" onClick={onClose} className="btn-primary">
              Selesai
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
