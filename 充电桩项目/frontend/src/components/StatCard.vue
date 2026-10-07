<template>
  <a-card :bordered="false" class="stat-card" :body-style="{ padding: '16px 18px' }">
    <div class="stat-label">
      <component v-if="icon" :is="icon" style="margin-right: 5px" />{{ label }}
    </div>
    <div class="stat-value" :class="tone">
      {{ display }}<span v-if="suffix" class="stat-suffix">{{ suffix }}</span>
    </div>
    <div v-if="hint" class="stat-hint">{{ hint }}</div>
  </a-card>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: 0 },
  suffix: { type: String, default: '' },
  tone: { type: String, default: '' },
  hint: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
})

const display = computed(() => {
  if (typeof props.value === 'number') {
    return Number.isInteger(props.value) ? props.value : props.value.toFixed(1)
  }
  return props.value ?? '-'
})
</script>

<style scoped>
.stat-hint {
  font-size: 12px;
  color: #a0a6ad;
  margin-top: 6px;
}
</style>
