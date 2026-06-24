import { useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'

import SubmitJobForm from '../components/SubmitJobForm'
import {
  IconCode,
  IconGithub,
  IconNotebook,
  IconUpload,
} from '../components/icons'
import type { JobSource } from '../lib/types'

type Meta = {
  source: JobSource
  title: string
  desc: string
  Icon: (p: { className?: string }) => JSX.Element
  accent: string
}

const SOURCE_META: Record<string, Meta> = {
  code: {
    source: 'paste',
    title: 'Tempel Kode Python',
    desc: 'Tulis / tempel skrip Python — langsung dijalankan di GPU.',
    Icon: IconCode,
    accent: 'from-blue-500 to-indigo-500',
  },
  notebook: {
    source: 'notebook',
    title: 'Jalankan Notebook (.ipynb)',
    desc: 'Unggah notebook; semua sel dieksekusi otomatis & hasilnya bisa diunduh.',
    Icon: IconNotebook,
    accent: 'from-orange-500 to-rose-500',
  },
  zip: {
    source: 'upload',
    title: 'Upload Project (.zip)',
    desc: 'Zip seluruh folder project; entrypoint dideteksi otomatis.',
    Icon: IconUpload,
    accent: 'from-emerald-500 to-teal-500',
  },
  github: {
    source: 'git',
    title: 'Clone GitHub Repo',
    desc: 'Tempel URL repo publik GitHub; otomatis di-clone & dijalankan.',
    Icon: IconGithub,
    accent: 'from-violet-500 to-fuchsia-500',
  },
}

export default function Submit() {
  const { source } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const meta = SOURCE_META[source ?? 'code'] ?? SOURCE_META.code
  const Icon = meta.Icon

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Hero */}
      <div className="card-pad flex items-center gap-4">
        <span
          className={`grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br ${meta.accent} text-white shadow-lg`}
        >
          <Icon className="h-7 w-7" />
        </span>
        <div>
          <h1 className="text-xl font-bold text-slate-800">{meta.title}</h1>
          <p className="text-sm text-slate-500">{meta.desc}</p>
        </div>
      </div>

      <SubmitJobForm
        key={meta.source}
        initialSource={meta.source}
        onDone={() => {
          void qc.invalidateQueries({ queryKey: ['jobs'] })
          navigate('/jobs')
        }}
        onCancel={() => navigate('/jobs')}
      />
    </div>
  )
}
