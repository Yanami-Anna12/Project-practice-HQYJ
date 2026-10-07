<template>
  <div ref="el" :style="{ width: '100%', height: height }" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '300px' },
  loading: { type: Boolean, default: false },
})

const el = ref(null)
let chart = null
let ro = null

function render() {
  if (!chart) return
  chart.setOption(props.option, true)
}

function resize() {
  if (chart) chart.resize()
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  if (props.loading) chart.showLoading()
  window.addEventListener('resize', resize)
  if (window.ResizeObserver) {
    ro = new ResizeObserver(resize)
    ro.observe(el.value)
  }
})

watch(() => props.option, render, { deep: true })

watch(
  () => props.loading,
  (v) => {
    if (!chart) return
    if (v) chart.showLoading()
    else chart.hideLoading()
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (ro) ro.disconnect()
  if (chart) chart.dispose()
  chart = null
})
</script>
