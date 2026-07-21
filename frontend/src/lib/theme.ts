// Tema terang/gelap/otomatis (class 'dark' pada <html>). Preferensi disimpan di
// localStorage per-browser dan diterapkan SEBELUM render pertama (dipanggil dari
// main.tsx) agar tidak berkedip. 'auto' = ikut prefers-color-scheme sistem.
export type Theme = 'light' | 'dark' | 'auto'

const KEY = 'ch_theme'

export function getTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'dark' || v === 'auto' ? v : 'light'
  } catch {
    return 'light'
  }
}

function systemDark(): boolean {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch {
    return false
  }
}

export function resolveTheme(t: Theme): 'light' | 'dark' {
  return t === 'auto' ? (systemDark() ? 'dark' : 'light') : t
}

export function applyTheme(t: Theme): void {
  document.documentElement.classList.toggle('dark', resolveTheme(t) === 'dark')
}

export function setTheme(t: Theme): void {
  try {
    localStorage.setItem(KEY, t)
  } catch {
    /* localStorage nonaktif — tema tetap berlaku untuk sesi ini */
  }
  applyTheme(t)
}

export function initTheme(): void {
  applyTheme(getTheme())
  // Mode 'auto': ikut perubahan tema OS secara langsung.
  try {
    window
      .matchMedia('(prefers-color-scheme: dark)')
      .addEventListener('change', () => {
        if (getTheme() === 'auto') applyTheme('auto')
      })
  } catch {
    /* browser lama tanpa addEventListener — abaikan */
  }
}
