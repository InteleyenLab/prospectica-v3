<template>
  <div class="chart-card">
    <div class="chart-header">
      <h4 class="chart-title">{{ title || 'Demanda e Ingreso Esperado (Gabor-Granger)' }}</h4>
      <span v-if="optimalPrice" class="badge-opt">Óptimo P*: {{ formatCop(optimalPrice) }}</span>
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

const optimalPrice = computed(() => {
  const n = Number(props.spec?.optimal_price)
  return Number.isFinite(n) && n > 0 ? n : null
})

const formatCop = (val) => `$${Math.round(Number(val)).toLocaleString('es-CO')} COP`

const renderChart = () => {
  if (!chartEl.value) return
  if (!instance) instance = echarts.init(chartEl.value)
  const pts = props.spec?.points || []
  const labels = pts.map((p) => Math.round(Number(p.price || 0)).toLocaleString('es-CO'))
  const demands = pts.map((p) => Number(((Number(p.demand_monotonic ?? p.demand_raw ?? 0)) * 100).toFixed(1)))
  const revenues = pts.map((p) => Math.round(Number(p.expected_revenue || 0)))

  instance.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Demanda (%)', 'Ingreso Esperado'], bottom: 0 },
    grid: { left: 48, right: 56, top: 20, bottom: 42 },
    xAxis: { type: 'category', data: labels, axisLabel: { fontSize: 10 } },
    yAxis: [
      { type: 'value', name: 'Demanda %', min: 0, max: 100 },
      { type: 'value', name: 'Ingreso', min: 0 }
    ],
    series: [
      { name: 'Demanda (%)', type: 'line', smooth: true, data: demands },
      { name: 'Ingreso Esperado', type: 'bar', yAxisIndex: 1, data: revenues, itemStyle: { opacity: 0.65 } }
    ]
  }, true)
}

onMounted(renderChart)
watch(() => props.spec, renderChart, { deep: true })
onUnmounted(() => { if (instance) instance.dispose() })
</script>

<style scoped>
.chart-card { background: #FFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; }
.chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.chart-title { margin: 0; font-size: 13px; font-weight: 600; color: #0F172A; }
.badge-opt { font-family: 'JetBrains Mono', monospace; font-size: 10px; background: #0F172A; color: #FFF; padding: 2px 8px; border-radius: 4px; }
.chart-canvas { width: 100%; height: 240px; }
</style>
