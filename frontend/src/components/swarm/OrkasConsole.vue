<template>
  <div class="orkas-console">
    <div class="orkas-header">
      <div>
        <span class="orkas-title">Consola Orkas · Enjambre Persistente</span>
        <span class="orkas-meta">Destinatario activo: <strong>{{ activeRecipient }}</strong></span>
      </div>
      <span v-if="sessionId" class="orkas-sid mono">{{ sessionId }}</span>
    </div>

    <div v-if="knownAgents.length > 0" class="mentions-bar">
      <span class="mentions-label">Mencionar @:</span>
      <button
        v-for="name in knownAgents.slice(0, 6)"
        :key="name"
        type="button"
        class="mention-chip"
        @click="appendMention(name)"
      >
        @{{ name }}
      </button>
    </div>

    <div class="orkas-messages">
      <div v-for="(msg, idx) in messages" :key="msg.message_id || idx" class="orkas-msg" :class="msg.from_kind">
        <div class="msg-head">
          <strong>{{ msg.sender_name }}</strong>
          <span class="msg-kind">{{ msg.from_kind }}</span>
        </div>
        <div class="msg-body">{{ msg.content }}</div>
      </div>
      <div v-if="messages.length === 0" class="orkas-empty">
        Envía una pregunta amplia para que ModeratorCommander coordine el enjambre, o usa @Agente para conversar directamente (persiste tras recargas).
      </div>
    </div>

    <div class="orkas-input-row">
      <input
        v-model="draft"
        type="text"
        class="orkas-input"
        placeholder="Ej. ¿Por qué dudan en pagar $70.000? o @Ciudadano ..."
        @keyup.enter="handleSend"
      />
      <button type="button" class="orkas-send-btn" :disabled="sending || !draft.trim()" @click="handleSend">
        {{ sending ? 'Enviando...' : 'Enviar' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { createSwarmSession, getSwarmSessions, sendSwarmMessage } from '../../api/report'

const props = defineProps({
  simulationId: { type: String, required: true }
})

const sessionId = ref('')
const activeRecipient = ref('ModeratorCommander')
const knownAgents = ref([])
const messages = ref([])
const draft = ref('')
const sending = ref(false)

const initSession = async () => {
  if (!props.simulationId) return
  try {
    const listRes = await getSwarmSessions(props.simulationId)
    const existing = listRes?.data?.sessions?.[0]?.session_id || null
    const res = await createSwarmSession(props.simulationId, { session_id: existing })
    if (res?.success && res.data) {
      sessionId.value = res.data.session?.session_id || ''
      activeRecipient.value = res.data.session?.active_recipient || 'ModeratorCommander'
      knownAgents.value = res.data.rehydration?.known_agents || res.data.session?.known_agents || []
      messages.value = res.data.messages || []
    }
  } catch (err) {
    // Mantiene estado limpio si aún no se ha creado sesión
  }
}

const appendMention = (name) => {
  draft.value = `${draft.value ? draft.value + ' ' : ''}@${name} `
}

const handleSend = async () => {
  const text = draft.value.trim()
  if (!text || sending.value || !props.simulationId) return
  sending.value = true
  draft.value = ''
  messages.value.push({ from_kind: 'human', sender_name: 'Usuario', content: text })
  try {
    const res = await sendSwarmMessage(props.simulationId, {
      session_id: sessionId.value || undefined,
      message: text
    })
    if (res?.success && res.data) {
      if (res.data.session?.session_id) sessionId.value = res.data.session.session_id
      if (res.data.session?.active_recipient) activeRecipient.value = res.data.session.active_recipient
      ;(res.data.replies || []).forEach((r) => messages.value.push(r))
    }
  } finally {
    sending.value = false
  }
}

onMounted(initSession)
watch(() => props.simulationId, initSession)
</script>

<style scoped>
.orkas-console { display: flex; flex-direction: column; gap: 10px; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; background: #FFF; }
.orkas-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.orkas-title { font-weight: 700; font-size: 13px; margin-right: 10px; }
.orkas-meta { font-size: 12px; color: #475569; }
.orkas-sid { font-size: 10px; color: #64748B; }
.mentions-bar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.mentions-label { font-size: 11px; color: #64748B; }
.mention-chip { border: 1px solid #CBD5E1; background: #F8FAFC; border-radius: 4px; padding: 2px 6px; font-size: 11px; cursor: pointer; }
.orkas-messages { max-height: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 8px; background: #F8FAFC; border-radius: 6px; }
.orkas-msg { padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.45; }
.orkas-msg.human { background: #0F172A; color: #FFF; align-self: flex-end; max-width: 85%; }
.orkas-msg.commander, .orkas-msg.agent { background: #FFF; border: 1px solid #E2E8F0; max-width: 92%; }
.msg-head { display: flex; gap: 8px; font-size: 10px; opacity: 0.75; margin-bottom: 3px; }
.orkas-empty { font-size: 12px; color: #64748B; text-align: center; padding: 16px; }
.orkas-input-row { display: flex; gap: 8px; }
.orkas-input { flex: 1; border: 1px solid #CBD5E1; border-radius: 6px; padding: 8px 10px; font-size: 12px; }
.orkas-send-btn { background: #0F172A; color: #FFF; border: none; border-radius: 6px; padding: 8px 14px; font-size: 12px; cursor: pointer; }
.orkas-send-btn:disabled { background: #94A3B8; cursor: not-allowed; }
</style>
