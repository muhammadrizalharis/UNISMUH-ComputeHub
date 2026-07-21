import { useState } from 'react'

import { cn } from '../lib/format'
import { getTheme, setTheme } from '../lib/theme'
import { IconMoon, IconSun } from './icons'

// Tombol ganti tema terang/gelap.
// variant 'overlay' = untuk halaman berlatar foto gelap (landing/login);
// variant 'ghost'   = untuk di dalam aplikasi (ikut tema via kelas ter-remap).
export default function ThemeToggle({
  variant = 'ghost',
  className,
}: {
  variant?: 'ghost' | 'overlay'
  className?: string
}) {
  const [theme, setThemeState] = useState(getTheme())
  const flip = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    setThemeState(next)
  }
  return (
    <button
      onClick={flip}
      title={theme === 'dark' ? 'Ganti ke mode terang' : 'Ganti ke mode gelap'}
      aria-label="Ganti tema"
      className={cn(
        'grid shrink-0 place-items-center transition',
        variant === 'overlay'
          ? 'h-10 w-10 rounded-xl bg-white/10 text-white ring-1 ring-white/20 backdrop-blur hover:bg-white/20'
          : 'h-9 w-9 rounded-xl bg-white text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50 hover:text-brand-600',
        className,
      )}
    >
      {theme === 'dark' ? (
        <IconSun className="h-5 w-5" />
      ) : (
        <IconMoon className="h-5 w-5" />
      )}
    </button>
  )
}
