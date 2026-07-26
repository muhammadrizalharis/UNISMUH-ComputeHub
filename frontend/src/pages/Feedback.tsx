// Menu SARAN — kanal masukan resmi dari semua peran ke pengelola platform.
// Pengguna: kirim saran/masalah + lihat status tindak lanjut miliknya.
// Admin & super admin: tinjau semua, ubah status (baru/ditinjau/selesai), hapus spam.
// Saran baru otomatis diberitahukan ke pengelola via Telegram + email semua admin.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime, timeAgo } from '../lib/format'
import type { FeedbackItem } from '../lib/types'
import { IconSend, IconTrash } from '../components/icons'
import Spinner from '../components/Spinner'

const CATEGORIES: Array<{ id: string; label: string; desc: string }> = [
  { id: 'saran', label: 'Saran fitur', desc: 'Ide agar platform lebih baik' },
  { id: 'masalah', label: 'Masalah', desc: 'Ada yang tidak berfungsi/membingungkan' },
  { id: 'lainnya', label: 'Lainnya', desc: 'Apa pun selain dua di atas' },
]

const STATUS_META: Record<string, { label: string; cls: string }> = {
  baru: { label: 'Baru', cls: 'bg-sky-50 text-sky-700 ring-sky-600/20' },
  ditinjau: { label: 'Ditinjau', cls: 'bg-amber-50 text-amber-700 ring-amber-600/20' },
  selesai: { label: 'Selesai', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' },
}

const CATEGORY_CLS: Record<string, string> = {
  saran: 'bg-violet-50 text-violet-700 ring-violet-600/20',
  masalah: 'bg-rose-50 text-rose-700 ring-rose-600/20',
  lainnya: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

function StatusPill({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.baru
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset',
        meta.cls,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {meta.label}
    </span>
  )
}

function CategoryChip({ category }: { category: string }) {
  const label = CATEGORIES.find((c) => c.id === category)?.label ?? category
  return (
    <span
      className={cn(
        'inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset',
        CATEGORY_CLS[category] ?? CATEGORY_CLS.lainnya,
      )}
    >
      {label}
    </span>
  )
}

export default function Feedback() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const qc = useQueryClient()

  const [category, setCategory] = useState('saran')
  const [message, setMessage] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const mineQ = useQuery({
    queryKey: ['feedback', 'mine'],
    queryFn: () => api.listMyFeedback(),
  })
  const allQ = useQuery({
    queryKey: ['feedback', 'all'],
    queryFn: () => api.listAllFeedback(),
    enabled: isAdmin,
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['feedback'] })
  }

  const sendMutation = useMutation({
    mutationFn: () => api.createFeedback(category, message.trim()),
    onSuccess: () => {
      setMessage('')
      setNotice('Terima kasih! Saran Anda sudah terkirim ke pengelola.')
      setError(null)
      refresh()
    },
    onError: (e) => {
      setNotice(null)
      setError(e instanceof ApiError ? e.message : 'Gagal mengirim saran.')
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      api.updateFeedbackStatus(id, status),
    onSuccess: refresh,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteFeedback(id),
    onSuccess: refresh,
  })

  const canSend = message.trim().length >= 5 && !sendMutation.isPending

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-indigo-600 text-white shadow">
          <IconSend className="h-6 w-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-bold leading-tight text-slate-800">Saran & Masukan</h1>
          <p className="text-sm text-slate-500">
            Ada ide, keluhan, atau sesuatu yang membingungkan? Sampaikan di sini —
            masukan Anda langsung diteruskan ke pengelola platform.
          </p>
        </div>
      </div>

      {/* --- Form kirim --- */}
      <div className="card space-y-4 p-5">
        <div className="flex flex-wrap gap-2">
          {CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setCategory(c.id)}
              className={cn(
                'rounded-xl px-3.5 py-2 text-left text-sm ring-1 ring-inset transition',
                category === c.id
                  ? 'bg-gradient-to-br from-brand-500 to-indigo-600 text-white shadow ring-transparent'
                  : 'bg-white text-slate-600 ring-slate-200 hover:bg-slate-50',
              )}
            >
              <span className="block font-semibold">{c.label}</span>
              <span
                className={cn(
                  'block text-[11px]',
                  category === c.id ? 'text-white/80' : 'text-slate-400',
                )}
              >
                {c.desc}
              </span>
            </button>
          ))}
        </div>

        <div>
          <textarea
            className="input min-h-[110px] w-full resize-y"
            placeholder="Tulis masukan Anda… (minimal 5 karakter)"
            maxLength={2000}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
          <div className="mt-1 text-right text-[11px] text-slate-400">
            {message.length}/2000
          </div>
        </div>

        {notice && (
          <div className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700 ring-1 ring-inset ring-emerald-600/15">
            {notice}
          </div>
        )}
        {error && (
          <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/15">
            {error}
          </div>
        )}

        <div className="flex justify-end">
          <button
            type="button"
            className="btn-primary inline-flex items-center gap-2"
            disabled={!canSend}
            onClick={() => sendMutation.mutate()}
          >
            <IconSend className="h-4 w-4" />
            {sendMutation.isPending ? 'Mengirim…' : 'Kirim saran'}
          </button>
        </div>
      </div>

      {/* --- Saran saya --- */}
      <div className="card p-5">
        <h2 className="mb-3 text-sm font-bold text-slate-800">Saran saya</h2>
        {mineQ.isLoading && <Spinner label="Memuat…" />}
        {mineQ.data && mineQ.data.length === 0 && (
          <p className="text-sm text-slate-400">
            Belum ada — saran pertama Anda akan muncul di sini beserta status tindak lanjutnya.
          </p>
        )}
        <ul className="divide-y divide-slate-100">
          {(mineQ.data ?? []).map((f) => (
            <li key={f.id} className="flex flex-wrap items-start gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <CategoryChip category={f.category} />
                  <span className="text-[11px] text-slate-400" title={formatDateTime(f.created_at)}>
                    {timeAgo(f.created_at)}
                  </span>
                </div>
                <p className="whitespace-pre-wrap break-words text-sm text-slate-700">
                  {f.message}
                </p>
              </div>
              <StatusPill status={f.status} />
            </li>
          ))}
        </ul>
      </div>

      {/* --- Semua saran (admin) --- */}
      {isAdmin && (
        <div className="card p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-800">Semua saran (admin)</h2>
            <span className="text-[11px] text-slate-400">
              {allQ.data ? `${allQ.data.length} masukan` : ''}
            </span>
          </div>
          {allQ.isLoading && <Spinner label="Memuat…" />}
          {allQ.data && allQ.data.length === 0 && (
            <p className="text-sm text-slate-400">Belum ada masukan dari pengguna.</p>
          )}
          <ul className="divide-y divide-slate-100">
            {(allQ.data ?? []).map((f: FeedbackItem) => (
              <li key={f.id} className="flex flex-wrap items-start gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-700">
                      {f.user_name || 'Tanpa nama'}
                    </span>
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      {f.user_role}
                    </span>
                    <CategoryChip category={f.category} />
                    <span
                      className="text-[11px] text-slate-400"
                      title={formatDateTime(f.created_at)}
                    >
                      {timeAgo(f.created_at)}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-sm text-slate-700">
                    {f.message}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    className="input px-2 py-1 text-xs"
                    value={f.status}
                    onChange={(e) =>
                      statusMutation.mutate({ id: f.id, status: e.target.value })
                    }
                  >
                    <option value="baru">Baru</option>
                    <option value="ditinjau">Ditinjau</option>
                    <option value="selesai">Selesai</option>
                  </select>
                  <button
                    type="button"
                    title="Hapus (spam)"
                    className="rounded-lg p-1.5 text-rose-500 transition hover:bg-rose-50"
                    onClick={() => {
                      if (window.confirm('Hapus masukan ini? Tindakan permanen.')) {
                        deleteMutation.mutate(f.id)
                      }
                    }}
                  >
                    <IconTrash className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
