import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-slate-950 px-6 text-center">
      {/* Latar aurora lembut */}
      <div className="blob pointer-events-none absolute -left-24 top-16 h-80 w-80 rounded-full bg-brand-500/20" />
      <div
        className="blob pointer-events-none absolute -right-16 bottom-24 h-72 w-72 rounded-full bg-violet-500/20"
        style={{ animationDelay: '2.5s' }}
      />
      <div
        className="blob pointer-events-none absolute left-1/3 top-1/2 h-56 w-56 rounded-full bg-cyan-400/10"
        style={{ animationDelay: '4s' }}
      />

      <div className="relative z-10 animate-fade-in">
        <img
          src="/logos/logo-unismuh-computehub-256.png"
          alt="UNISMUH ComputeHub"
          className="mx-auto mb-6 h-16 w-16 rounded-2xl shadow-lg shadow-brand-600/30"
        />
        <p className="gradient-text text-8xl font-black leading-none">404</p>
        <h1 className="mt-4 text-xl font-bold text-white">
          Halaman tidak ditemukan
        </h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-slate-400">
          Alamat yang kamu buka tidak ada, sudah dipindahkan, atau kamu tidak
          punya akses ke sana.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <Link to="/" className="btn-primary">
            ← Kembali ke Dashboard
          </Link>
          <Link
            to="/bantuan"
            className="rounded-xl bg-white/10 px-4 py-2 text-sm font-semibold text-white ring-1 ring-white/20 transition hover:bg-white/20"
          >
            Buka Bantuan
          </Link>
        </div>
      </div>
    </div>
  )
}
