// Helper formatting & util kelas CSS.

export function accountSourceLabel(account: { is_local?: boolean; is_sso?: boolean }): string {
  if (account.is_local) return 'Lokal'
  return account.is_sso ? 'ComputeHub (SSO)' : 'ComputeHub'
}

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

/** Parse ISO dari backend; anggap UTC bila tak ada timezone. */
export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)
  const d = new Date(hasTz ? iso : `${iso}Z`)
  return isNaN(d.getTime()) ? null : d
}

export function formatDateTime(iso: string | null | undefined): string {
  const d = parseDate(iso)
  if (!d) return '-'
  return d.toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function timeAgo(iso: string | null | undefined): string {
  const d = parseDate(iso)
  if (!d) return '-'
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)} dtk lalu`
  if (diff < 3600) return `${Math.floor(diff / 60)} mnt lalu`
  if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`
  return `${Math.floor(diff / 86400)} hari lalu`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return '-'
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`
  if (seconds < 60) return `${seconds.toFixed(1)} dtk`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  return `${h}j ${m % 60}m`
}

/** Nilai MiB (basis 1024: RAM, VRAM, kuota) -> "512 MiB" / "1,5 GiB". */
export function formatMB(mb: number | null | undefined): string {
  if (mb == null) return '-'
  if (mb < 1024) return `${mb.toFixed(0)} MiB`
  return `${(mb / 1024).toFixed(1)} GiB`
}

/** Byte -> satuan biner (KiB/MiB/GiB/TiB, basis 1024) — sama dgn kuota & `du -h`. */
export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes == null || !Number.isFinite(bytes)) return '—'
  const abs = Math.abs(bytes)
  if (abs < 1024) return `${Math.round(bytes)} B`
  const units = ['KiB', 'MiB', 'GiB', 'TiB']
  let v = bytes / 1024
  let i = 0
  while (Math.abs(v) >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(digits)} ${units[i]}`
}

export function pct(value: number, total: number): number {
  if (!total) return 0
  return Math.min(100, Math.max(0, (value / total) * 100))
}
