import service from './index'

export const submitBrief = (payload) => service.post('/api/brief', payload)

export const confirmStudyContext = (payload) => service.post('/api/study-context/confirm', payload)

export const runSecondaryResearch = (payload) => service.post('/api/research/secondary/run', payload)

export const getResearchEvidence = (projectId) =>
  service.get('/api/research/evidence', { params: { project_id: projectId } })

export const runCalibrationGate = (payload) => service.post('/api/calibration/run', payload)

export const uploadRealData = (payload) => service.post('/api/real-data/upload', payload)

export const getBacktestingDashboard = () => service.get('/api/backtesting/dashboard')
