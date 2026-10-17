// Panel terminal web (xterm.js — library yang sama dengan terminal VS Code).
// Shell berjalan DI DALAM container kernel sesi user (docker exec di backend):
// hanya melihat /work, /persist miliknya, dan mount bersama read-only — folder
// user lain tidak pernah ada di namespace container. Toggle: Ctrl+` (ala VS Code).
//
// Shell MILIK SESI (bukan milik panel): pindah menu/window/tab atau menyembunyikan
// panel hanya melepas koneksi — proses tetap jalan di server dan outputnya
// diputar ulang saat panel tersambung lagi. Shell berhenti hanya lewat tombol
// "Hentikan", perintah `exit`, atau kernel dimatikan.
import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

import { api } from '../lib/api'
import { IconStop, IconX } from './icons'

type Mode = 'live' | 'retry' | 'ended' | 'kicked'

const RETRY_MAX_MS = 10_000
const PING_MS = 25_000

export default function TerminalPanel({
  sessionId,
  onHide,
  onKill,
}: {
  sessionId: string
  /** Sembunyikan panel saja — shell tetap jalan. */
  onHide: () => void
  /** Dipanggil setelah shell diminta berhenti. */
  onKill: () => void
}) {
  const holderRef = useRef<HTMLDivElement | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [mode, setMode] = useState<Mode>('live')

  useEffect(() => {
    const el = holderRef.current
    if (!el) return
    const term = new Terminal({
      fontSize: 13,
      fontFamily:
        'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
      cursorBlink: true,
      scrollback: 5000,
      theme: {
        background: '#0f172a', // slate-900 — senada toolbar notebook
        foreground: '#e2e8f0',
        cursor: '#38bdf8',
        selectionBackground: '#334155',
      },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(el)
    fit.fit()

    let disposed = false
    let current: Mode = 'live'
    let attempt = 0
    let retryTimer: number | undefined
    const note = (msg: string) => term.write(`\r\n\x1b[90m[${msg}]\x1b[0m\r\n`)
    const setM = (m: Mode) => {
      current = m
      setMode(m)
    }
    const sendResize = () => {
      const ws = wsRef.current
      if (ws?.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    }

    const connect = () => {
      if (disposed) return
      window.clearTimeout(retryTimer)
      const old = wsRef.current
      if (old && old.readyState <= WebSocket.OPEN) return
      const ws = new WebSocket(api.interactiveTerminalWsUrl(sessionId))
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws
      ws.onopen = () => {
        attempt = 0
        // Server segera memutar ulang riwayat layar -> mulai dari layar bersih.
        term.reset()
        setM('live')
        sendResize()
        term.focus()
      }
      ws.onmessage = (ev) => term.write(new Uint8Array(ev.data as ArrayBuffer))
      ws.onclose = (ev) => {
        if (disposed || wsRef.current !== ws) return
        wsRef.current = null
        if (ev.code === 4409) {
          note('terminal sedang dibuka di tab/jendela lain — klik di sini atau tekan tombol apa saja untuk mengambil alih')
          setM('kicked')
          return
        }
        const final: Record<number, string> = {
          1000: 'shell selesai',
          4401: 'sesi login berakhir — silakan login ulang',
          4404: 'kernel tidak aktif — nyalakan kernel dulu',
          4500: 'shell gagal dijalankan',
        }
        if (ev.code in final) {
          note(`${final[ev.code]} — tekan Enter untuk membuka shell baru`)
          setM('ended')
          return
        }
        // Putus tak terduga (jaringan/proxy/backend restart): sambung ulang otomatis.
        if (current !== 'retry') note('koneksi terputus — menyambung ulang…')
        setM('retry')
        const delay = Math.min(RETRY_MAX_MS, 500 * 2 ** attempt++)
        retryTimer = window.setTimeout(connect, delay)
      }
    }

    const sub = term.onData((d) => {
      if (current === 'kicked') return connect()
      if (current === 'ended') {
        if (d.includes('\r')) connect()
        return
      }
      const ws = wsRef.current
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data: d }))
    })
    const onClickTakeover = () => {
      if (current === 'kicked') connect()
    }
    el.addEventListener('mousedown', onClickTakeover)
    const onVisible = () => {
      if (document.visibilityState === 'visible' && current === 'retry') connect()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('online', onVisible)
    const ping = window.setInterval(() => {
      const ws = wsRef.current
      if (ws?.readyState === WebSocket.OPEN) ws.send('{"type":"ping"}')
    }, PING_MS)
    const ro = new ResizeObserver(() => {
      fit.fit()
      sendResize()
    })
    ro.observe(el)

    connect()

    return () => {
      disposed = true
      window.clearTimeout(retryTimer)
      window.clearInterval(ping)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('online', onVisible)
      el.removeEventListener('mousedown', onClickTakeover)
      sub.dispose()
      ro.disconnect()
      // Lepas koneksi SAJA — shell di server tetap jalan.
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        ws.onclose = null
        ws.close()
      }
      term.dispose()
    }
  }, [sessionId])

  const kill = () => {
    if (!window.confirm('Hentikan shell terminal? Proses yang sedang berjalan di terminal ikut berhenti.'))
      return
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'kill' }))
    } else if (mode !== 'ended') {
      // Belum tersambung: buka koneksi singkat khusus untuk mengirim perintah berhenti.
      const tmp = new WebSocket(api.interactiveTerminalWsUrl(sessionId))
      tmp.onopen = () => tmp.send(JSON.stringify({ type: 'kill' }))
    }
    onKill()
  }

  const status =
    mode === 'retry'
      ? ' · menyambung ulang…'
      : mode === 'kicked'
        ? ' · dibuka di tab lain'
        : mode === 'ended'
          ? ' · shell berhenti'
          : ''

  return (
    <div className="overflow-hidden rounded-xl bg-slate-900 shadow-lg ring-1 ring-white/10">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
        <span className="font-mono text-[11px] text-slate-400">
          Terminal — /work (container sesi) · bash · git · nano tersedia
          <span className="text-amber-300/80">{status}</span>
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={kill}
            title="Hentikan shell (proses di terminal ikut berhenti)"
            className="rounded p-1 text-slate-400 transition hover:bg-rose-500/20 hover:text-rose-300"
          >
            <IconStop className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onHide}
            title="Sembunyikan terminal — shell tetap jalan (Ctrl+`)"
            className="rounded p-1 text-slate-400 transition hover:bg-white/10 hover:text-slate-200"
          >
            <IconX className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div ref={holderRef} className="h-72 px-2 py-1.5" />
    </div>
  )
}
