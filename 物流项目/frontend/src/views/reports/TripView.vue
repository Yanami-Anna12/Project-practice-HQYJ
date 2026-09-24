<script setup>
/**
 * 趟次达成看板（需求文档 二.5）。
 *
 * ★ 两个达成率口径不同，容易混淆，页面上分开显示：
 *   · 趟次达成率 = 实际趟次 ÷ 计划趟次（计划趟次 = 计划保有量 × 每车日趟次）
 *   · 大包/小包保障达成 = 这两类车的实际趟次 ÷ 计划趟次
 *     需求要求「货量不足时优先保障大包、小包的日出车次数」，
 *     所以这是重点看的指标。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import EChart from '@/components/EChart.vue'
import { useReportDate } from '@/utils/reportDate'

const { scheduleDate, dates, loadDates } = useReportDate()

const loading = ref(false)
const data = ref(null)

async function load() {
  loading.value = true
  try {
    data.value = await withError(() => api.fetchTripReport(scheduleDate.value || undefined))
  } finally {
    loading.value = false
  }
}

const rows = computed(() => data.value?.by_type || [])

/** 柱状图：计划趟次 vs 实际趟次 */
const chartOption = computed(() => {
  const r = rows.value
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['计划趟次', '实际趟次'] },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: r.map((x) => x.name) },
    yAxis: { type: 'value', name: '趟' },
    series: [
      {
        name: '计划趟次',
        type: 'bar',
        data: r.map((x) => x.planned_trips),
        itemStyle: { color: '#c0c4cc' },
      },
      {
        name: '实际趟次',
        type: 'bar',
        data: r.map((x) => x.actual_trips),
        itemStyle: { color: '#409eff' },
        label: { show: true, position: 'top' },
      },
    ],
  }
})

/** 各车型实际趟次占比（环形图） */
const pieOption = computed(() => {
  const r = rows.value.filter((x) => x.actual_trips > 0)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 趟 ({d}%)' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '44%'],
        data: r.map((x) => ({ name: x.name, value: x.actual_trips })),
        label: { formatter: '{b}\n{c} 趟' },
      },
    ],
  }
})

const small = computed(() => data.value?.small_package || {})

onMounted(async () => {
  await loadDates()
  await load()
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">趟次达成</h2>
        <p class="page-desc">
          对比计划趟次与实际趟次，并单独看<strong>大包/小包保障达成</strong>
          —— 需求要求货量不足时优先保障它们的日出车次数。
        </p>
      </div>
      <div class="actions">
        <el-select
          v-model="scheduleDate"
          placeholder="全部日期"
          clearable
          style="width: 160px"
          @change="load"
        >
          <el-option v-for="d in dates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-row v-if="data" :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">实际趟次</div>
          <div class="stat-value">{{ data.total_trips }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">计划趟次</div>
          <div class="stat-value muted-value">{{ data.planned_trips }}</div>
          <div class="stat-note">Σ(计划保有量 × 日趟次)</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">趟次达成率</div>
          <div class="stat-value">{{ data.achievement_rate }}%</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">大包小包保障达成</div>
          <div
            class="stat-value"
            :class="small.achievement_rate >= 100 ? 'ok' : 'warn'"
          >
            {{ small.achievement_rate }}%
          </div>
          <div class="stat-note">{{ small.actual_trips }} / {{ small.planned_trips }} 趟</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mb">
      <el-col :xs="24" :lg="14">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">计划 vs 实际趟次</span>
          </template>
          <EChart :option="chartOption" height="300px" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">实际趟次构成</span>
          </template>
          <EChart :option="pieOption" height="300px" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <span class="card-title">按车型明细</span>
      </template>
      <el-table :data="rows" stripe>
        <el-table-column prop="name" label="车型" width="110" />
        <el-table-column prop="planned_trips" label="计划趟次" width="110" align="center" />
        <el-table-column prop="actual_trips" label="实际趟次" width="110" align="center">
          <template #default="{ row }">
            <span class="qty">{{ row.actual_trips }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="vehicles_used" label="用车数" width="100" align="center" />
        <el-table-column label="配送货量" width="120" align="right">
          <template #default="{ row }">{{ row.total_load.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="达成率" min-width="220">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.min(100, row.achievement_rate)"
              :stroke-width="14"
              :color="row.achievement_rate >= 100 ? '#67c23a' : '#e6a23c'"
              :format="() => `${row.achievement_rate.toFixed(1)}%`"
            />
          </template>
        </el-table-column>
        <el-table-column label="装载量区间" width="130">
          <template #default="{ row }">
            <span class="perm-code">{{ row.min_load }}–{{ row.max_load }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        达成率不必是 100%。「不保障满勤」是明确的需求，所以实际趟次通常低于计划趟次；
        真正要盯的是<strong>大包/小包保障达成</strong> —— 它反映货量不足时是否优先保住了这两类车的出车。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.card-title {
  font-weight: 600;
}

.mb {
  margin-bottom: 16px;
}

.h-full {
  height: 100%;
}

.stat {
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
}

.stat-value.ok {
  color: #67c23a;
}

.stat-value.warn {
  color: #e6a23c;
}

.stat-value.muted-value {
  color: #909399;
}

.stat-note {
  font-size: 11px;
  color: #c0c4cc;
}

.qty {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-weight: 600;
}
</style>
