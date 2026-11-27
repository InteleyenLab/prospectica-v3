import service from './index'
import { brandConfig } from '../config/brand.config'

/**
 * 
 * @param {Object} data - { simulation_id, force_regenerate? }
 */
export const generateReport = (data) => {
  return service.post('/api/report/generate', data)
}

/**
 * 
 * @param {string} reportId
 */
export const getReportStatus = (reportId) => {
  return service.get(`/api/report/generate/status`, { params: { report_id: reportId } })
}

/**
 *  Agent （）
 * @param {string} reportId
 * @param {number} fromLine - 
 */
export const getAgentLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/agent-log`, { params: { from_line: fromLine } })
}

/**
 * （）
 * @param {string} reportId
 * @param {number} fromLine - 
 */
export const getConsoleLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/console-log`, { params: { from_line: fromLine } })
}

/**
 * 
 * @param {string} reportId
 */
export const getReport = (reportId) => {
  return service.get(`/api/report/${reportId}`)
}

/**
 *  Report Agent 
 * @param {Object} data - { simulation_id, report_id?, message, chat_history? }
 */
export const chatWithReport = (data, files = []) => {
  if (files && files.length) {
    const form = new FormData()
    Object.entries(data).forEach(([k, v]) => {
      if (v === undefined || v === null) return
      form.append(k, typeof v === 'object' ? JSON.stringify(v) : v)
    })
    files.forEach(f => form.append('files', f))
    return service.post('/api/report/chat', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  }
  return service.post('/api/report/chat', data)
}

/**
 * Descarga el archivo Markdown completo del informe.
 * @param {string} reportId
 */
export const downloadReportMarkdown = (reportId) => {
  return downloadReportFormat(reportId, 'md')
}

/**
 * Descarga el informe en el formato solicitado (md, pdf, pptx, xlsx, zip).
 * @param {string} reportId
 * @param {string} format
 */
export const downloadReportFormat = (reportId, format = 'md') => {
  if (!reportId) return
  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  const fmt = String(format || 'md').toLowerCase()
  const link = document.createElement('a')
  link.href = `${baseUrl}/api/report/${encodeURIComponent(reportId)}/download?format=${encodeURIComponent(fmt)}`
  link.download = `${reportId}.${fmt}`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

/**
 * Abre una vista de impresión limpia para guardar o descargar el informe como PDF.
 * @param {Object} params - { reportId, outline, sections, renderMarkdown }
 */
export const exportReportToPdf = ({ reportId, outline, sections, renderMarkdown }) => {
  if (!outline) return
  const escapeHtml = (str) => String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

  const sectionHtml = (outline.sections || []).map((sec, idx) => {
    const rawBody = sections?.[idx + 1] || sec.content || ''
    const renderedBody = renderMarkdown ? renderMarkdown(rawBody) : escapeHtml(rawBody)
    const num = String(idx + 1).padStart(2, '0')
    return `
      <section class="pdf-section">
        <h2><span class="sec-num">${num}</span> ${escapeHtml(sec.title)}</h2>
        <div class="sec-body">${renderedBody}</div>
      </section>
    `
  }).join('')

  const printWin = window.open('', '_blank', 'width=900,height=700')
  if (!printWin) {
    window.print()
    return
  }

  printWin.document.write(`<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <title>${escapeHtml(outline.title || reportId || 'Estudio de Inteligencia de Mercados')}</title>
  <style>
    @page { size: A4; margin: 20mm 18mm; }
    body { font-family: 'Georgia', 'Times New Roman', serif; color: #111827; line-height: 1.65; max-width: 780px; margin: 0 auto; padding: 24px; }
    .meta { font-family: monospace; font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 12px; display: flex; justify-content: space-between; border-bottom: 1px solid #E5E7EB; padding-bottom: 8px; }
    h1 { font-size: 28px; line-height: 1.25; margin: 12px 0; color: #0F172A; }
    .summary { font-style: italic; color: #4B5563; font-size: 15px; border-left: 3px solid #111827; padding-left: 14px; margin: 16px 0 28px 0; }
    .pdf-section { margin-bottom: 26px; page-break-inside: avoid; }
    .pdf-section h2 { font-size: 19px; color: #111827; border-bottom: 1px solid #E5E7EB; padding-bottom: 6px; margin-bottom: 12px; }
    .sec-num { font-family: monospace; color: #6B7280; font-size: 14px; margin-right: 6px; }
    .sec-body p, .md-p { margin: 0 0 10px 0; font-size: 14px; }
    .md-quote, blockquote { border-left: 3px solid #D1D5DB; margin: 10px 0; padding: 6px 14px; color: #374151; background: #F9FAFB; font-style: italic; }
    ul, ol { margin: 8px 0 12px 20px; padding-left: 8px; }
    li { margin-bottom: 4px; font-size: 14px; }
    strong { font-weight: 700; color: #111827; }
    .md-table-wrap { margin: 12px 0; border: 1px solid #D1D5DB; border-radius: 6px; overflow: hidden; }
    .md-table, table { width: 100%; border-collapse: collapse; font-size: 12.5px; line-height: 1.45; }
    .md-table th, th { background: #1F2937; color: #FFFFFF; font-weight: 600; text-align: left; padding: 8px 10px; border-right: 1px solid #374151; }
    .md-table td, td { padding: 8px 10px; border-top: 1px solid #E5E7EB; border-right: 1px solid #E5E7EB; vertical-align: top; }
    .md-table th:last-child, .md-table td:last-child, th:last-child, td:last-child { border-right: none; }
    .md-table tbody tr:nth-child(even), tbody tr:nth-child(even) { background: #F9FAFB; }
    @media print { body { padding: 0; } }
  </style>
</head>
<body>
  <div class="meta">
    <span>${escapeHtml(brandConfig.pdfHeaderLabel)}</span>
    <span>ID: ${escapeHtml(reportId || '')}</span>
  </div>
  <h1>${escapeHtml(outline.title)}</h1>
  ${outline.summary ? `<div class="summary">${escapeHtml(outline.summary)}</div>` : ''}
  ${sectionHtml}
  <script>
    window.onload = function() { setTimeout(function() { window.print(); }, 250); };
  <\/script>
</body>
</html>`)
  printWin.document.close()
}

export const getReportManifest = (reportId) => {
  return service.get(`/api/report/${encodeURIComponent(reportId)}/manifest`)
}

export const getReportChapter = (reportId, chapterNum) => {
  return service.get(`/api/report/${encodeURIComponent(reportId)}/chapter/${chapterNum}`)
}

export const createSwarmSession = (simulationId, data = {}) => {
  return service.post(`/api/swarm/${encodeURIComponent(simulationId)}/sessions`, data)
}

export const getSwarmSessions = (simulationId) => {
  return service.get(`/api/swarm/${encodeURIComponent(simulationId)}/sessions`)
}

export const sendSwarmMessage = (simulationId, data = {}) => {
  return service.post(`/api/swarm/${encodeURIComponent(simulationId)}/message`, data)
}
