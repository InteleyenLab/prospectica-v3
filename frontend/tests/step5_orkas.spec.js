import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')

describe('Consola Orkas persistente en Step5Interaction y HistoryDatabase (Fase 5)', () => {
  it('integra OrkasConsole, FocusGroupRoom, WhatsAppChatPanel y StructuredSurveyTab sin literales CJK', () => {
    const swarmFiles = [
      'OrkasConsole.vue',
      'FocusGroupRoom.vue',
      'WhatsAppChatPanel.vue',
      'StructuredSurveyTab.vue'
    ]
    swarmFiles.forEach((f) => {
      const code = readFileSync(resolve(frontendRoot, 'src/components/swarm', f), 'utf-8')
      expect(/[\u4e00-\u9fff]/.test(code)).toBe(false)
    })

    const step5 = readFileSync(resolve(frontendRoot, 'src/components/Step5Interaction.vue'), 'utf-8')
    expect(step5).toContain('OrkasConsole')
    expect(step5).toContain('FocusGroupRoom')
    expect(step5).toContain('WhatsAppChatPanel')
    expect(step5).toContain('StructuredSurveyTab')
    expect(/[\u4e00-\u9fff]/.test(step5)).toBe(false)

    const hist = readFileSync(resolve(frontendRoot, 'src/components/HistoryDatabase.vue'), 'utf-8')
    expect(hist).toContain('goToInteraction')
    expect(/[\u4e00-\u9fff]/.test(hist)).toBe(false)

    const repApi = readFileSync(resolve(frontendRoot, 'src/api/report.js'), 'utf-8')
    expect(repApi).toContain('/manifest')
    expect(repApi).toContain('/sessions')
    expect(repApi).toContain('/message')
  })
})
