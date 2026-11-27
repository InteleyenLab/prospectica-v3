<template>
  <div class="survey-tab">
    <div class="survey-header">
      <span class="survey-title">Encuesta Estructurada Estratificada ({{ rows.length }} registros)</span>
      <div class="survey-actions">
        <button type="button" class="run-btn" :disabled="running" @click="triggerSurvey">
          {{ running ? 'Recolectando...' : 'Ejecutar N=300' }}
        </button>
        <button type="button" class="refresh-btn" @click="loadSurvey">Actualizar</button>
      </div>
    </div>
    <div v-if="rows.length === 0" class="survey-empty">Sin encuestas estructuradas aún.</div>
    <div v-else class="survey-table-wrap">
      <table class="survey-table">
        <thead>
          <tr><th>ID</th><th>Ciudad</th><th>Estrato</th><th>Postura</th><th>NPS</th><th>Verbatim</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows.slice(0, 25)" :key="i">
            <td class="mono">{{ r.respondent_id }}</td>
            <td>{{ r.city_name }}</td>
            <td>{{ r.stratum_code }}</td>
            <td>{{ r.attitude_segment }}</td>
            <td class="mono">{{ r.nps_score }}</td>
            <td>{{ r.verbatim_response }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { getChannelSessions, runStructuredSurvey } from '../../api/simulation'

const props = defineProps({ simulationId: { type: String, required: true } })
const rows = ref([])
const running = ref(false)

const loadSurvey = async () => {
  if (!props.simulationId) return
  try {
    const res = await getChannelSessions(props.simulationId, 'structured_survey', 200)
    rows.value = res?.data?.items || []
  } catch (e) {}
}

const triggerSurvey = async () => {
  if (!props.simulationId || running.value) return
  running.value = true
  try {
    await runStructuredSurvey(props.simulationId, { sample_size: 300, use_llm: false, sync: true })
    await loadSurvey()
  } finally {
    running.value = false
  }
}

onMounted(loadSurvey)
watch(() => props.simulationId, loadSurvey)
</script>

<style scoped>
.survey-tab { border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; background: #FFF; }
.survey-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 8px; }
.survey-title { font-weight: 700; font-size: 13px; }
.survey-actions { display: flex; gap: 6px; }
.run-btn { background: #0F172A; color: #FFF; border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.refresh-btn { border: 1px solid #CBD5E1; background: #F8FAFC; border-radius: 4px; padding: 4px 8px; font-size: 11px; cursor: pointer; }
.survey-empty { font-size: 12px; color: #64748B; }
.survey-table-wrap { max-height: 280px; overflow: auto; }
.survey-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.survey-table th, .survey-table td { border-bottom: 1px solid #E2E8F0; padding: 5px 6px; text-align: left; }
</style>
