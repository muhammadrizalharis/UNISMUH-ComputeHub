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
  const menempel = useRef(true)
  const [diAtas, setDiAtas] = useState(false)

  const onScroll = useCallback(() => {
    const el = ref.current
    if (!el) return
    const sisa = el.scrollHeight - el.scrollTop - el.clientHeight
    menempel.current = sisa <= AMBANG_PX
    setDiAtas(!menempel.current)
  }, [])

  useEffect(() => {
    const el = ref.current
    if (el && menempel.current) el.scrollTop = el.scrollHeight
  }, [deps])

  const keBawah = useCallback(() => {
    const el = ref.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    menempel.current = true
    setDiAtas(false)
  }, [])

  return { ref, onScroll, diAtas, keBawah }
}
