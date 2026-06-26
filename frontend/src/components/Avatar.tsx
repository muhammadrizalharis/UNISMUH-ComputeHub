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
 * Avatar pengguna: tampilkan foto (`src`, data URL dari backend) bila ada, atau
 * inisial dengan gradien sesuai peran. Prop `className` mengatur ukuran, rounding
 * & ukuran teks.
 */
export default function Avatar({
  src,
  name,
  gradient,
  className,
}: {
  src?: string | null
  name: string
  gradient: string
  className?: string
}) {
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
