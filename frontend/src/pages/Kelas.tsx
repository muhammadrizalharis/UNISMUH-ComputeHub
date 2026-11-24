// RUANG KELAS — dosen/admin membuat kelas, mahasiswa bergabung memakai kode kelas.
// /kelas      : daftar kelas saya + gabung dengan kode (+ buat kelas untuk dosen/admin)
// /kelas/:id  : detail kelas; pengajar/admin mengelola kode & anggota, mahasiswa melihat
//               pengajar dan bisa keluar dari kelas.
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import { ROLE_META } from '../lib/roles'
import type { ClassMemberRole, ClassMembersAddResult, ClassroomSummary } from '../lib/types'
import {
  IconArrowLeft,
  IconChalkboard,
  IconCopy,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconUsers,
} from '../components/icons'
import Spinner from '../components/Spinner'

const errMsg = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

function Pill({ children, cls }: { children: React.ReactNode; cls: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset',
        cls,
      )}
    >
      {children}
    </span>
  )
}

const MY_ROLE: Record<string, { label: string; cls: string }> = {
  pengajar: { label: 'Pengajar', cls: 'bg-violet-50 text-violet-700 ring-violet-600/20' },
  mahasiswa: { label: 'Peserta', cls: 'bg-sky-50 text-sky-700 ring-sky-600/20' },
  admin: { label: 'Admin', cls: 'bg-brand-50 text-brand-700 ring-brand-600/20' },
}

function Notice({ kind, children }: { kind: 'ok' | 'err'; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        'rounded-xl px-4 py-3 text-sm ring-1 ring-inset',
        kind === 'ok'
          ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/15'
          : 'bg-rose-50 text-rose-700 ring-rose-600/15',
      )}
    >
      {children}
    </div>
  )
}

function formatCode(code: string) {
  return code.length === 8 ? `${code.slice(0, 4)}-${code.slice(4)}` : code
}

export default function Kelas() {
  const { id } = useParams()
  return id ? <KelasDetail id={Number(id)} /> : <KelasList />
}

function Header({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 text-white shadow">
        <IconChalkboard className="h-6 w-6" />
      </span>
      <div className="min-w-0">
        <h1 className="text-lg font-bold leading-tight text-slate-800">{title}</h1>
        <p className="text-sm text-slate-500">{subtitle}</p>
      </div>
    </div>
  )
}

function ClassCard({ c }: { c: ClassroomSummary }) {
  const role = MY_ROLE[c.my_role] ?? MY_ROLE.mahasiswa
  return (
    <Link
      to={`/kelas/${c.id}`}
      className={cn('card block p-4 transition hover:shadow-md', c.archived && 'opacity-60')}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Pill cls={role.cls}>{role.label}</Pill>
        {c.archived && <Pill cls="bg-slate-100 text-slate-600 ring-slate-500/20">Diarsipkan</Pill>}
      </div>
      <h3 className="truncate font-semibold text-slate-800">{c.name}</h3>
      <p className="truncate text-xs text-slate-500">
        Pengajar: {c.teachers.join(', ') || '—'}
      </p>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
        <IconUsers className="h-3.5 w-3.5" />
        {c.student_count} peserta
      </p>
    </Link>
  )
}

