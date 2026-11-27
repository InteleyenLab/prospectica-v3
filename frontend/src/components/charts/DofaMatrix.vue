<template>
  <div class="chart-card">
    <div class="chart-header">
      <h4 class="chart-title">{{ title || 'Matriz DOFA Cruzada (FO / FA / DO / DA)' }}</h4>
    </div>
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  title: { type: String, default: '' },
  scores: {
    type: Array,
    default: () => [
      { quadrant: 'FO (Crecer)', impacto: 85, urgencia: 80 },
      { quadrant: 'FA (Blindar)', impacto: 78, urgencia: 90 },
      { quadrant: 'DO (Optimizar)', impacto: 72, urgencia: 75 },
      { quadrant: 'DA (Mitigar)', impacto: 65, urgencia: 88 }
    ]
  }
})

const chartEl = ref(null)
let instance = null

const renderChart = () => {
  if (!chartEl.value) return
  if (!instance) instance = echarts.init(chartEl.value)
  const safeNum = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)
  const rows = props.scores || []
  instance.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Impacto Estratégico', 'Urgencia'], bottom: 0 },
    grid: { left: 48, right: 16, top: 18, bottom: 42 },
    xAxis: { type: 'category', data: rows.map((r) => r.quadrant), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', min: 0, max: 100 },
    series: [
      { name: 'Impacto Estratégico', type: 'bar', data: rows.map((r) => safeNum(r.impacto)) },
      { name: 'Urgencia', type: 'bar', data: rows.map((r) => safeNum(r.urgencia)) }
    ]
  }, true)
}

onMounted(renderChart)
watch(() => props.scores, renderChart, { deep: true })
onUnmounted(() => { if (instance) instance.dispose() })
</script>

<style scoped>
.chart-card { background: #FFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; }
.chart-header { margin-bottom: 8px; }
.chart-title { margin: 0; font-size: 13px; font-weight: 600; color: #0F172A; }
.chart-canvas { width: 100%; height: 220px; }
</style>
