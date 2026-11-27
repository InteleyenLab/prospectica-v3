<template>
  <div class="room-box">
    <div class="room-header">
      <span class="room-title">Sala de Focus Group ({{ turns.length }} intervenciones)</span>
      <button type="button" class="refresh-btn" @click="loadTurns">Actualizar</button>
    </div>
    <div v-if="turns.length === 0" class="room-empty">Sin turnos registrados en focus_group todavía.</div>
    <div v-else class="turns-list">
      <div v-for="(t, i) in turns.slice(0, 20)" :key="i" class="turn-card">
        <div class="turn-meta">
          <strong>{{ t.actor_name }}</strong>
          <span>{{ t.city_name }} · {{ t.stratum_code }} · {{ t.region_macro }}</span>
          <span v-if="t.objection_tag" class="obj-tag">{{ t.objection_tag }}</span>
        </div>
        <p class="turn-text">{{ t.content_text }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { getChannelSessions } from '../../api/simulation'

const props = defineProps({ simulationId: { type: String, required: true } })
const turns = ref([])

const loadTurns = async () => {
  if (!props.simulationId) return
  try {
    const res = await getChannelSessions(props.simulationId, 'focus_group', 100)
    turns.value = res?.data?.items || []
  } catch (e) {}
}

onMounted(loadTurns)
watch(() => props.simulationId, loadTurns)
</script>

<style scoped>
.room-box { border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; background: #FFF; }
.room-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.room-title { font-weight: 700; font-size: 13px; }
.refresh-btn { border: 1px solid #CBD5E1; background: #F8FAFC; border-radius: 4px; padding: 3px 8px; font-size: 11px; cursor: pointer; }
.room-empty { font-size: 12px; color: #64748B; }
.turns-list { display: flex; flex-direction: column; gap: 8px; max-height: 300px; overflow-y: auto; }
.turn-card { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px; font-size: 12px; }
.turn-meta { display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; color: #475569; margin-bottom: 4px; }
.obj-tag { background: #FEE2E2; color: #991B1B; padding: 1px 5px; border-radius: 3px; font-size: 10px; }
.turn-text { margin: 0; color: #0F172A; }
</style>
