/**
 * 
 * ，ProcessAPI
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: '',
  territorialConfig: null,
  isPending: false
})

export function setPendingUpload(files, requirement, territorialConfig = null) {
  state.files = files
  state.simulationRequirement = requirement
  state.territorialConfig = territorialConfig
  state.isPending = true
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    territorialConfig: state.territorialConfig,
    isPending: state.isPending
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.territorialConfig = null
  state.isPending = false
}

export default state
