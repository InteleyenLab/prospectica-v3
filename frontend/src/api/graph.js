import service from './index'

/**
 * （）
 * @param {Object} data - files, simulation_requirement, project_name
 * @returns {Promise}
 */
export function generateOntology(formData) {
  return service({
    url: '/api/graph/ontology/generate',
    method: 'post',
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

/**
 * 
 * @param {Object} data - project_id, graph_name
 * @returns {Promise}
 */
export function buildGraph(data) {
  return service({
    url: '/api/graph/build',
    method: 'post',
    data
  })
}

/**
 * 
 * @param {String} taskId - ID
 * @returns {Promise}
 */
export function getTaskStatus(taskId) {
  return service({
    url: `/api/graph/task/${taskId}`,
    method: 'get'
  })
}

/**
 * 
 * @param {String} graphId - ID
 * @returns {Promise}
 */
export function getGraphData(graphId) {
  return service({
    url: `/api/graph/data/${graphId}`,
    method: 'get'
  })
}

/**
 * 
 * @param {String} projectId - ID
 * @returns {Promise}
 */
export function getProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'get'
  })
}

/**
 * Lista los paquetes territoriales de país disponibles.
 * @returns {Promise}
 */
export function getCountryPacks() {
  return service({
    url: '/api/country-packs',
    method: 'get'
  })
}

/**
 * Obtiene el detalle completo de un paquete de país.
 * @param {String} iso2
 * @returns {Promise}
 */
export function getCountryPack(iso2 = 'co') {
  return service({
    url: `/api/country-packs/${iso2}`,
    method: 'get'
  })
}

/**
 * Lista las ciudades oficiales registradas para un país.
 * @param {String} iso2
 * @returns {Promise}
 */
export function getCountryCities(iso2 = 'co') {
  return service({
    url: `/api/country-packs/${iso2}/cities`,
    method: 'get'
  })
}
