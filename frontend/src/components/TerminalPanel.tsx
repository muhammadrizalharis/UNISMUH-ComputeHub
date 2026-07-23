// Panel terminal web (xterm.js — library yang sama dengan terminal VS Code).
// Shell berjalan DI DALAM container kernel sesi user (docker exec di backend):
// hanya melihat /work, /persist miliknya, dan mount bersama read-only — folder
// user lain tidak pernah ada di namespace container. Toggle: Ctrl+` (ala VS Code).
import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

import { api } from '../lib/api'
import { IconX } from './icons'

export default function TerminalPanel({
  sessionId,
  onClose,
}: {
  sessionId: string
  onClose: () => void
}) {
  const holderRef = useRef<HTMLDivElement | null>(null)

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

    const ws = new WebSocket(api.interactiveTerminalWsUrl(sessionId))
    ws.binaryType = 'arraybuffer'
    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    }
    ws.onopen = () => {
      sendResize()
      term.focus()
    }
    ws.onmessage = (ev) => term.write(new Uint8Array(ev.data as ArrayBuffer))
    ws.onclose = (ev) => {
      const alasan =
        ev.code === 4404
          ? ' — kernel tidak aktif (nyalakan kernel dulu)'
          : ev.code === 4401
            ? ' — sesi login berakhir'
            : ''
      term.write(`\r\n\x1b[90m[terminal ditutup${alasan}]\x1b[0m\r\n`)
    }
    const sub = term.onData((d) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data: d }))
    })
    const ro = new ResizeObserver(() => {
      fit.fit()
      sendResize()
    })
    ro.observe(el)

    return () => {
      sub.dispose()
      ro.disconnect()
      ws.close()
      term.dispose()
    }
  }, [sessionId])

  return (
    <div className="overflow-hidden rounded-xl bg-slate-900 shadow-lg ring-1 ring-white/10">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
        <span className="font-mono text-[11px] text-slate-400">
          Terminal — /work (container sesi) · bash · git tersedia
        </span>
        <button
          onClick={onClose}
          title="Tutup terminal (Ctrl+`)"
          className="rounded p-1 text-slate-400 transition hover:bg-white/10 hover:text-slate-200"
        >
          <IconX className="h-3.5 w-3.5" />
        </button>
      </div>
      <div ref={holderRef} className="h-72 px-2 py-1.5" />
    </div>
  )
}
