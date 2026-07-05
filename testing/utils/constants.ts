import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export const BASE_URL = process.env.BASE_URL ?? 'http://127.0.0.1:8088'
export const API_PREFIX = `${BASE_URL}/api/v1`

export const AUTH_DIR = path.resolve(__dirname, '..', '.auth')
export const ADMIN_STATE = path.join(AUTH_DIR, 'admin.json')
export const SUPERADMIN_STATE = path.join(AUTH_DIR, 'superadmin.json')
export const STUDENT_STATE = path.join(AUTH_DIR, 'student.json')
export const INFO_FILE = path.join(AUTH_DIR, 'info.json')

export const SCREENSHOT_DIR = path.resolve(__dirname, '..', 'screenshots')

/** Semua rute aplikasi (dari App.tsx). */
export const ROUTES = {
  public: ['/welcome', '/login'],
  protected: [
    '/',
    '/monitor',
    '/jobs',
    '/storage',
    '/submit/code',
    '/submit/notebook',
    '/submit/zip',
    '/submit/github',
    '/users',
    '/report',
    '/alerts',
    '/admin',
    '/profile',
  ],
  notFound: '/halaman-yang-tidak-ada-xyz',
} as const

/** Item navigasi sidebar (label terlihat). */
export const NAV = {
  main: ['Dashboard', 'Daftar Job', 'Penyimpanan'],
  mainAdminOnly: ['Monitor'],
  submit: ['Tempel Kode', 'Notebook', 'Upload ZIP', 'GitHub Repo'],
  admin: ['Laporan', 'Peringatan', 'Pengguna', 'Pengaturan'],
} as const

export interface AuthInfo {
  origin: string
  expires_min: number
  admin: { id: number; email: string; username: string | null; role: string }
  student: { id: number; email: string; username: string | null; role: string }
}
