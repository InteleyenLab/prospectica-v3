import service from './index'

/**
 * 
 * @param {Object} data - { project_id, graph_id?, enable_twitter?, enable_reddit? }
 */
export const createSimulation = (data) => {
  return service.post('/api/simulation/create', data)
}

/**
 * （）
 * @param {Object} data - { simulation_id, entity_types?, use_llm_for_profiles?, parallel_profile_count?, force_regenerate? }
 */
export const prepareSimulation = (data) => {
  return service.post('/api/simulation/prepare', data)
}

/**
 * 
 * @param {Object} data - { task_id?, simulation_id? }
 */
export const getPrepareStatus = (data) => {
  return service.post('/api/simulation/prepare/status', data)
}

/**
 * 
 * @param {string} simulationId
 */
export const getSimulation = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}`)
}

/**
 * Elimina una simulación individual del historial
 */
export const deleteSimulation = (simulationId) => {
  return service.delete(`/api/simulation/${encodeURIComponent(simulationId)}`)
}

/**
 *  Agent Profiles
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' | 'twitter'（）
 */
export const getSimulationProfiles = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles`, { params })
}

/**
 *  Agent Profiles
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' | 'twitter'（）
 */
export const getSimulationProfilesRealtime = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles/realtime`, { params })
}

/**
 * 
 * @param {string} simulationId
 */
export const getSimulationConfig = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config`)
}

/**
 * 
 * @param {string} simulationId
 * @returns {Promise} ，
 */
export const getSimulationConfigRealtime = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config/realtime`)
}

/**
 * 
 * @param {string} projectId - ，ID
 */
export const listSimulations = (projectId) => {
  const params = projectId ? { project_id: projectId } : {}
  return service.get('/api/simulation/list', { params })
}

/**
 * 
 * @param {Object} data - { simulation_id, platform?, max_rounds?, enable_graph_memory_update? }
 */
export const startSimulation = (data) => {
  return service.post('/api/simulation/start', data)
}

/**
 * 
 * @param {Object} data - { simulation_id }
 */
export const stopSimulation = (data) => {
  return service.post('/api/simulation/stop', data)
}

/**
 * 
 * @param {string} simulationId
 */
export const getRunStatus = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status`)
}

/**
 * （）
 * @param {string} simulationId
 */
export const getRunStatusDetail = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status/detail`)
}

/**
 * 
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' | 'twitter'（）
 * @param {number} limit - 
 * @param {number} offset - 
 */
export const getSimulationPosts = (simulationId, platform, limit = 50, offset = 0) => {
  const params = { limit, offset }
  if (platform) params.platform = platform
  return service.get(`/api/simulation/${simulationId}/posts`, { params })
}

/**
 * （）
 * @param {string} simulationId
 * @param {number} startRound - 
 * @param {number} endRound - 
 */
export const getSimulationTimeline = (simulationId, startRound = 0, endRound = null) => {
  const params = { start_round: startRound }
  if (endRound !== null) {
    params.end_round = endRound
  }
  return service.get(`/api/simulation/${simulationId}/timeline`, { params })
}

/**
 * Agent
 * @param {string} simulationId
 */
export const getAgentStats = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/agent-stats`)
}

/**
 * 
 * @param {string} simulationId
 * @param {Object} params - { limit, offset, platform, agent_id, round_num }
 */
export const getSimulationActions = (simulationId, params = {}) => {
  return service.get(`/api/simulation/${simulationId}/actions`, { params })
}

/**
 * （）
 * @param {Object} data - { simulation_id, timeout? }
 */
export const closeSimulationEnv = (data) => {
  return service.post('/api/simulation/close-env', data)
}

/**
 * 
 * @param {Object} data - { simulation_id }
 */
export const getEnvStatus = (data) => {
  return service.post('/api/simulation/env-status', data)
}

/**
 *  Agent
 * @param {Object} data - { simulation_id, interviews: [{ agent_id, prompt }] }
 */
export const interviewAgents = (data) => {
  return service.post('/api/simulation/interview/batch', data)
}

/**
 * （）
 * 
 * @param {number} limit - 
 */
export const getSimulationHistory = (limit = 20) => {
  return service.get('/api/simulation/history', { params: { limit } })
}

/**
 * Lista el catálogo oficial de los 11 canales colombianos + compatibilidad legada.
 */
export const getChannelsCatalog = (includeLegacy = true) => {
  return service.get('/api/channels/catalog', { params: { include_legacy: includeLegacy } })
}

/**
 * Obtiene eventos multicanal persistidos en simulation_channels.db (o fallback legado).
 */
export const getChannelEvents = (simulationId, params = {}) => {
  return service.get(`/api/channels/${encodeURIComponent(simulationId)}/events`, { params })
}

/**
 * Obtiene sesiones detalladas de un canal (whatsapp_1on1, focus_group, street_survey, medios).
 */
export const getChannelSessions = (simulationId, channelId, limit = 200) => {
  return service.get(
    `/api/channels/${encodeURIComponent(simulationId)}/sessions/${encodeURIComponent(channelId)}`,
    { params: { limit } }
  )
}

/**
 * Ejecuta rondas de simulación multicanal sobre los 11 canales habilitados.
 */
export const runMultichannelSimulation = (simulationId, data = {}) => {
  return service.post(`/api/channels/${encodeURIComponent(simulationId)}/run`, data)
}

/**
 * Inicia encuesta estructurada estratificada (N=300 por defecto) de forma asíncrona.
 */
export const runStructuredSurvey = (simulationId, data = {}) => {
  return service.post(`/api/swarm/${encodeURIComponent(simulationId)}/survey/run`, data)
}

/**
 * Consulta el estado de una tarea asíncrona de encuesta o enjambre.
 */
export const getSwarmTaskStatus = (simulationId, taskId) => {
  return service.get(
    `/api/swarm/${encodeURIComponent(simulationId)}/tasks/${encodeURIComponent(taskId)}`
  )
}
