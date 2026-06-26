import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import Avatar from '../components/Avatar'
import ChangePasswordModal from '../components/ChangePasswordModal'
import {
  IconCamera,
  IconClock,
  IconKey,
  IconLogout,
  IconMail,
  IconShield,
  IconTrash,
  IconUser,
} from '../components/icons'
import { fileToAvatarDataUrl, getAvatar, setAvatar } from '../lib/avatar'
import { useAuth } from '../lib/auth'
import { cn, parseDate } from '../lib/format'
import { ROLE_META } from '../lib/roles'

function formatJoinDate(iso: string): string {
  const d = parseDate(iso)
  if (!d) return '-'
  return d.toLocaleDateString('id-ID', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function InfoRow({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">
          {label}
        </dt>
        <dd className="truncate text-sm font-semibold text-slate-700">{value}</dd>
        {hint && <p className="mt-0.5 text-xs leading-snug text-slate-400">{hint}</p>}
      </div>
    </div>
  )
}

export default function Profile() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const [pwOpen, setPwOpen] = useState(false)
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [hasPhoto, setHasPhoto] = useState(() => (user ? !!getAvatar(user.id) : false))

  if (!user) return null
  const meta = ROLE_META[user.role]

  const onPickFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // reset agar file yang sama bisa dipilih lagi
    if (!file) return
    setPhotoError(null)
    if (file.size > 8 * 1024 * 1024) {
      setPhotoError('Ukuran gambar maksimal 8 MB.')
      return
    }
    try {
      const dataUrl = await fileToAvatarDataUrl(file)
      setAvatar(user.id, dataUrl)
      setHasPhoto(true)
    } catch (err) {
      setPhotoError(err instanceof Error ? err.message : 'Gagal memproses gambar.')
    }
  }

  const removePhoto = () => {
    setAvatar(user.id, null)
    setHasPhoto(false)
    setPhotoError(null)
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="gradient-text text-2xl font-bold">Profil Saya</h1>
        <p className="text-sm text-slate-500">
          Informasi akun & pengaturan keamanan ComputeHub kamu.
        </p>
      </div>

      {/* Identitas + foto */}
      <div className="card-pad">
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-start">
          <div className="relative shrink-0">
            <Avatar
              uid={user.id}
              name={user.name}
              gradient={meta.avatar}
              className="h-24 w-24 rounded-3xl text-3xl shadow-lg ring-4 ring-white"
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              title="Ganti foto profil"
              className="absolute -bottom-1 -right-1 grid h-9 w-9 place-items-center rounded-full bg-brand-500 text-white shadow-md ring-2 ring-white transition hover:bg-brand-600"
            >
              <IconCamera className="h-4 w-4" />
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={onPickFile}
            />
          </div>

          <div className="min-w-0 flex-1 text-center sm:text-left">
            <h2 className="truncate text-xl font-bold text-slate-800">{user.name}</h2>
            <p className="mt-0.5 flex items-center justify-center gap-1.5 text-sm text-slate-500 sm:justify-start">
              <IconMail className="h-4 w-4 shrink-0" />
              <span className="truncate">{user.email}</span>
            </p>

            <div className="mt-3 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              <span className={cn('badge', meta.badge)}>
                <meta.Icon className="h-3.5 w-3.5" />
                {meta.label}
              </span>
              {user.is_active ? (
                <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Akun aktif
                </span>
              ) : (
                <span className="badge bg-slate-100 text-slate-500 ring-slate-400/20">
                  Nonaktif
                </span>
              )}
              {user.is_superadmin && (
                <span className="badge bg-amber-50 text-amber-700 ring-amber-600/20">
                  <IconShield className="h-3.5 w-3.5" />
                  Super Admin
                </span>
              )}
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              <button
                onClick={() => fileRef.current?.click()}
                className="btn-ghost px-3 py-1.5 text-xs"
              >
                <IconCamera className="h-4 w-4" />
                {hasPhoto ? 'Ganti foto' : 'Unggah foto'}
              </button>
              {hasPhoto && (
                <button
                  onClick={removePhoto}
                  className="btn-ghost px-3 py-1.5 text-xs text-rose-600"
                >
                  <IconTrash className="h-4 w-4" />
                  Hapus foto
                </button>
              )}
            </div>
            {photoError && <p className="mt-2 text-xs text-rose-600">{photoError}</p>}
            <p className="mt-1.5 text-[11px] text-slate-400">
              Foto disimpan di browser ini saja (tidak diunggah ke server).
            </p>
          </div>
        </div>
      </div>

      {/* Detail akun */}
      <div className="card-pad">
        <h3 className="mb-3 text-sm font-semibold text-slate-700">Detail Akun</h3>
        <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
          <InfoRow
            icon={<IconUser className="h-4 w-4" />}
            label="Nama lengkap"
            value={user.name}
          />
          <InfoRow
            icon={<IconMail className="h-4 w-4" />}
            label="Email"
            value={user.email}
          />
          <InfoRow
            icon={<IconShield className="h-4 w-4" />}
            label="Peran"
            value={meta.label}
            hint={meta.description}
          />
          <InfoRow
            icon={<IconClock className="h-4 w-4" />}
            label="Bergabung sejak"
            value={formatJoinDate(user.created_at)}
          />
        </dl>
      </div>

      {/* Keamanan & sesi */}
      <div className="card-pad">
        <h3 className="mb-1 text-sm font-semibold text-slate-700">Keamanan & Sesi</h3>
        <p className="mb-4 text-xs text-slate-500">
          Jaga keamanan akun: ubah password secara berkala & keluar bila memakai
          perangkat bersama.
        </p>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setPwOpen(true)} className="btn-ghost">
            <IconKey className="h-4 w-4 text-amber-500" />
            Ubah Password
          </button>
          <button onClick={handleLogout} className="btn-danger">
            <IconLogout className="h-4 w-4" />
            Keluar
          </button>
        </div>
      </div>

      {pwOpen && <ChangePasswordModal onClose={() => setPwOpen(false)} />}
    </div>
  )
}
