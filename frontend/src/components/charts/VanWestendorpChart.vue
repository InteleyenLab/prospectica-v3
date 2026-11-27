<template>
  <div class="chart-card">
    <div class="chart-header">
      <h4 class="chart-title">{{ title || 'Sensibilidad de Precios Van Westendorp (PSM)' }}</h4>
      <div v-if="markers" class="chart-badges">
        <span v-if="markers.pmc != null" class="badge">PMC: {{ formatCop(markers.pmc) }}</span>
        <span v-if="markers.opp != null" class="badge badge-accent">OPP: {{ formatCop(markers.opp) }}</span>
        <span v-if="markers.idp != null" class="badge">IDP: {{ formatCop(markers.idp) }}</span>
        <span v-if="markers.pme != null" class="badge">PME: {{ formatCop(markers.pme) }}</span>
      </div>
    </div>
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  title: { type: String, default: '' },
  spec: { type: Object, default: () => ({}) }
})

const chartEl = ref(null)
let instance = null

const markers = computed(() => props.spec?.markers || null)

const formatCop = (val) => {
  const n = Number(val)
  return Number.isFinite(n) ? `$${Math.round(n).toLocaleString('es-CO')}` : '-'
}

const buildOption = () => {
  const prices = (props.spec?.prices || []).map(Number).filter(Number.isFinite)
  const s = props.spec?.series || {}
  const clean = (arr) => (arr || []).map((v) => (Number.isFinite(Number(v)) ? Number((Number(v) * 100).toFixed(1)) : 0))

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Muy Barato', 'No Barato', 'No Caro', 'Muy Caro'], bottom: 0 },
    grid: { left: 48, right: 20, top: 20, bottom: 42 },
    xAxis: {
      type: 'category',
      data: prices.map((p) => Math.round(p).toLocaleString('es-CO')),
      axisLabel: { fontSize: 10 }
    },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      { name: 'Muy Barato', type: 'line', smooth: true, data: clean(s.too_cheap) },
      { name: 'No Barato', type: 'line', smooth: true, data: clean(s.not_cheap) },
      { name: 'No Caro', type: 'line', smooth: true, data: clean(s.not_expensive) },
      { name: 'Muy Caro', type: 'line', smooth: true, data: clean(s.too_expensive) }
    ]
  }
}

const renderChart = () => {
  if (!chartEl.value) return
  if (!instance) instance = echarts.init(chartEl.value)
  instance.setOption(buildOption(), true)
}

onMounted(renderChart)
watch(() => props.spec, renderChart, { deep: true })
onUnmounted(() => {
  if (instance) instance.dispose()
})
</script>

<style scoped>
.chart-card { background: #FFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; }
.chart-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chart-title { margin: 0; font-size: 13px; font-weight: 600; color: #0F172A; }
.chart-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.badge { font-family: 'JetBrains Mono', monospace; font-size: 10px; padding: 2px 6px; border-radius: 4px; background: #F1F5F9; color: #334155; }
.badge-accent { background: #0F172A; color: #FFF; }
.chart-canvas { width: 100%; height: 240px; }
</style>
