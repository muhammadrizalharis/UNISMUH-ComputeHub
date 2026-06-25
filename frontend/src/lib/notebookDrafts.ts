// Penyimpanan draf notebook interaktif (kode sel) di localStorage.
// Kunci di-scope per-user (lihat InteractiveNotebook) supaya kode satu akun
// TIDAK terlihat oleh akun lain di browser yang sama.

export const NB_LS_PREFIX = 'computehub_nb_'

/** Hapus SEMUA draf notebook dari localStorage (dipanggil saat logout). */
export function clearNotebookDrafts(): void {
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(NB_LS_PREFIX)) keys.push(k)
    }
    keys.forEach((k) => localStorage.removeItem(k))
  } catch {
    /* localStorage nonaktif -> abaikan */
  }
}

/**
 * Hapus draf milik akun LAIN (atau legacy tanpa suffix uid) supaya kode satu
 * akun tidak terlihat akun lain di browser yang sama. Dipanggil saat editor
 * dibuka -> bersih walau user belum logout.
 */
export function pruneForeignDrafts(uid: number): void {
  try {
    const mine = `:${uid}`
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(NB_LS_PREFIX) && !k.endsWith(mine)) keys.push(k)
    }
    keys.forEach((k) => localStorage.removeItem(k))
  } catch {
    /* localStorage nonaktif -> abaikan */
  }
}
