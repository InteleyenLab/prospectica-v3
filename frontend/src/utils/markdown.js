import { Marked } from 'marked'
import DOMPurify from 'dompurify'

const md = new Marked({
  gfm: true,
  breaks: true
})

md.use({
  renderer: {
    heading({ tokens, depth }) {
      const text = this.parser.parseInline(tokens)
      const mapped = Math.min(5, Math.max(2, depth + 1))
      return `<h${mapped} class="md-h${mapped}">${text}</h${mapped}>\n`
    },
    blockquote({ tokens }) {
      const body = this.parser.parse(tokens)
      return `<blockquote class="md-quote">${body}</blockquote>\n`
    },
    table(token) {
      const headerCells = token.header
        .map((cell) => `<th>${this.parser.parseInline(cell.tokens)}</th>`)
        .join('')
      const bodyRows = token.rows
        .map((row) => {
          const cols = row.map((cell) => `<td>${this.parser.parseInline(cell.tokens)}</td>`).join('')
          return `<tr>${cols}</tr>`
        })
        .join('')
      return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table></div>\n`
    },
    code({ text }) {
      const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
      return `<pre class="code-block"><code>${escaped}</code></pre>\n`
    },
    codespan({ text }) {
      const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
      return `<code class="inline-code">${escaped}</code>`
    },
    hr() {
      return '<hr class="md-hr">\n'
    }
  }
})

/**
 * Convierte Markdown a HTML preservando tablas/estilos y sanitizando cualquier vector XSS vía DOMPurify.
 */
export function renderSafeMarkdown(content) {
  if (!content) return ''
  const processedContent = String(content)
    .replace(/\r\n/g, '\n')
    .replace(/^##(?!#)\s+.+\n+/, '')

  const rawHtml = md.parse(processedContent)
  if (typeof DOMPurify?.sanitize === 'function') {
    return DOMPurify.sanitize(rawHtml, {
      USE_PROFILES: { html: true },
      ALLOW_UNKNOWN_PROTOCOLS: false,
      FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form'],
      FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur']
    })
  }
  return rawHtml
}
