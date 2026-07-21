// Tema terang/gelap (class 'dark' pada <html>). Preferensi disimpan di localStorage
// per-browser dan diterapkan SEBELUM render pertama (dipanggil dari main.tsx) agar
// tidak berkedip (flash of light theme).
export type Theme = 'light' | 'dark'

const KEY = 'ch_theme'

export function getTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function applyTheme(t: Theme): void {
  document.documentElement.classList.toggle('dark', t === 'dark')
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
}
