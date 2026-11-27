<template>
  <div class="wa-box">
    <div class="wa-header">
      <span class="wa-title">Conversaciones WhatsApp 1-a-1 ({{ items.length }})</span>
      <button type="button" class="refresh-btn" @click="loadSessions">Actualizar</button>
    </div>
    <div v-if="items.length === 0" class="wa-empty">Sin chats de WhatsApp registrados todavía.</div>
    <div v-else class="wa-thread">
      <div v-for="(it, idx) in items.slice(0, 20)" :key="idx" class="wa-bubble">
        <div class="wa-meta">
          <strong>{{ it.actor_name }}</strong>
          <span>{{ it.city_name }} ({{ it.stratum_code }})</span>
          <span v-if="it.message_type === 'voice_note'" class="voice-chip">Nota de voz {{ it.duration_sec }}s</span>
          <span v-if="it.payment_friction_tag" class="pay-chip">{{ it.payment_friction_tag }}</span>
        </div>
        <p class="wa-text">{{ it.content_text }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { getChannelSessions } from '../../api/simulation'

const props = defineProps({ simulationId: { type: String, required: true } })
const items = ref([])

const loadSessions = async () => {
  if (!props.simulationId) return
  try {
    const res = await getChannelSessions(props.simulationId, 'whatsapp_1on1', 100)
    items.value = res?.data?.items || []
  } catch (e) {}
}

onMounted(loadSessions)
watch(() => props.simulationId, loadSessions)
</script>

<style scoped>
.wa-box { border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; background: #FFF; }
.wa-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.wa-title { font-weight: 700; font-size: 13px; }
.refresh-btn { border: 1px solid #CBD5E1; background: #F8FAFC; border-radius: 4px; padding: 3px 8px; font-size: 11px; cursor: pointer; }
.wa-empty { font-size: 12px; color: #64748B; }
.wa-thread { display: flex; flex-direction: column; gap: 8px; max-height: 300px; overflow-y: auto; }
.wa-bubble { background: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 8px; padding: 8px 10px; font-size: 12px; }
.wa-meta { display: flex; flex-wrap: wrap; gap: 6px; font-size: 10px; color: #065F46; margin-bottom: 4px; }
.voice-chip { background: #DBEAFE; color: #1E40AF; padding: 1px 5px; border-radius: 3px; }
.pay-chip { background: #FEF3C7; color: #92400E; padding: 1px 5px; border-radius: 3px; }
.wa-text { margin: 0; color: #0F172A; }
</style>