function KelasList() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const isAdmin = user?.role === 'admin'
  const canCreate = isAdmin || user?.role === 'dosen'
  const [scope, setScope] = useState<'mine' | 'all'>('mine')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [joinErr, setJoinErr] = useState<string | null>(null)
  const [createErr, setCreateErr] = useState<string | null>(null)

  const listQ = useQuery({
    queryKey: ['classrooms', scope],
    queryFn: () => api.listClassrooms(scope),
  })

  const joinM = useMutation({
    mutationFn: () => api.joinClassroom(code.trim()),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ['classrooms'] })
      navigate(`/kelas/${c.id}`)
    },
    onError: (e) => setJoinErr(errMsg(e, 'Gagal bergabung.')),
  })

  const createM = useMutation({
    mutationFn: () => api.createClassroom(name.trim(), desc.trim()),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ['classrooms'] })
      navigate(`/kelas/${c.id}`)
    },
    onError: (e) => setCreateErr(errMsg(e, 'Gagal membuat kelas.')),
  })

  const rooms = listQ.data ?? []
  const aktif = rooms.filter((r) => !r.archived)
  const arsip = rooms.filter((r) => r.archived)

  return (
    <div className="space-y-5">
      <Header
        title="Ruang Kelas"
        subtitle="Kelas praktikum Anda. Gabung dengan kode dari dosen, atau buat kelas sendiri bila Anda dosen."
      />

      <div className={cn('grid gap-4', canCreate && 'lg:grid-cols-2')}>
        <form
          className="card space-y-3 p-5"
          onSubmit={(e) => {
            e.preventDefault()
            setJoinErr(null)
            joinM.mutate()
          }}
        >
          <h2 className="text-sm font-bold text-slate-800">Gabung kelas</h2>
          <p className="text-xs text-slate-500">Masukkan kode kelas 8 karakter dari dosen Anda.</p>
          <div className="flex gap-2">
            <input
              className="input flex-1 font-mono uppercase tracking-widest"
              placeholder="ABCD-EFGH"
              maxLength={16}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <button
              type="submit"
              className="btn-primary"
              disabled={code.replace(/[^a-z0-9]/gi, '').length < 4 || joinM.isPending}
            >
              {joinM.isPending ? 'Memproses…' : 'Gabung'}
            </button>
          </div>
          {joinErr && <Notice kind="err">{joinErr}</Notice>}
        </form>

        {canCreate && (
          <form
            className="card space-y-3 p-5"
            onSubmit={(e) => {
              e.preventDefault()
              setCreateErr(null)
              createM.mutate()
            }}
          >
            <h2 className="text-sm font-bold text-slate-800">Buat kelas baru</h2>
            <input
              className="input w-full"
              placeholder="Nama kelas, mis. Deep Learning — TI 5A"
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <textarea
              className="input min-h-[64px] w-full resize-y"
              placeholder="Deskripsi singkat (opsional)"
              maxLength={1000}
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
            />
            <div className="flex justify-end">
              <button
                type="submit"
                className="btn-primary inline-flex items-center gap-2"
                disabled={name.trim().length < 3 || createM.isPending}
              >
                <IconPlus className="h-4 w-4" />
                {createM.isPending ? 'Membuat…' : 'Buat kelas'}
              </button>
            </div>
            {createErr && <Notice kind="err">{createErr}</Notice>}
          </form>
        )}
      </div>

      <div className="card p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-bold text-slate-800">
            {scope === 'all' ? 'Semua kelas' : 'Kelas saya'}
          </h2>
          {isAdmin && (
            <div className="flex gap-1 rounded-lg bg-slate-100 p-1 text-xs">
              {(['mine', 'all'] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setScope(s)}
                  className={cn(
                    'rounded-md px-3 py-1 font-semibold',
                    scope === s ? 'bg-white text-slate-800 shadow' : 'text-slate-500',
                  )}
                >
                  {s === 'mine' ? 'Kelas saya' : 'Semua kelas'}
                </button>
              ))}
            </div>
          )}
        </div>
        {listQ.isLoading && <Spinner label="Memuat…" />}
        {listQ.data && rooms.length === 0 && (
          <p className="text-sm text-slate-400">
            Belum ada kelas.{' '}
            {canCreate ? 'Buat kelas di atas, lalu bagikan kodenya.' : 'Minta kode kelas ke dosen Anda.'}
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {aktif.map((c) => (
            <ClassCard key={c.id} c={c} />
          ))}
        </div>
        {arsip.length > 0 && (
          <>
            <h3 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Diarsipkan
            </h3>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {arsip.map((c) => (
                <ClassCard key={c.id} c={c} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function KelasDetail({ id }: { id: number }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')

  const q = useQuery({ queryKey: ['classroom', id], queryFn: () => api.getClassroom(id) })
  const c = q.data

  useEffect(() => {
    if (c && !editing) {
      setName(c.name)
      setDesc(c.description)
    }
  }, [c, editing])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['classroom', id] })
    qc.invalidateQueries({ queryKey: ['classrooms'] })
  }
  const onErr = (e: unknown) => setMsg({ kind: 'err', text: errMsg(e, 'Aksi gagal.') })

  const updateM = useMutation({
    mutationFn: (patch: Parameters<typeof api.updateClassroom>[1]) => api.updateClassroom(id, patch),
    onSuccess: () => {
      setEditing(false)
      refresh()
    },
    onError: onErr,
  })
  const codeM = useMutation({
    mutationFn: () => api.regenerateClassCode(id),
    onSuccess: () => {
      setMsg({ kind: 'ok', text: 'Kode baru dibuat. Kode lama tidak berlaku lagi.' })
      refresh()
    },
    onError: onErr,
  })
  const deleteM = useMutation({
    mutationFn: () => api.deleteClassroom(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['classrooms'] })
      navigate('/kelas')
    },
    onError: onErr,
  })
  const leaveM = useMutation({
    mutationFn: () => api.leaveClassroom(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['classrooms'] })
      navigate('/kelas')
    },
    onError: onErr,
  })
  const roleM = useMutation({
    mutationFn: ({ uid, role }: { uid: number; role: ClassMemberRole }) =>
      api.setClassMemberRole(id, uid, role),
    onSuccess: refresh,
    onError: onErr,
  })
  const removeM = useMutation({
    mutationFn: (uid: number) => api.removeClassMember(id, uid),
    onSuccess: refresh,
    onError: onErr,
  })

  if (q.isLoading) return <Spinner label="Memuat kelas…" />
  if (q.isError || !c)
    return (
      <div className="space-y-3">
        <Link to="/kelas" className="inline-flex items-center gap-1 text-sm text-brand-600">
          <IconArrowLeft className="h-4 w-4" /> Kembali
        </Link>
        <Notice kind="err">{errMsg(q.error, 'Kelas tidak ditemukan.')}</Notice>
      </div>
    )

  const teachers = c.members.filter((m) => m.role === 'pengajar')
  const students = c.members.filter((m) => m.role === 'mahasiswa')

  return (
    <div className="space-y-5">
      <Link to="/kelas" className="inline-flex items-center gap-1 text-sm text-brand-600">
        <IconArrowLeft className="h-4 w-4" /> Semua kelas
      </Link>

      <div className="card space-y-3 p-5">
        {editing ? (
          <div className="space-y-2">
            <input
              className="input w-full"
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <textarea
              className="input min-h-[64px] w-full resize-y"
              maxLength={1000}
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>
                Batal
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={name.trim().length < 3 || updateM.isPending}
                onClick={() => updateM.mutate({ name: name.trim(), description: desc.trim() })}
              >
                Simpan
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Pill cls={(MY_ROLE[c.my_role] ?? MY_ROLE.mahasiswa).cls}>
                  {(MY_ROLE[c.my_role] ?? MY_ROLE.mahasiswa).label}
                </Pill>
                {c.archived && (
                  <Pill cls="bg-slate-100 text-slate-600 ring-slate-500/20">Diarsipkan</Pill>
                )}
              </div>
              <h1 className="text-lg font-bold text-slate-800">{c.name}</h1>
              {c.description && (
                <p className="whitespace-pre-wrap text-sm text-slate-600">{c.description}</p>
              )}
              <p className="mt-1 text-xs text-slate-500">
                Pengajar: {c.teachers.join(', ')} · {c.student_count} peserta
              </p>
            </div>
            {c.can_manage ? (
              <button type="button" className="btn-ghost" onClick={() => setEditing(true)}>
                Ubah
              </button>
            ) : (
              <button
                type="button"
                className="btn-ghost text-rose-600"
                disabled={leaveM.isPending}
                onClick={() => {
                  if (window.confirm(`Keluar dari kelas ${c.name}?`)) leaveM.mutate()
                }}
              >
                Keluar kelas
              </button>
            )}
          </div>
        )}
        {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      </div>

      {c.can_manage && c.code && (
        <div className="card flex flex-wrap items-center gap-4 p-5">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Kode kelas</p>
            <p className="font-mono text-3xl font-bold tracking-[0.2em] text-slate-800">
              {formatCode(c.code)}
            </p>
            <p className="text-xs text-slate-500">
              {c.archived
                ? 'Kelas diarsipkan: tidak menerima anggota baru.'
                : c.join_enabled
                  ? 'Bagikan kode ini ke mahasiswa; mereka masuk lewat menu Ruang Kelas → Gabung.'
                  : 'Pendaftaran dengan kode sedang ditutup.'}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-ghost inline-flex items-center gap-1.5"
              onClick={() => {
                void navigator.clipboard?.writeText(formatCode(c.code ?? ''))
                setMsg({ kind: 'ok', text: 'Kode disalin.' })
              }}
            >
              <IconCopy className="h-4 w-4" /> Salin
            </button>
            <button
              type="button"
              className="btn-ghost inline-flex items-center gap-1.5"
              disabled={codeM.isPending}
              onClick={() => {
                if (window.confirm('Buat kode baru? Kode lama langsung tidak berlaku.')) codeM.mutate()
              }}
            >
              <IconRefresh className="h-4 w-4" /> Kode baru
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={updateM.isPending || c.archived}
              onClick={() => updateM.mutate({ join_enabled: !c.join_enabled })}
            >
              {c.join_enabled ? 'Tutup pendaftaran' : 'Buka pendaftaran'}
            </button>
          </div>
        </div>
      )}

      {c.can_manage && <AddMembers classId={id} onDone={refresh} />}

      <div className="card p-5">
        <h2 className="mb-3 text-sm font-bold text-slate-800">
          Pengajar <span className="font-normal text-slate-400">({teachers.length})</span>
        </h2>
        <MemberTable
          rows={teachers}
          manage={c.can_manage}
          onRole={(uid, role) => roleM.mutate({ uid, role })}
          onRemove={(uid, nama) => {
            if (window.confirm(`Keluarkan ${nama} dari kelas?`)) removeM.mutate(uid)
          }}
        />
      </div>

      {c.can_manage && (
        <div className="card p-5">
          <h2 className="mb-3 text-sm font-bold text-slate-800">
            Peserta <span className="font-normal text-slate-400">({students.length})</span>
          </h2>
          {students.length === 0 ? (
            <p className="text-sm text-slate-400">
              Belum ada peserta. Bagikan kode kelas atau tambahkan peserta di atas.
            </p>
          ) : (
            <MemberTable
              rows={students}
              manage
              onRole={(uid, role) => roleM.mutate({ uid, role })}
              onRemove={(uid, nama) => {
                if (window.confirm(`Keluarkan ${nama} dari kelas?`)) removeM.mutate(uid)
              }}
            />
          )}
        </div>
      )}

      {c.can_manage && (
        <div className="card flex flex-wrap items-center justify-between gap-3 p-5">
          <div className="text-sm text-slate-600">
            <b>Arsipkan</b> kelas yang sudah selesai agar tidak menerima anggota baru, atau{' '}
            <b>hapus</b> permanen (anggota dikeluarkan; berkas mahasiswa tidak tersentuh).
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-ghost"
              disabled={updateM.isPending}
              onClick={() => updateM.mutate({ archived: !c.archived })}
            >
              {c.archived ? 'Aktifkan lagi' : 'Arsipkan'}
            </button>
            <button
              type="button"
              className="btn-ghost inline-flex items-center gap-1.5 text-rose-600"
              disabled={deleteM.isPending}
              onClick={() => {
                if (window.confirm(`Hapus kelas ${c.name} secara permanen?`)) deleteM.mutate()
              }}
            >
              <IconTrash className="h-4 w-4" /> Hapus kelas
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function MemberTable({
  rows,
  manage,
  onRole,
  onRemove,
}: {
  rows: { user_id: number; name: string; username: string | null; email: string | null; account_role: keyof typeof ROLE_META; role: ClassMemberRole; joined_at: string }[]
  manage: boolean
  onRole: (uid: number, role: ClassMemberRole) => void
  onRemove: (uid: number, nama: string) => void
}) {
  return (
    <ul className="divide-y divide-slate-100">
      {rows.map((m) => {
        const meta = ROLE_META[m.account_role]
        return (
          <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-800">{m.name}</p>
              {manage && (
                <p className="truncate text-xs text-slate-500">
                  {[m.username, m.email].filter(Boolean).join(' · ')}
                  {' · '}bergabung {formatDateTime(m.joined_at)}
                </p>
              )}
            </div>
            {meta && <Pill cls={meta.badge}>{meta.label}</Pill>}
            {manage && (
              <>
                <select
                  className="input w-auto py-1 text-xs"
                  value={m.role}
                  onChange={(e) => onRole(m.user_id, e.target.value as ClassMemberRole)}
                >
                  <option value="mahasiswa">Peserta</option>
                  <option value="pengajar">Pengajar</option>
                </select>
                <button
                  type="button"
                  title="Keluarkan dari kelas"
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                  onClick={() => onRemove(m.user_id, m.name)}
                >
                  <IconTrash className="h-4 w-4" />
                </button>
              </>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function AddMembers({ classId, onDone }: { classId: number; onDone: () => void }) {
  const [text, setText] = useState('')
  const [role, setRole] = useState<ClassMemberRole>('mahasiswa')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [result, setResult] = useState<ClassMembersAddResult | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  const candQ = useQuery({
    queryKey: ['class-candidates', classId, debounced],
    queryFn: () => api.searchClassCandidates(classId, debounced),
    enabled: debounced.length >= 2,
  })

  const addM = useMutation({
    mutationFn: (body: { identifiers?: string[]; user_ids?: number[] }) =>
      api.addClassMembers(classId, { ...body, role }),
    onSuccess: (r) => {
      setResult(r)
      setErr(null)
      if (r.added.length) {
        setText('')
        onDone()
        candQ.refetch()
      }
    },
    onError: (e) => setErr(errMsg(e, 'Gagal menambah anggota.')),
  })

  const identifiers = text
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean)

  return (
    <div className="card space-y-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-800">Tambah anggota manual</h2>
        <select
          className="input w-auto py-1 text-xs"
          value={role}
          onChange={(e) => setRole(e.target.value as ClassMemberRole)}
        >
          <option value="mahasiswa">sebagai Peserta</option>
          <option value="pengajar">sebagai Pengajar (dosen/asisten)</option>
        </select>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            Tempel daftar email, username, atau NIM (bagian depan email) — satu per baris.
          </p>
          <textarea
            className="input min-h-[96px] w-full resize-y font-mono text-xs"
            placeholder={'105841100120\nnama@unismuh.ac.id'}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button
            type="button"
            className="btn-primary inline-flex items-center gap-2"
            disabled={!identifiers.length || identifiers.length > 200 || addM.isPending}
            onClick={() => addM.mutate({ identifiers })}
          >
            <IconPlus className="h-4 w-4" />
            Tambahkan {identifiers.length ? `(${identifiers.length})` : ''}
          </button>
        </div>
        <div className="space-y-2">
          <p className="text-xs text-slate-500">Atau cari nama/email pengguna:</p>
          <input
            className="input w-full"
            placeholder="Ketik minimal 2 huruf…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {candQ.isFetching && <Spinner label="Mencari…" />}
          <ul className="max-h-52 divide-y divide-slate-100 overflow-auto">
            {(candQ.data ?? []).map((u) => (
              <li key={u.id} className="flex items-center gap-2 py-1.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-slate-800">{u.name}</p>
                  <p className="truncate text-xs text-slate-500">{u.email}</p>
                </div>
                <button
                  type="button"
                  className="btn-ghost py-1 text-xs"
                  disabled={addM.isPending}
                  onClick={() => addM.mutate({ user_ids: [u.id] })}
                >
                  Tambah
                </button>
              </li>
            ))}
            {candQ.data && candQ.data.length === 0 && (
              <li className="py-1.5 text-xs text-slate-400">Tidak ada pengguna yang cocok.</li>
            )}
          </ul>
        </div>
      </div>
      {err && <Notice kind="err">{err}</Notice>}
      {result && (
        <Notice kind={result.not_found.length || result.ambiguous.length ? 'err' : 'ok'}>
          {result.added.length} ditambahkan
          {result.already.length > 0 && `, ${result.already.length} sudah anggota`}
          {result.not_found.length > 0 && `. Tidak ditemukan: ${result.not_found.join(', ')}`}
          {result.ambiguous.length > 0 &&
            `. Cocok lebih dari satu akun (pakai email lengkap): ${result.ambiguous.join(', ')}`}
        </Notice>
      )}
    </div>
  )
}
