import { useParams, useSearchParams } from 'react-router-dom'

import InteractiveNotebook, { type NotebookMode } from '../components/InteractiveNotebook'
import {
  IconCode,
  IconCpu,
  IconGithub,
  IconNotebook,
  IconUpload,
} from '../components/icons'
import { useAuth } from '../lib/auth'

type Meta = {
  mode: NotebookMode
  title: string
  desc: string
  Icon: (p: { className?: string }) => JSX.Element
  accent: string
}

const SOURCE_META: Record<string, Meta> = {
  code: {
    mode: 'paste',
    title: 'Tempel Kode Python',
    desc: 'Editor interaktif ala Colab — kode jalan di GPU, hasil langsung tampil, variabel tersimpan antar-sel.',
    Icon: IconCode,
    accent: 'from-blue-500 to-indigo-500',
  },
  notebook: {
    mode: 'notebook',
    title: 'Jalankan Notebook (.ipynb)',
    desc: 'Unggah .ipynb; sel kode & markdown dimuat ke editor interaktif — jalankan & ubah langsung di GPU.',
    Icon: IconNotebook,
    accent: 'from-orange-500 to-rose-500',
  },
  zip: {
    mode: 'zip',
    title: 'Upload Project (Folder)',
    desc: 'Unggah SATU folder project (ukuran nyata, tanpa zip); jelajahi file di explorer & jalankan kodenya secara interaktif di GPU.',
    Icon: IconUpload,
    accent: 'from-emerald-500 to-teal-500',
  },
  github: {
    mode: 'github',
    title: 'Clone GitHub Repo',
    desc: 'Clone repo publik GitHub; jelajahi file & jalankan interaktif di GPU (variabel persist antar-sel).',
    Icon: IconGithub,
    accent: 'from-violet-500 to-fuchsia-500',
  },
}

export default function Submit() {
  const { source } = useParams()
  const [search] = useSearchParams()
  // Dari galeri template: /submit/notebook?template=<id> -> sel template dimuat otomatis.
  const templateId = search.get('template') ?? undefined
  const { user } = useAuth()

  const meta = SOURCE_META[source ?? 'code'] ?? SOURCE_META.code
  const Icon = meta.Icon
  // Info hemat CPU hanya untuk mahasiswa & dosen; admin/super admin lihat batas asli di menu Admin.
  const showCpuTip = user?.role === 'mahasiswa' || user?.role === 'dosen'

  return (
    <div className="space-y-4">
      {/* Hero ramping (hemat ruang vertikal, fokus ke editor; lebar penuh ala IDE) */}
      <div className="flex items-center gap-3">
        <span
          className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br ${meta.accent} text-white shadow`}
        >
          <Icon className="h-6 w-6" />
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-bold leading-tight text-slate-800">
            {meta.title}
          </h1>
          <p className="truncate text-sm text-slate-500">{meta.desc}</p>
        </div>
      </div>

      {showCpuTip && (
        <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-600/15">
          <IconCpu className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <p>
            <b>Minimalkan penggunaan CPU.</b> Server ini dipakai bersama — gunakan
            CPU seperlunya dan manfaatkan GPU untuk komputasi berat agar tetap lancar
            untuk semua pengguna.
          </p>
        </div>
      )}

      <InteractiveNotebook key={templateId ?? meta.mode} mode={meta.mode} templateId={templateId} />
    </div>
  )
}
