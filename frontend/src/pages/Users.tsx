import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import Spinner from '../components/Spinner'
import { IconPlus, IconSettings, IconX } from '../components/icons'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import type { User, UserPolicy, UserRole } from '../lib/types'

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

  const usersQ = useQuery({
    queryKey: ['users'],
    queryFn: api.listUsers,
    enabled: user?.role === 'admin',
  })

  const updateMutation = useMutation({
    mutationFn: (args: {
      id: number
      payload: Partial<{ role: UserRole; is_active: boolean }>
    }) => api.updateUser(args.id, args.payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteUser(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['users'] }),
  })

  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }

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

      {showForm && (
        <CreateUserForm
          onDone={() => {
            setShowForm(false)
            void qc.invalidateQueries({ queryKey: ['users'] })
          }}
        />
      )}

      <div className="card overflow-hidden">
        {usersQ.isLoading ? (
          <Spinner label="Memuat user…" className="p-6" />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="table-th">Nama</th>
                  <th className="table-th">Email</th>
                  <th className="table-th">Role</th>
                  <th className="table-th">Status</th>
                  <th className="table-th">Dibuat</th>
                  <th className="table-th"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {usersQ.data?.map((u) => {
                  const self = u.id === user.id
                  return (
                    <tr key={u.id} className="hover:bg-slate-50">
                      <td className="table-td font-semibold text-slate-800">
                        {u.name}
                        {self && (
                          <span className="ml-2 text-xs text-slate-400">(Anda)</span>
                        )}
                      </td>
                      <td className="table-td text-slate-600">{u.email}</td>
                      <td className="table-td">
                        <select
                          className={cn('badge cursor-pointer', ROLE_STYLE[u.role])}
                          value={u.role}
                          disabled={self || updateMutation.isPending}
                          onChange={(e) =>
                            updateMutation.mutate({
                              id: u.id,
                              payload: { role: e.target.value as UserRole },
                            })
                          }
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="table-td">
                        <button
                          disabled={self || updateMutation.isPending}
                          onClick={() =>
                            updateMutation.mutate({
                              id: u.id,
                              payload: { is_active: !u.is_active },
                            })
                          }
                          className={cn(
                            'badge',
                            u.is_active
                              ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
                              : 'bg-slate-100 text-slate-500 ring-slate-500/20',
                            !self && 'cursor-pointer',
                          )}
                        >
                          {u.is_active ? 'aktif' : 'nonaktif'}
                        </button>
                      </td>
                      <td className="table-td text-slate-500">
                        {formatDateTime(u.created_at)}
                      </td>
                      <td className="table-td text-right">
                        <div className="flex items-center justify-end gap-1">
                          {u.role === 'mahasiswa' && (
                            <button
                              onClick={() => setPolicyUser(u)}
                              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-brand-50 hover:text-brand-600"
                              title="Atur limit khusus mahasiswa ini"
                            >
                              <IconSettings className="h-4 w-4" />
                            </button>
                          )}
                          {!self && (
                            <button
                              onClick={() => {
                                if (window.confirm(`Hapus user ${u.email}?`)) {
                                  deleteMutation.mutate(u.id)
                                }
                              }}
                              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                              title="Hapus"
                            >
                              <IconX className="h-4 w-4" />
                            </button>
                          )}
                        </div>
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
    </div>
  )
}

function CreateUserForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRole>('mahasiswa')
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      api.createUser({ name: name.trim(), email: email.trim(), password, role }),
    onSuccess: onDone,
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
          <label className="label">Password</label>
          <input
            type="password"
            className="input"
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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
            {ROLES.map((r) => (
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
        <button type="button" className="btn-ghost" onClick={onDone}>
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
        <div className="sm:col-span-2">
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
