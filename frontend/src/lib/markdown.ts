// Renderer Markdown minimal & AMAN untuk menampilkan sel markdown notebook.
// Prinsip keamanan: HTML di-escape DULU, baru transformasi terbatas diterapkan,
// sehingga konten notebook tidak bisa menyuntikkan tag/atribut berbahaya (XSS).
// Tanpa dependensi eksternal (hemat bundle).

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Renderer ini sengaja tanpa KaTeX (hemat ~300 KB). Model kadang tetap menulis
// LaTeX seperti "$\rightarrow$" yang lalu tampil mentah, jadi perintah yang umum
// dipakai diterjemahkan ke Unicode.
const SIMBOL: Record<string, string> = {
  rightarrow: '→', to: '→', leftarrow: '←', leftrightarrow: '↔',
  Rightarrow: '⇒', Leftarrow: '⇐', Leftrightarrow: '⇔', mapsto: '↦',
  times: '×', cdot: '·', div: '÷', pm: '±', mp: '∓',
  neq: '≠', ne: '≠', leq: '≤', le: '≤', geq: '≥', ge: '≥', approx: '≈', equiv: '≡',
  ll: '≪', gg: '≫', propto: '∝',
  sum: '∑', prod: '∏', int: '∫', sqrt: '√', partial: '∂', nabla: '∇', infty: '∞',
  in: '∈', notin: '∉', subset: '⊂', subseteq: '⊆', cup: '∪', cap: '∩',
  forall: '∀', exists: '∃', land: '∧', lor: '∨', neg: '¬',
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', varepsilon: 'ε',
  zeta: 'ζ', eta: 'η', theta: 'θ', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν',
  xi: 'ξ', rho: 'ρ', sigma: 'σ', tau: 'τ', phi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Sigma: 'Σ', Phi: 'Φ', Omega: 'Ω',
  ldots: '…', dots: '…', cdots: '⋯', quad: ' ', qquad: '  ',
}

function matematika(s: string): string {
  if (!s.includes('\\') && !s.includes('$')) return s
  // Lepas pembatas $...$ HANYA bila isinya memang LaTeX (ada backslash), supaya
  // teks biasa seperti "$5 dan $10" tidak ikut termakan.
  const buka = (_m: string, isi: string) => (isi.includes('\\') ? isi : _m)
  let t = s
    .replace(/\$\$([\s\S]+?)\$\$/g, buka)
    .replace(/\$([^$\n]+?)\$/g, buka)
    .replace(/\\\(([\s\S]+?)\\\)/g, '$1')
    .replace(/\\\[([\s\S]+?)\\\]/g, '$1')
  t = t.replace(/\\(?:text|textbf|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}/g, '$1')
  t = t.replace(/\\([%&#_{}$])/g, '$1')
  return t.replace(/\\([A-Za-z]+)/g, (m, nama: string) => SIMBOL[nama] ?? m)
}

function inline(s: string): string {
  let t = esc(matematika(s))
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>')
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  // Link [teks](url) — hanya skema aman; selain itu tampilkan teks saja.
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, txt: string, url: string) => {
    const safe = /^(https?:|mailto:|\/|#|\.)/i.test(url)
    return safe
      ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${txt}</a>`
      : txt
  })
  return t
}

const BLOCK_RE = /^(#{1,6}\s|```|>\s?|\s*[-*+]\s|\s*\d+\.\s|(-{3,}|\*{3,}|_{3,})\s*$)/

export function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let i = 0
  let list: 'ul' | 'ol' | null = null
  const closeList = () => {
    if (list) {
      html.push(`</${list}>`)
      list = null
    }
  }

  while (i < lines.length) {
    const line = lines[i]

    if (/^```/.test(line.trim())) {
      closeList()
      const buf: string[] = []
      i++
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        buf.push(esc(lines[i]))
        i++
      }
      i++ // lewati fence penutup
      html.push(`<pre class="md-pre"><code>${buf.join('\n')}</code></pre>`)
      continue
    }

    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      closeList()
      const lvl = h[1].length
      html.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`)
      i++
      continue
    }

    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      closeList()
      html.push('<hr/>')
      i++
      continue
    }

    if (/^>\s?/.test(line)) {
      closeList()
      html.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`)
      i++
      continue
    }

    const ul = line.match(/^\s*[-*+]\s+(.*)$/)
    if (ul) {
      if (list !== 'ul') {
        closeList()
        html.push('<ul>')
        list = 'ul'
      }
      html.push(`<li>${inline(ul[1])}</li>`)
      i++
      continue
    }

    const ol = line.match(/^\s*\d+\.\s+(.*)$/)
    if (ol) {
      if (list !== 'ol') {
        closeList()
        html.push('<ol>')
        list = 'ol'
      }
      html.push(`<li>${inline(ol[1])}</li>`)
      i++
      continue
    }

    if (!line.trim()) {
      closeList()
      i++
      continue
    }

    closeList()
    const para: string[] = [line]
    i++
    while (i < lines.length && lines[i].trim() && !BLOCK_RE.test(lines[i])) {
      para.push(lines[i])
      i++
    }
    html.push(`<p>${inline(para.join(' '))}</p>`)
  }

  closeList()
  return html.join('\n')
}
