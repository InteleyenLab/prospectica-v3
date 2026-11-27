import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')

const EXPECTED_CHANNELS = [
  'whatsapp_1on1',
  'focus_group',
  'street_survey',
  'facebook_groups',
  'tiktok',
  'instagram',
  'news_portals',
  'colombian_web',
  'advertising',
  'tv',
  'radio'
]

describe('Frontend Multicanal (11 canales + Encuesta N=300 + Legado, Fase 3)', () => {
  it('Step1GraphBuild expone selector de los 11 canales y tamaño de encuesta', () => {
    const step1 = readFileSync(resolve(frontendRoot, 'src/components/Step1GraphBuild.vue'), 'utf-8')
    EXPECTED_CHANNELS.forEach((cid) => expect(step1).toContain(cid))
    expect(step1).toContain('enabled_channels')
    expect(step1).toContain('survey_target_n')
    expect(/[\u4e00-\u9fff]/.test(step1)).toBe(false)
  })

  it('Step3Simulation expone ChannelMonitorWorkspace y api/simulation.js expone rutas /api/channels y /api/swarm', () => {
    const step3 = readFileSync(resolve(frontendRoot, 'src/components/Step3Simulation.vue'), 'utf-8')
    const simApi = readFileSync(resolve(frontendRoot, 'src/api/simulation.js'), 'utf-8')

    EXPECTED_CHANNELS.forEach((cid) => expect(step3).toContain(cid))
    expect(step3).toContain('handleRunMultichannel')
    expect(step3).toContain('handleRunSurvey')
    expect(/[\u4e00-\u9fff]/.test(step3)).toBe(false)

    expect(simApi).toContain('/api/channels/catalog')
    expect(simApi).toContain('/api/swarm/')
    expect(simApi).toContain('/survey/run')
  })
})
