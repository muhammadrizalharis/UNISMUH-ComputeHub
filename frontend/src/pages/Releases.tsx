import { Link } from 'react-router-dom'

import ThemeToggle from '../components/ThemeToggle'
import { APP_VERSION, RELEASES } from '../lib/version'

// Halaman publik riwayat versi (route /rilis), ditautkan dari lencana versi di footer.
export default function Releases() {
  return (
    <div className="min-h-screen bg-white dark:bg-slate-950">
      <header className="border-b border-slate-200 dark:border-slate-800">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <Link to="/welcome" className="flex items-center gap-2.5">
            <img src="/logos/teknik-merah.png" alt="" className="h-9 w-9 object-contain" />
            <div>
              <p className="font-bold text-slate-800 dark:text-slate-100">UNISMUH ComputeHub</p>
              <p className="text-[11px] uppercase tracking-wide text-slate-400">
                Sistem Komputasi Terpadu
              </p>
            </div>
          </Link>
          <div className="flex items-center gap-2.5">
            <ThemeToggle />
            <Link to="/welcome" className="btn-ghost text-sm">
              ← Beranda
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        <div className="mb-8">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 sm:text-3xl">
              Riwayat Versi
            </h1>
            <span className="rounded-full bg-brand-600 px-3 py-1 text-xs font-bold text-white">
              Versi sekarang v{APP_VERSION}
            </span>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
            Daftar {RELEASES.length} versi UNISMUH ComputeHub sejak rilis pertama, beserta
            perubahan utamanya. Nomor versi memakai pola{' '}
            <span className="font-semibold">besar.menengah.perbaikan</span>: angka menengah naik
            setiap ada gelombang fitur baru, angka terakhir untuk perbaikan kecil.
          </p>
        </div>

        <ol className="relative space-y-8 border-l border-slate-200 pl-6 dark:border-slate-800">
          {RELEASES.map((r, i) => (
            <li key={r.version} className="relative">
              <span
                className={
                  i === 0
                    ? 'absolute -left-[31px] top-1.5 h-3 w-3 rounded-full bg-brand-600 ring-4 ring-brand-100 dark:ring-brand-600/25'
                    : 'absolute -left-[31px] top-1.5 h-3 w-3 rounded-full bg-slate-300 ring-4 ring-white dark:bg-slate-600 dark:ring-slate-950'
                }
              />
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-sm font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  v{r.version}
                </span>
                <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">
                  {r.title}
                </h2>
                {i === 0 && (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                    Terbaru
                  </span>
                )}
                <span className="text-xs text-slate-400">{r.date}</span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                {r.summary}
              </p>
              <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                {r.highlights.map((h, j) => (
                  <li key={j}>{h}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>

        <p className="mt-10 border-t border-slate-200 pt-5 text-xs text-slate-400 dark:border-slate-800">
          © {new Date().getFullYear()} UNISMUH ComputeHub · Fakultas Teknik · Universitas
          Muhammadiyah Makassar
        </p>
      </main>
    </div>
  )
}
