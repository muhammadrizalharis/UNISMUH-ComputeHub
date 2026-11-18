import type { QueueItem } from './types'
import { formatDuration } from './format'

const REASON: Record<NonNullable<QueueItem['waiting_reason']>, string> = {
  quota: 'Kuota GPU harian habis',
  scheduled: 'Menunggu jadwal',
  own_limit: 'Menunggu job/sesi Anda yang lain',
  gpu_full: 'GPU penuh',
  cpu_full: 'CPU penuh',
}

const SOURCE: Record<QueueItem['estimate_source'], string> = {
  riwayat: 'dari riwayat job bernama sama',
  pengguna: 'dari rata-rata job pemilik',
  umum: 'dari rata-rata job semua pengguna',
  bawaan: 'dari batas waktu bawaan (belum ada riwayat)',
}

export function queueReasonLabel(q: QueueItem): string | null {
  return q.waiting_reason ? REASON[q.waiting_reason] : null
}

/** Teks "mulai dalam": 'segera', '~5m 0s', atau 'belum bisa diperkirakan'. */
export function queueEtaText(q: QueueItem): string {
  if (q.eta_seconds == null) return 'belum bisa diperkirakan'
  if (q.eta_seconds < 1) return 'segera'
  return `~${formatDuration(q.eta_seconds)}`
}

export function queueEstimateHint(q: QueueItem): string {
  return `Perkiraan durasi ${SOURCE[q.estimate_source] ?? ''}`.trim()
}
