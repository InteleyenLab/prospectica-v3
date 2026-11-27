<template>
  <div class="chart-card">
    <div class="chart-header">
      <h4 class="chart-title">{{ title || 'Embudo de Conversión 5 Etapas' }}</h4>
    </div>
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  title: { type: String, default: '' },
  spec: { type: Object, default: () => ({}) }
})

const chartEl = ref(null)
let instance = null

const renderChart = () => {
  if (!chartEl.value) return
  if (!instance) instance = echarts.init(chartEl.value)
  const safeNum = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)
  const stages = props.spec?.stages || []
  const data = stages.map((s) => ({
    name: `${s.stage} (${safeNum(s.share_of_total_pct)}%)`,
    value: safeNum(s.count)
  }))

  instance.setOption({
    tooltip: { trigger: 'item' },
    series: [
      {
        name: 'Embudo',
        type: 'funnel',
        left: '10%',
        top: 16,
        bottom: 16,
        width: '80%',
        sort: 'descending',
        label: { show: true, position: 'inside', fontSize: 11 },
        data
      }
    ]
  }, true)
}

onMounted(renderChart)
watch(() => props.spec, renderChart, { deep: true })
onUnmounted(() => { if (instance) instance.dispose() })
</script>

<style scoped>
.chart-card { background: #FFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; }
.chart-header { margin-bottom: 8px; }
.chart-title { margin: 0; font-size: 13px; font-weight: 600; color: #0F172A; }
.chart-canvas { width: 100%; height: 220px; }
</style>
