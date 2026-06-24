// Metadata tampilan per-peran (warna, ikon, label) agar admin/dosen/mahasiswa
// punya identitas visual yang jelas & konsisten di seluruh aplikasi.
import { IconChalkboard, IconGraduationCap, IconShield } from '../components/icons'
import type { UserRole } from './types'

export interface RoleMeta {
  label: string // label Indonesia
  Icon: (p: { className?: string }) => JSX.Element
  badge: string // kelas badge (bg/teks/ring)
  avatar: string // gradien avatar
  sidebarText: string // aksen teks di sidebar gelap
  title: string // judul dashboard
  description: string // deskripsi peran
}

export const ROLE_META: Record<UserRole, RoleMeta> = {
  admin: {
    label: 'Administrator',
    Icon: IconShield,
    badge: 'bg-brand-50 text-brand-700 ring-brand-600/20',
    avatar: 'from-brand-500 to-indigo-500',
    sidebarText: 'text-brand-300',
    title: 'ComputeHub Control Center',
    description:
      'Kontrol penuh platform: kelola pengguna, pengaturan, laporan & pantau seluruh server.',
  },
  dosen: {
    label: 'Dosen',
    Icon: IconChalkboard,
    badge: 'bg-violet-50 text-violet-700 ring-violet-600/20',
    avatar: 'from-violet-500 to-fuchsia-500',
    sidebarText: 'text-violet-300',
    title: 'Ruang Kerja Dosen',
    description:
      'Jalankan job dengan prioritas lebih tinggi, opsi lanjutan, dan pantau pemakaian GPU.',
  },
  mahasiswa: {
    label: 'Mahasiswa',
    Icon: IconGraduationCap,
    badge: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
    avatar: 'from-emerald-500 to-teal-500',
    sidebarText: 'text-emerald-300',
    title: 'Ruang Belajar Mahasiswa',
    description:
      'Submit kode / notebook ke GPU dengan kuota harian. Sederhana, cepat, dan terpandu.',
  },
}
