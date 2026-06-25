// Renderer Markdown minimal & AMAN untuk menampilkan sel markdown notebook.
// Prinsip keamanan: HTML di-escape DULU, baru transformasi terbatas diterapkan,
// sehingga konten notebook tidak bisa menyuntikkan tag/atribut berbahaya (XSS).
// Tanpa dependensi eksternal (hemat bundle).

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inline(s: string): string {
  let t = esc(s)
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
