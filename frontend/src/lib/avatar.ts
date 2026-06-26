// Foto profil disimpan lokal di browser (localStorage, per-user id).
// Catatan: tidak tersinkron antar-perangkat & tidak terlihat admin — cukup
// untuk personalisasi tampilan tanpa mengubah backend/DB. Gambar dikompres
// dulu agar hemat kuota localStorage (~5MB).

const keyOf = (uid: number) => `ch_avatar_${uid}`

/** Event global agar semua komponen Avatar ikut ter-update saat foto berubah. */
export const AVATAR_EVENT = 'ch:avatar-changed'

export function getAvatar(uid: number): string | null {
  try {
    return localStorage.getItem(keyOf(uid))
  } catch {
    return null
  }
}

export function setAvatar(uid: number, dataUrl: string | null): void {
  try {
    if (dataUrl) localStorage.setItem(keyOf(uid), dataUrl)
    else localStorage.removeItem(keyOf(uid))
  } catch {
    // kuota localStorage penuh / akses ditolak — abaikan saja
  }
  window.dispatchEvent(new Event(AVATAR_EVENT))
}

/**
 * Baca file gambar, perkecil ke maksimum 256px (lewat kanvas) lalu ekspor
 * sebagai JPEG agar ukuran base64 kecil & aman disimpan di localStorage.
 */
export function fileToAvatarDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) {
      reject(new Error('File harus berupa gambar.'))
      return
    }
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Gagal membaca file.'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('Gambar tidak valid.'))
      img.onload = () => {
        const max = 256
        const scale = Math.min(1, max / Math.max(img.width, img.height))
        const w = Math.max(1, Math.round(img.width * scale))
        const h = Math.max(1, Math.round(img.height * scale))
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          reject(new Error('Kanvas tidak didukung browser ini.'))
          return
        }
        ctx.drawImage(img, 0, 0, w, h)
        resolve(canvas.toDataURL('image/jpeg', 0.85))
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  })
}
