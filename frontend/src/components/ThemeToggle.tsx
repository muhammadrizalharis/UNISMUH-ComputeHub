import { useState } from 'react'

import { cn } from '../lib/format'
import { getTheme, setTheme, type Theme } from '../lib/theme'
import { IconMoon, IconSun } from './icons'

const CYCLE: Theme[] = ['light', 'dark', 'auto']
const NEXT_TITLE: Record<Theme, string> = {
  light: 'Ganti ke mode gelap',
  dark: 'Ganti ke mode ikuti sistem',
  auto: 'Ganti ke mode terang',
}

// Tombol ganti tema terang/gelap/ikuti-sistem (siklus).
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
    const next = CYCLE[(CYCLE.indexOf(theme) + 1) % CYCLE.length]
    setTheme(next)
    setThemeState(next)
  }
  return (
    <button
      onClick={flip}
      title={NEXT_TITLE[theme]}
      aria-label="Ganti tema"
      className={cn(
        'grid shrink-0 place-items-center transition',
        variant === 'overlay'
          ? 'h-10 w-10 rounded-xl bg-white/10 text-white ring-1 ring-white/20 backdrop-blur hover:bg-white/20'
          : 'h-9 w-9 rounded-xl bg-white text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50 hover:text-brand-600',
        className,
      )}
    >
      {theme === 'light' ? (
        <IconMoon className="h-5 w-5" />
      ) : theme === 'dark' ? (
        <span className="text-base leading-none" aria-hidden>
          ◐
        </span>
      ) : (
        <IconSun className="h-5 w-5" />
      )}
    </button>
  )
}
