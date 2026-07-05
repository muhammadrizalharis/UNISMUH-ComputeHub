// Util foto profil. Gambar dikompres di sisi klien (resize 256px -> JPEG) lalu
// dikirim sebagai data URL base64 ke backend untuk disimpan di kolom users.avatar
// (sinkron lintas perangkat & terlihat admin). Lihat api.updateAvatar.

/**
 * Baca file gambar, perkecil ke maksimum 256px (lewat kanvas) lalu ekspor
 * sebagai JPEG agar ukuran base64 kecil (hemat untuk disimpan di DB).
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

/**
 * Untuk gambar yang dilampirkan ke Asisten AI (input vision): perkecil ke maksimum
 * `max` px (default 1024) lalu ekspor JPEG q0.85 — payload tetap wajar tetapi detail
 * cukup untuk dibaca model vision (mis. plot, screenshot, diagram).
 */
export function fileToChatImageDataUrl(file: File, max = 1024): Promise<string> {
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
