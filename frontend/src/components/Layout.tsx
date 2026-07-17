import { Suspense, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../lib/auth'
import { cn } from '../lib/format'
import { ROLE_META } from '../lib/roles'
import {
  IconBell,
  IconChart,
  IconChevron,
  IconCode,
  IconDashboard,
  IconGithub,
  IconGpu,
  IconHelp,
  IconFolder,
  IconJobs,
  IconKey,
  IconLogout,
  IconNotebook,
  IconServer,
  IconSettings,
  IconUpload,
  IconUser,
  IconUsers,
} from './icons'
import Avatar from './Avatar'
import ChangePasswordModal from './ChangePasswordModal'
import Spinner from './Spinner'

type Leaf = {
  to: string
  label: string
  Icon: (p: { className?: string }) => JSX.Element
  end?: boolean
}

const MAIN: Leaf[] = [
  { to: '/', label: 'Dashboard', Icon: IconDashboard, end: true },
  { to: '/monitor', label: 'Monitor', Icon: IconChart },
  { to: '/jobs', label: 'Daftar Job', Icon: IconJobs },
  { to: '/storage', label: 'Penyimpanan', Icon: IconFolder },
  { to: '/bantuan', label: 'Bantuan', Icon: IconHelp },
]

const SUBMIT: Leaf[] = [
  { to: '/submit/code', label: 'Tempel Kode', Icon: IconCode },
  { to: '/submit/notebook', label: 'Notebook', Icon: IconNotebook },
  { to: '/submit/zip', label: 'Upload Folder', Icon: IconUpload },
  { to: '/submit/github', label: 'GitHub Repo', Icon: IconGithub },
]

const ADMIN: Leaf[] = [
  { to: '/report', label: 'Laporan', Icon: IconServer },
  { to: '/alerts', label: 'Peringatan', Icon: IconBell },
  { to: '/users', label: 'Pengguna', Icon: IconUsers },
  { to: '/admin', label: 'Pengaturan', Icon: IconSettings },
]

function SideLink({
  to,
  label,
  Icon,
  end,
  sub,
  collapsed,
}: Leaf & { sub?: boolean; collapsed?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          'nav-link',
          collapsed && 'justify-center px-0',
          sub && !collapsed && 'py-1.5 text-[13px]',
          isActive && 'nav-link-active',
        )
      }
    >
      <Icon className={sub && !collapsed ? 'h-4 w-4' : 'h-5 w-5'} />
      {!collapsed && label}
    </NavLink>
  )
}

