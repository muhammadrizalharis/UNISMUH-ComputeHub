import { useEffect, useState } from 'react'

import { AVATAR_EVENT, getAvatar } from '../lib/avatar'
import { cn } from '../lib/format'

function initials(name: string): string {
  return name
    .split(' ')
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
}

/**
 * Avatar pengguna: tampilkan foto (bila di-set di browser) atau inisial dengan
 * gradien sesuai peran. Prop `className` mengatur ukuran, rounding & ukuran teks.
 */
export default function Avatar({
  uid,
  name,
  gradient,
  className,
}: {
  uid: number
  name: string
  gradient: string
  className?: string
}) {
  const [src, setSrc] = useState<string | null>(() => getAvatar(uid))

  useEffect(() => {
    setSrc(getAvatar(uid))
    const sync = () => setSrc(getAvatar(uid))
    window.addEventListener(AVATAR_EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(AVATAR_EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [uid])

  if (src) {
    return <img src={src} alt={name} className={cn('object-cover', className)} />
  }

  return (
    <span
      className={cn(
        'grid place-items-center bg-gradient-to-br font-bold text-white',
        gradient,
        className,
      )}
    >
      {initials(name)}
    </span>
  )
}
