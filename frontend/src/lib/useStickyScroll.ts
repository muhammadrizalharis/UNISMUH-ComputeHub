// Auto-scroll yang MENGHORMATI gulir pengguna.
//
// Menempelkan tampilan ke bawah tiap ada teks baru terasa benar saat kita memang
// sedang mengikuti jawaban. Tapi selama AI masih mengetik, pesan berubah tiap
// potongan -- kalau selalu dipaksa turun, pengguna tidak akan pernah bisa
// membaca ulang bagian atas: begitu di-scroll, langsung tertarik kembali.
//
// Jadi: ikuti ke bawah HANYA selama pengguna berada di dekat dasar. Begitu ia
// menggulir ke atas, tempelan dilepas sampai ia kembali sendiri ke bawah.

import { useCallback, useEffect, useRef, useState } from 'react'

const AMBANG_PX = 80 // sisa jarak ke dasar yang masih dianggap "sedang mengikuti"

export function useStickyScroll<T extends HTMLElement>(deps: unknown) {
  const ref = useRef<T>(null)
  const tinggiLama = useRef(0)
  const abaikanSampai = useRef(0)
  const [diAtas, setDiAtas] = useState(false)

  const onScroll = useCallback(() => {
    const el = ref.current
    if (!el || performance.now() < abaikanSampai.current) return
    setDiAtas(el.scrollHeight - el.scrollTop - el.clientHeight > AMBANG_PX)
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    // Keputusan diambil dari tinggi konten SEBELUM bertambah, bukan dari event
    // scroll terakhir. Saat streaming cepat, potongan teks berikutnya kerap tiba
    // sebelum browser sempat mengirim event scroll -- kalau bersandar pada event,
    // gulir pengguna terlewat dan ia tertarik balik ke dasar terus-menerus.
    const sisaSebelum = tinggiLama.current - el.scrollTop - el.clientHeight
    tinggiLama.current = el.scrollHeight
    if (sisaSebelum > AMBANG_PX) return
    el.scrollTop = el.scrollHeight
  }, [deps])

  const keBawah = useCallback(() => {
    const el = ref.current
    if (!el) return
    abaikanSampai.current = performance.now() + 600 // gulir mulus masih berjalan
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    tinggiLama.current = 0 // tempel lagi: konten berikutnya wajib ikut turun
    setDiAtas(false)
  }, [])

  return { ref, onScroll, diAtas, keBawah }
}
