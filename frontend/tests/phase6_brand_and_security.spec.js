// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { brandConfig } from '../src/config/brand.config.js'
import { renderSafeMarkdown } from '../src/utils/markdown.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')
const projectRoot = resolve(frontendRoot, '..')

describe('Fase 6 (Gate G6): Seguridad XSS DOMPurify y Migración a Prospéctica Inc.', () => {
  it('neutraliza vectores XSS en Markdown manteniendo tablas y formato válido', () => {
    const dirtyMd = [
      '### Resumen Seguro',
      '<script>alert("xss")</script>',
      '<img src="x" onerror="alert(1)" />',
      '<iframe src="https://evil.example"></iframe>',
      '',
      '[Enlace peligroso](javascript:alert(2)) y <a href="javascript:alert(3)">click</a>',
      '',
      '| Ciudad | Precio Óptimo |',
      '|---|---|',
      '| Medellín | COP $70.000 |'
    ].join('\n')

    const cleanHtml = renderSafeMarkdown(dirtyMd)
    expect(cleanHtml).not.toContain('<script')
    expect(cleanHtml).not.toContain('<iframe')
    expect(cleanHtml).not.toContain('onerror=')
    expect(cleanHtml).not.toContain('javascript:')
    expect(cleanHtml).toContain('md-table')
    expect(cleanHtml).toContain('Medellín')
  })

  it('expone configuración centralizada de Prospéctica Inc. y elimina MiroFish visible de vistas, locales y exports', () => {
    expect(brandConfig.name).toBe('Prospéctica Inc.')
    expect(brandConfig.uppercaseName).toBe('PROSPÉCTICA INC.')
    expect(brandConfig.storageKeys.splitLeft).toBe('prospectica_split_left')
    expect(brandConfig.storageKeys.legacySplitLeft).toBe('prospectica_split_left')

    const filesToCheck = [
      resolve(projectRoot, 'locales/es.json'),
      resolve(frontendRoot, 'index.html'),
      resolve(frontendRoot, 'src/views/Home.vue'),
      resolve(frontendRoot, 'src/views/MainView.vue'),
      resolve(frontendRoot, 'src/views/SimulationView.vue'),
      resolve(frontendRoot, 'src/views/SimulationRunView.vue'),
      resolve(frontendRoot, 'src/views/ReportView.vue'),
      resolve(frontendRoot, 'src/views/InteractionView.vue'),
      resolve(frontendRoot, 'src/api/report.js')
    ]

    for (const filePath of filesToCheck) {
      const content = readFileSync(filePath, 'utf-8')
      expect(content).not.toMatch(/mirofish/i)
      expect(/[\u4e00-\u9fff]/.test(content)).toBe(false)
    }

    const indexHtml = readFileSync(resolve(frontendRoot, 'index.html'), 'utf-8')
    expect(indexHtml).toContain('Prospéctica Inc.')

    const esJson = JSON.parse(readFileSync(resolve(projectRoot, 'locales/es.json'), 'utf-8'))
    expect(esJson.meta.title).toContain('Prospéctica Inc.')
    expect(esJson.home.heroDescBrand).toBe('Prospéctica Inc.')
    expect(esJson.home.engineBadge).toContain('Prospéctica')
    expect(esJson.step5.chatWithReportAgent).toBeTruthy()
  })

  it('delega renderMarkdown de Step4Report y Step5Interaction en renderSafeMarkdown y migra localStorage sin regresión', () => {
    const step4 = readFileSync(resolve(frontendRoot, 'src/components/Step4Report.vue'), 'utf-8')
    const step5 = readFileSync(resolve(frontendRoot, 'src/components/Step5Interaction.vue'), 'utf-8')

    expect(step4).toContain('renderSafeMarkdown')
    expect(step5).toContain('renderSafeMarkdown')
    expect(step5).toContain('brandConfig.storageKeys.splitLeft')
    expect(step5).toContain('brandConfig.storageKeys.legacySplitLeft')
  })
})
