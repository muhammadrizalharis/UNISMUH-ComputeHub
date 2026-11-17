import { cn } from '../lib/format'
import type { AssistantModelInfo } from '../lib/types'

export function parseModelList(raw: string | null | undefined): string[] {
  const out: string[] = []
  for (const part of (raw ?? '').split(/[,\n]/)) {
    const m = part.trim()
    if (m && !out.includes(m)) out.push(m)
  }
  return out
}

const CAPS: Record<string, string> = {
  vision: '👁',
  audio: '🔊',
  tools: '🧰',
  thinking: '🧠',
  embedding: 'embed',
}

/**
 * Pilih banyak model Ollama. Urutan = urutan centang; model pertama (★ utama) dipakai
 * Asisten AI web, semua yang dicentang tampil di Copilot Chat devbox.
 */
export default function ModelMultiSelect({
  value,
  models,
  onChange,
  emptyHint,
}: {
  value: string[]
  models: AssistantModelInfo[]
  onChange: (v: string[]) => void
  emptyHint?: string
}) {
  const unknown = value.filter((v) => !models.some((m) => m.name === v))
  const rows: AssistantModelInfo[] = [
    ...unknown.map((name) => ({ name, size_gb: 0, parameter_size: '', quantization: '' })),
    ...models.filter((m) => !(m.capabilities ?? []).includes('embedding')),
  ]
  const toggle = (name: string) =>
    onChange(value.includes(name) ? value.filter((v) => v !== name) : [...value, name])
  const makePrimary = (name: string) => onChange([name, ...value.filter((v) => v !== name)])

  return (
    <div className="space-y-1.5">
      <div className="max-h-64 overflow-y-auto rounded-xl border border-slate-200 p-1.5 dark:border-slate-700">
        {rows.map((m) => {
          const checked = value.includes(m.name)
          const primary = value[0] === m.name
          const caps = (m.capabilities ?? []).filter((c) => c !== 'completion')
          return (
            <label
              key={m.name}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800',
                checked && 'bg-indigo-50/60 dark:bg-indigo-500/10',
              )}
            >
              <input type="checkbox" checked={checked} onChange={() => toggle(m.name)} />
              <span className="min-w-0 flex-1 truncate">
                {m.name}
                <span className="ml-1 text-[11px] text-slate-400">
                  {m.size_gb ? `${m.size_gb} GB` : ''}
                  {m.parameter_size ? ` · ${m.parameter_size}` : ''}
                  {caps.length ? ` · ${caps.map((c) => CAPS[c] ?? c).join(' ')}` : ''}
                </span>
              </span>
              {primary ? (
                <span className="rounded bg-indigo-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  ★ utama
                </span>
              ) : (
                checked && (
                  <button
                    type="button"
                    className="rounded px-1.5 py-0.5 text-[10px] text-indigo-600 ring-1 ring-indigo-200 hover:bg-indigo-50"
                    onClick={(e) => {
                      e.preventDefault()
                      makePrimary(m.name)
                    }}
                  >
                    jadikan utama
                  </button>
                )
              )}
            </label>
          )
        })}
        {rows.length === 0 && <p className="px-2 py-1.5 text-xs text-slate-400">Daftar model belum termuat.</p>}
      </div>
      <p className="text-[11px] text-slate-400">
        ★ utama = model Asisten AI web. Semua yang dicentang tampil di Copilot Chat devbox
        (mode agent butuh 🧰 tools).{value.length === 0 && emptyHint ? ` ${emptyHint}` : ''}
      </p>
    </div>
  )
}
