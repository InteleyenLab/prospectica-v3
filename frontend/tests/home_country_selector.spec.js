import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  setPendingUpload,
  getPendingUpload,
  clearPendingUpload
} from '../src/store/pendingUpload.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')

describe('Selector territorial opcional y flujo pendingUpload (Fase 1)', () => {
  beforeEach(() => {
    clearPendingUpload()
  })

  it('mantiene retrocompatibilidad de setPendingUpload con 2 argumentos y soporta territorialConfig opcional', () => {
    setPendingUpload([{ name: 'doc.pdf' }], 'Estudio de mercado base')
    let pending = getPendingUpload()
    expect(pending.isPending).toBe(true)
    expect(pending.territorialConfig).toBeNull()

    setPendingUpload([{ name: 'nexo.pdf' }], 'Validar NEXO Colombia', {
      countryCode: 'co',
      targetCities: ['Medellín', 'Bogotá D.C.'],
      targetStrata: ['E2', 'E3'],
      useOfficialSources: true,
      useLiveWeb: false
    })
    pending = getPendingUpload()
    expect(pending.territorialConfig.countryCode).toBe('co')
    expect(pending.territorialConfig.targetCities).toEqual(['Medellín', 'Bogotá D.C.'])
    expect(pending.territorialConfig.targetStrata).toEqual(['E2', 'E3'])
  })

  it('expone selector territorial opcional en Home.vue sin literales CJK', () => {
    const homeVue = readFileSync(resolve(frontendRoot, 'src/views/Home.vue'), 'utf-8')
    const mainViewVue = readFileSync(resolve(frontendRoot, 'src/views/MainView.vue'), 'utf-8')
    const graphApi = readFileSync(resolve(frontendRoot, 'src/api/graph.js'), 'utf-8')

    expect(homeVue).toContain('Contexto Territorial y Demográfico')
    expect(homeVue).toContain('getCountryPacks')
    expect(homeVue).toContain('getCountryCities')
    expect(/[\u4e00-\u9fff]/.test(homeVue)).toBe(false)

    expect(mainViewVue).toContain("formData.append('country_code'")
    expect(mainViewVue).toContain("formData.append('target_cities'")
    expect(graphApi).toContain('/api/country-packs')
  })
})