function SectionLabel({
  children,
  collapsed,
}: {
  children: React.ReactNode
  collapsed?: boolean
}) {
  if (collapsed) return <div className="mx-2 my-2 border-t border-white/10" />
  return (
    <p className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
      {children}
    </p>
  )
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [submitOpen, setSubmitOpen] = useState(true)
  const [pwOpen, setPwOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('computehub_sidebar_collapsed') === '1',
  )
  const toggleCollapsed = () =>
    setCollapsed((v) => {
      const next = !v
      localStorage.setItem('computehub_sidebar_collapsed', next ? '1' : '0')
      if (next) setMenuOpen(false)
      return next
    })
  const isAdmin = user?.role === 'admin'
  const role = user?.role
  const meta = user ? ROLE_META[user.role] : null
  // Monitor sistem (berat) hanya untuk admin — mahasiswa & dosen tidak perlu.
  const mainItems =
    role === 'admin' ? MAIN : MAIN.filter((m) => m.to !== '/monitor')
  const submitActive = location.pathname.startsWith('/submit')

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  // Daftar datar untuk nav mobile
  const mobileItems: Leaf[] = [
    ...mainItems,
    ...SUBMIT,
    ...(isAdmin ? ADMIN : []),
    { to: '/profile', label: 'Profil', Icon: IconUser },
  ]

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside
        className={cn(
          'sticky top-0 hidden h-screen shrink-0 flex-col bg-gradient-to-b from-slate-900 via-slate-900 to-[#0b1020] py-5 text-slate-300 shadow-2xl ring-1 ring-white/5 transition-[width] duration-200 md:flex',
          collapsed ? 'w-[4.75rem] px-2' : 'w-64 px-4',
        )}
      >
        <div className={collapsed ? 'px-0' : 'px-2'}>
          <div
            className={cn(
              'flex items-center',
              collapsed ? 'justify-center' : 'gap-3',
            )}
          >
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-indigo-500 text-white shadow-lg shadow-brand-600/40">
              <IconGpu />
            </span>
            {!collapsed && (
              <div className="leading-tight">
                <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                  UNISMUH
                </p>
                <p className="text-base font-bold leading-tight text-white">
                  ComputeHub
                </p>
              </div>
            )}
          </div>
          {!collapsed && (
            <p className="mt-2 text-xs text-brand-300">Informatics HPC Platform</p>
          )}
        </div>

        {/* Tombol ciutkan / lebarkan sidebar (ikon panah saja) */}
        <button
          type="button"
          onClick={toggleCollapsed}
          title={collapsed ? 'Lebarkan sidebar' : 'Ciutkan sidebar'}
          aria-label={collapsed ? 'Lebarkan sidebar' : 'Ciutkan sidebar'}
          className={cn(
            'mt-3 grid h-8 w-8 place-items-center rounded-lg bg-white/5 text-slate-400 ring-1 ring-white/10 transition hover:bg-white/10 hover:text-white',
            collapsed ? 'mx-auto' : 'ml-auto',
          )}
        >
          <IconChevron
            className={cn(
              'h-4 w-4 transition-transform',
              collapsed ? '-rotate-90' : 'rotate-90',
            )}
          />
        </button>

        <nav className="mt-4 flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden pr-1">
          <SectionLabel collapsed={collapsed}>Menu</SectionLabel>
          {mainItems.map((l) => (
            <SideLink key={l.to} {...l} collapsed={collapsed} />
          ))}

          {/* Grup Submit (collapsible) */}
          <SectionLabel collapsed={collapsed}>Buat Job</SectionLabel>
          {collapsed ? (
            SUBMIT.map((l) => <SideLink key={l.to} {...l} collapsed />)
          ) : (
            <>
              <button
                type="button"
                onClick={() => setSubmitOpen((v) => !v)}
                className={cn('nav-link w-full', submitActive && 'text-white')}
              >
                <IconNotebook className="h-5 w-5" />
                Notebook Interaktif
                <IconChevron
                  className={cn(
                    'ml-auto h-4 w-4 transition-transform',
                    submitOpen ? 'rotate-0' : '-rotate-90',
                  )}
                />
              </button>
              {submitOpen && (
                <div className="ml-3 space-y-0.5 border-l border-white/10 pl-3">
                  {SUBMIT.map((l) => (
                    <SideLink key={l.to} {...l} sub />
                  ))}
                </div>
              )}
            </>
          )}

          {isAdmin && (
            <>
              <SectionLabel collapsed={collapsed}>Admin</SectionLabel>
              {ADMIN.map((l) => (
                <SideLink key={l.to} {...l} collapsed={collapsed} />
              ))}
            </>
          )}
        </nav>

        {user && meta && (
          <div className="relative mt-4">
            {/* Backdrop untuk menutup menu saat klik di luar */}
            {menuOpen && (
              <div
                className="fixed inset-0 z-30"
                onClick={() => setMenuOpen(false)}
                aria-hidden
              />
            )}

            {/* Menu akun — muncul ke atas karena kartu ada di paling bawah */}
            <div
              className={cn(
                'absolute bottom-full z-40 mb-2 overflow-hidden rounded-2xl border border-white/10 bg-slate-800/95 p-1.5 shadow-2xl ring-1 ring-black/40 backdrop-blur transition',
                collapsed ? 'left-0 w-56' : 'left-0 right-0',
                menuOpen
                  ? 'visible translate-y-0 opacity-100'
                  : 'invisible translate-y-1 opacity-0',
              )}
            >
              <p className="px-3 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                Akun
              </p>
              <button
                onClick={() => {
                  setMenuOpen(false)
                  navigate('/profile')
                }}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-slate-200 transition hover:bg-white/10"
              >
                <IconUser className="h-4 w-4 text-brand-300" />
                Profil saya
              </button>
              <button
                onClick={() => {
                  setMenuOpen(false)
                  setPwOpen(true)
                }}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-slate-200 transition hover:bg-white/10"
              >
                <IconKey className="h-4 w-4 text-amber-300" />
                Ubah Password
              </button>
              <div className="my-1 border-t border-white/10" />
              <button
                onClick={() => {
                  setMenuOpen(false)
                  handleLogout()
                }}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-rose-300 transition hover:bg-rose-500/15"
              >
                <IconLogout className="h-4 w-4" />
                Keluar
              </button>
            </div>

            {/* Kartu user — klik untuk membuka menu */}
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              title={collapsed ? user.name : undefined}
              className={cn(
                'flex w-full items-center rounded-2xl bg-white/5 text-left ring-1 ring-white/10 transition hover:bg-white/10',
                collapsed ? 'justify-center p-2' : 'gap-3 p-3',
                menuOpen && 'bg-white/10 ring-white/20',
              )}
            >
              <Avatar
                src={user.avatar}
                name={user.name}
                gradient={meta.avatar}
                className="h-9 w-9 shrink-0 rounded-full text-sm"
              />
              {!collapsed && (
                <>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {user.name}
                    </p>
                    <p className="truncate text-xs text-slate-400">
                      {user.email}
                    </p>
                  </div>
                  <IconChevron
                    className={cn(
                      'h-4 w-4 shrink-0 text-slate-400 transition-transform',
                      menuOpen ? 'rotate-0' : 'rotate-180',
                    )}
                  />
                </>
              )}
            </button>

            {!collapsed && (
              <span
                className={cn('badge mt-2 w-full justify-center', meta.badge)}
              >
                <meta.Icon className="h-3.5 w-3.5" />
                {meta.label}
              </span>
            )}
          </div>
        )}
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top nav */}
        <header className="flex items-center justify-between gap-3 bg-slate-900 px-4 py-3 text-white md:hidden">
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-indigo-500 text-white">
              <IconGpu className="h-4 w-4" />
            </span>
            <span className="text-sm font-bold">UNISMUH ComputeHub</span>
          </div>
          <div className="flex items-center gap-2">
            {meta && (
              <span className={cn('badge', meta.badge)}>
                <meta.Icon className="h-3.5 w-3.5" />
                {meta.label}
              </span>
            )}
            <button
              onClick={handleLogout}
              className="rounded-lg p-1.5 text-slate-300 hover:bg-rose-500/20 hover:text-rose-300"
            >
              <IconLogout className="h-5 w-5" />
            </button>
          </div>
        </header>
        <nav className="flex gap-1 overflow-x-auto bg-slate-900/95 px-2 py-2 md:hidden">
          {mobileItems.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn('nav-link whitespace-nowrap', isActive && 'nav-link-active')
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <main className="relative flex-1 p-4 sm:p-6 lg:p-8">
          {/* Blob bergerak di belakang konten */}
          <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
            <div className="blob absolute -left-10 top-8 h-64 w-64 rounded-full bg-brand-400/15" />
            <div
              className="blob absolute right-0 top-1/3 h-72 w-72 rounded-full bg-violet-400/15"
              style={{ animationDelay: '2.5s' }}
            />
            <div
              className="blob absolute bottom-0 left-1/2 h-60 w-60 rounded-full bg-cyan-400/10"
              style={{ animationDelay: '5s' }}
            />
          </div>
          <div key={location.pathname} className="animate-fade-in">
            <Suspense
              fallback={<Spinner label="Memuat halaman…" className="p-10" />}
            >
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>

      {pwOpen && <ChangePasswordModal onClose={() => setPwOpen(false)} />}
    </div>
  )
}
