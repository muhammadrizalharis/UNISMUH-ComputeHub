import { Link } from 'react-router-dom'
import { IconLock } from './icons'
import { JOB_TEMPLATES } from '../lib/jobTemplates'

const TITLES: Record<string, string> = {
  '/submit/code': 'Tempel Kode Python',
  '/submit/notebook': 'Jalankan Notebook (.ipynb)',
  '/submit/zip': 'Upload Project (Folder)',
  '/submit/github': 'Clone GitHub Repo',
  '/devbox': 'Devbox (VS Code)',
  '/templates': 'Galeri Template Notebook',
  '/jobs': 'Daftar Job',
  '/storage': 'Penyimpanan',
  '/bantuan': 'Bantuan',
  '/saran': 'Saran',
  '/monitor': 'Monitor',
}

export default function LockedFeaturePreview({ path }: { path: string }) {
  const title = TITLES[path] ?? 'Detail Job'
  const editor = path.startsWith('/submit/')
  return (
    <div className="space-y-5" data-testid="locked-preview">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl bg-amber-50 p-4 text-amber-900 ring-1 ring-amber-200">
        <div>
          <h2 className="flex items-center gap-2 font-semibold"><IconLock /> Fitur terkunci</h2>
          <p className="mt-1 text-sm">
            Ini pratinjau tampilan, bukan sesi atau data aktif. Anda belum dapat mengetik,
            mengunggah, menjalankan kode, atau memakai fitur ini sebelum disetujui admin.
          </p>
        </div>
        <Link to="/minta-akses" className="btn-primary shrink-0">Minta Akses</Link>
      </div>
      <h1 className="gradient-text text-xl font-bold">{title}</h1>
      <fieldset disabled className="min-w-0 space-y-4" aria-label={`${title} terkunci`}>
        {editor && (
          <>
            <div className="card-pad flex flex-wrap gap-3">
              <button className="btn-primary">Jalankan semua</button>
              <button className="btn-ghost">Simpan</button>
              <button className="btn-ghost">Tambah sel</button>
              <select className="input w-auto" aria-label="Versi Python"><option>Python</option></select>
              {path === '/submit/github' && <input className="input" aria-label="URL GitHub" placeholder="https://github.com/pemilik/repo" />}
              {(path === '/submit/zip' || path === '/submit/notebook') && (
                <label className="input">
                  {path.endsWith('zip') ? 'Pilih folder project' : 'Pilih notebook .ipynb'}
                  <input type="file" aria-label="Pilih berkas" className="mt-2 block w-full" />
                </label>
              )}
            </div>
            {[1, 2].map((n) => (
              <div key={n} className="card overflow-hidden">
                <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 text-sm text-slate-500">
                  <span>Sel kode {n}</span><span className="flex items-center gap-1"><IconLock className="h-4 w-4" /> Terkunci</span>
                </div>
                <textarea
                  className="block min-h-40 w-full resize-none bg-slate-950 p-4 font-mono text-sm text-slate-400"
                  aria-label={`Sel kode ${n} terkunci`}
                  value="# Editor dapat digunakan setelah akses disetujui admin."
                  readOnly
                />
              </div>
            ))}
          </>
        )}
        {path === '/devbox' && (
          <div className="card-pad space-y-4">
            <div className="flex gap-3"><button className="btn-primary">Buka Devbox</button><button className="btn-ghost">Hubungkan VS Code</button></div>
            <div className="grid min-h-72 grid-cols-4 overflow-hidden rounded-xl border border-slate-700 bg-slate-950 font-mono text-sm text-slate-400">
              <div className="border-r border-slate-700 p-4">EXPLORER<br /><br />Workspace terkunci</div>
              <div className="col-span-3 p-4">Editor VS Code <span className="block pt-10">Terminal dan editor belum tersedia.</span></div>
            </div>
          </div>
        )}
        {path === '/templates' && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {JOB_TEMPLATES.map((t) => (
              <div key={t.id} className="card-pad space-y-3">
                <h2 className="font-semibold">{t.label}</h2><p className="text-sm text-slate-500">{t.desc}</p>
                <button className="btn-ghost"><IconLock className="h-4 w-4" /> Gunakan template — terkunci</button>
              </div>
            ))}
          </div>
        )}
        {(path.startsWith('/jobs') || path === '/storage') && (
          <div className="card overflow-hidden">
            <div className="flex flex-wrap gap-3 p-4">
              <input className="input max-w-xs" aria-label="Pencarian terkunci" placeholder={path === '/storage' ? 'Cari berkas...' : 'Cari job...'} />
              <button className="btn-primary">{path === '/storage' ? 'Upload' : 'Buat Job'}</button>
              <button className="btn-ghost">{path === '/storage' ? 'Folder baru' : 'Filter status'}</button>
            </div>
            <table className="w-full text-left text-sm"><thead className="bg-slate-50"><tr>
              {(path === '/storage' ? ['Nama', 'Ukuran', 'Diubah', 'Aksi'] : ['ID', 'Nama Job', 'Status', 'Disubmit', 'Aksi']).map((h) => <th key={h} className="p-4">{h}</th>)}
            </tr></thead><tbody><tr><td colSpan={5} className="p-12 text-center text-slate-500">Terkunci — data tidak dimuat dalam pratinjau.</td></tr></tbody></table>
          </div>
        )}
        {path === '/saran' && (
          <div className="card-pad space-y-4">
            <select className="input" aria-label="Kategori saran"><option>Saran fitur</option></select>
            <textarea className="input min-h-40" aria-label="Pesan saran" placeholder="Tulis saran..." />
            <button className="btn-primary">Kirim saran — terkunci</button>
          </div>
        )}
        {path === '/bantuan' && (
          <div className="card-pad space-y-4">
            <input className="input" placeholder="Cari panduan..." aria-label="Cari bantuan" />
            {['Memulai komputasi', 'Notebook interaktif', 'Upload dan penyimpanan', 'Devbox dan GitHub'].map((t) => (
              <div key={t} className="flex items-center gap-2 rounded-lg border border-slate-200 p-4"><IconLock className="h-4 w-4" />{t} — terkunci</div>
            ))}
          </div>
        )}
        {path === '/monitor' && <div className="card-pad">Monitor lengkap terkunci. Pemantauan live tetap tersedia di Dashboard.</div>}
      </fieldset>
    </div>
  )
}
