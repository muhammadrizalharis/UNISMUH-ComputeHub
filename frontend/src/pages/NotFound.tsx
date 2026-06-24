import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-100 text-center">
      <p className="text-6xl font-black text-brand-600">404</p>
      <p className="text-slate-600">Halaman tidak ditemukan.</p>
      <Link to="/" className="btn-primary mt-2">
        Kembali ke Dashboard
      </Link>
    </div>
  )
}
