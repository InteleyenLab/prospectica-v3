import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')
const projectRoot = resolve(frontendRoot, '..')

describe('Contratos heredados y limpieza de UI (Fase 0)', () => {
  it('mantiene rutas principales de Vue Router sin dependencias de Process.vue legado', () => {
    const routerCode = readFileSync(resolve(frontendRoot, 'src/router/index.js'), 'utf-8')
    expect(routerCode).toContain('/process/:projectId')
    expect(routerCode).toContain('/simulation/:simulationId')
    expect(routerCode).toContain('/report/:reportId')
    expect(routerCode).toContain('/interaction/:reportId')
    expect(routerCode).not.toContain('Process.vue')
  })

  it('expone el botón Detener simulación conectado a handleStopSimulation en Step3Simulation.vue', () => {
    const step3 = readFileSync(resolve(frontendRoot, 'src/components/Step3Simulation.vue'), 'utf-8')
    expect(step3).toContain('handleStopSimulation')
    expect(step3).toContain('Detener simulación')
  })

  it('conserva español estricto sin literales CJK visibles en locales/es.json', () => {
    const esJson = JSON.parse(readFileSync(resolve(projectRoot, 'locales/es.json'), 'utf-8'))
    const raw = JSON.stringify(esJson)
    expect(/[\u4e00-\u9fff]/.test(raw)).toBe(false)
    expect(esJson.step5?.chatWithReportAgent).toBeTruthy()
  })
})
