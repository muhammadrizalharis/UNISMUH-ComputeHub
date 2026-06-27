import { useCallback, useState } from 'react'

import { IconRefresh } from './icons'
import { cn } from '../lib/format'

/**
 * Tombol "Refresh" dengan umpan-balik visual: saat diklik ikon berputar &
 * tombol dinonaktifkan selama minimal `minSpinMs` ms sehingga JELAS terlihat
 * sedang memuat — walau data dari cache datang seketika.
 */
export default function RefreshButton({
  onRefresh,
  label = 'Refresh',
  className,
  minSpinMs = 650,
}: {
  onRefresh: () => unknown | Promise<unknown>
  label?: string
  className?: string
  minSpinMs?: number
}) {
  const [busy, setBusy] = useState(false)

  const handle = useCallback(async () => {
    if (busy) return
    setBusy(true)
    const started = Date.now()
    try {
      await Promise.resolve(onRefresh())
    } finally {
      const wait = minSpinMs - (Date.now() - started)
      if (wait > 0) await new Promise((r) => setTimeout(r, wait))
      setBusy(false)
    }
  }, [busy, onRefresh, minSpinMs])

  return (
    <button
      type="button"
      onClick={() => void handle()}
      disabled={busy}
      className={cn('btn-ghost', busy && 'cursor-wait opacity-70', className)}
    >
      <IconRefresh className={cn('h-4 w-4', busy && 'animate-spin')} />
      {busy ? 'Memuat…' : label}
    </button>
  )
}
