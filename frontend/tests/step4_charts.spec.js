import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')

const CHARTS = [
  'VanWestendorpChart.vue',
  'GaborGrangerChart.vue',
  'FunnelChart.vue',
  'DistributionChart.vue',
  'DofaMatrix.vue'
]

describe('Componentes ECharts en Step4Report (Fase 5)', () => {
  it('usa echarts exclusivamente en los 5 gráficos y mantiene d3 exclusivo en GraphPanel.vue', () => {
    CHARTS.forEach((file) => {
      const code = readFileSync(resolve(frontendRoot, 'src/components/charts', file), 'utf-8')
      expect(code).toContain("from 'echarts'")
      expect(code).not.toContain("from 'd3'")
      expect(code).toContain('Number.isFinite')
      expect(/[\u4e00-\u9fff]/.test(code)).toBe(false)
    })

    const step4 = readFileSync(resolve(frontendRoot, 'src/components/Step4Report.vue'), 'utf-8')
    expect(step4).toContain('VanWestendorpChart')
    expect(step4).toContain('GaborGrangerChart')
    expect(step4).toContain('FunnelChart')
    expect(step4).toContain('DistributionChart')
    expect(step4).toContain('DofaMatrix')
    expect(step4).toContain('getReportManifest')
    expect(/[\u4e00-\u9fff]/.test(step4)).toBe(false)
  })
})
