<template>
  <div class="chart-card">
    <div class="chart-header">
      <h4 class="chart-title">{{ title || 'Distribución Temática / Proyección' }}</h4>
    </div>
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  title: { type: String, default: '' },
  items: { type: Array, default: () => [] },
  mode: { type: String, default: 'bar' }
})

const chartEl = ref(null)
let instance = null

const renderChart = () => {
  if (!chartEl.value) return
  if (!instance) instance = echarts.init(chartEl.value)
  const cleanItems = (props.items || []).map((it) => ({
    name: String(it.name || it.month || '-'),
    value: Number.isFinite(Number(it.value ?? it.revenue ?? 0)) ? Number(it.value ?? it.revenue ?? 0) : 0
  }))

  instance.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 56, right: 16, top: 18, bottom: 38 },
    xAxis: { type: 'category', data: cleanItems.map((i) => i.name), axisLabel: { fontSize: 10, rotate: 15 } },
    yAxis: { type: 'value' },
    series: [
      {
        type: props.mode === 'line' ? 'line' : 'bar',
        smooth: true,
        data: cleanItems.map((i) => i.value),
        itemStyle: { color: '#0F172A' }
      }
    ]
  }, true)
}

onMounted(renderChart)
watch(() => props.items, renderChart, { deep: true })
onUnmounted(() => { if (instance) instance.dispose() })
</script>

<style scoped>
.chart-card { background: #FFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; }
.chart-header { margin-bottom: 8px; }
.chart-title { margin: 0; font-size: 13px; font-weight: 600; color: #0F172A; }
.chart-canvas { width: 100%; height: 220px; }
</style>
