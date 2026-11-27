import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')

describe('Step2EnvSetup auditoría demográfica y retrocompatibilidad (Fase 2)', () => {
  it('incluye panel de auditoría demográfica, badges colombianos y huso UTC-5 sin literales CJK', () => {
    const step2 = readFileSync(resolve(frontendRoot, 'src/components/Step2EnvSetup.vue'), 'utf-8')
    expect(step2).toContain('Auditoría Demográfica de la Muestra')
    expect(step2).toContain('America/Bogota')
    expect(step2).toContain('demographicSummary')
    expect(step2).toContain('attitude_segment')
    expect(step2).toContain('stratum_code')
    expect(step2).toContain('city_name')
    expect(/[\u4e00-\u9fff]/.test(step2)).toBe(false)
  })
})
