import { IconMail } from './icons'

/**
 * Footer situs (dipakai di halaman Landing). Foto pengembang berupa PNG
 * transparan (cutout) tanpa bingkai/latar. Atribusi "Built by" di bar bawah.
 */
export default function SiteFooter() {
  return (
    <footer className="relative overflow-hidden bg-white lg:min-h-[20rem]">
      {/* Foto developer (cutout PNG) menempel di sudut kanan-bawah footer */}
      <img
        src="/developer.png"
        alt="muhammadrizalharis"
        className="pointer-events-none absolute bottom-0 right-10 hidden h-full w-auto select-none object-bottom lg:block"
      />
      <div className="relative mx-auto max-w-6xl px-6 py-10 lg:pr-52">
        <div className="grid items-start gap-8 sm:grid-cols-2 lg:grid-cols-3">
          {/* Brand */}
          <div>
            <div className="flex items-center gap-2">
              <img
                src="/logos/teknik-merah.png"
                alt=""
                className="h-9 w-9 object-contain"
              />
              <div>
                <p className="font-bold text-slate-800">UNISMUH ComputeHub</p>
                <p className="text-[11px] uppercase tracking-wide text-slate-400">
                  Sistem Komputasi Terpadu
                </p>
              </div>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-slate-500">
              Fakultas Teknik · Universitas Muhammadiyah Makassar
            </p>
          </div>

          {/* Hubungi Kami */}
          <div>
            <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-700">
              Hubungi Kami
            </h3>
            <ul className="space-y-2.5 text-sm text-slate-500">
              <li className="flex items-center gap-2">
                <IconMail className="h-4 w-4 shrink-0 text-brand-600" />
                ft@unismuh.ac.id
              </li>
              <li className="flex items-center gap-2">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-4 w-4 shrink-0 text-brand-600"
                >
                  <path
                    d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1.9.3 1.8.6 2.6a2 2 0 01-.5 2.1L8.1 9.6a16 16 0 006 6l1.2-1.2a2 2 0 012.1-.5c.8.3 1.7.5 2.6.6a2 2 0 011.7 2z"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                +62 411 865 545
              </li>
              <li className="flex items-start gap-2">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="mt-0.5 h-4 w-4 shrink-0 text-brand-600"
                >
                  <path d="M21 10c0 7-9 12-9 12s-9-5-9-12a9 9 0 0118 0z" />
                  <circle cx="12" cy="10" r="3" />
                </svg>
                Jl. Sultan Alauddin No.259, Makassar
              </li>
            </ul>
          </div>

          {/* Kebijakan + Ikuti Kami */}
          <div>
            <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-700">
              Kebijakan
            </h3>
            <ul className="space-y-2 text-sm text-slate-500">
              <li>Kebijakan Privasi</li>
              <li>Syarat &amp; Ketentuan</li>
              <li>Kebijakan Cookie</li>
            </ul>
            <h3 className="mb-2 mt-5 text-sm font-bold uppercase tracking-wide text-slate-700">
              Ikuti Kami
            </h3>
            <div className="flex gap-2">
              <span
                className="grid h-8 w-8 place-items-center rounded-lg bg-[#1877f2] text-white"
                title="Facebook"
              >
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                  <path d="M15 3h-3a4 4 0 00-4 4v3H5v4h3v7h4v-7h3l1-4h-4V7a1 1 0 011-1h3z" />
                </svg>
              </span>
              <span
                className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-[#f58529] via-[#dd2a7b] to-[#8134af] text-white"
                title="Instagram"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-4 w-4"
                >
                  <rect x="3" y="3" width="18" height="18" rx="5" />
                  <circle cx="12" cy="12" r="4" />
                  <circle cx="17.5" cy="6.5" r="1" fill="currentColor" />
                </svg>
              </span>
              <span
                className="grid h-8 w-8 place-items-center rounded-lg bg-[#ff0000] text-white"
                title="YouTube"
              >
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                  <path d="M22 12s0-3.2-.4-4.7a2.5 2.5 0 00-1.8-1.8C18.3 5 12 5 12 5s-6.3 0-7.8.5A2.5 2.5 0 002.4 7.3C2 8.8 2 12 2 12s0 3.2.4 4.7a2.5 2.5 0 001.8 1.8C5.7 19 12 19 12 19s6.3 0 7.8-.5a2.5 2.5 0 001.8-1.8C22 15.2 22 12 22 12zM10 15V9l5 3z" />
                </svg>
              </span>
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-col items-center justify-between gap-2 border-t border-slate-200 pt-5 text-xs text-slate-400 sm:flex-row">
          <p>
            © {new Date().getFullYear()}{' '}
            <span className="font-semibold text-slate-600">UNISMUH ComputeHub</span>{' '}
            · Semua hak dilindungi.
          </p>
          <p>
            Built by{' '}
            <span className="font-semibold text-slate-600">muhammadrizalharis</span>
          </p>
        </div>
      </div>
    </footer>
  )
}
