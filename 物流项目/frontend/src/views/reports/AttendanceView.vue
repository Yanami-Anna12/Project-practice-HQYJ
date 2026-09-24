<script setup>
/**
 * 车辆出勤看板（需求文档 二.5）。
 *
 * ★ 口径说明：统计的是**最近一次调度**的推荐方案，不是所有任务的累加。
 *   同一天多次调度时只取最后一次 —— 否则同一批货量会被重复计算。
 *   这一点在后端 reports._selected_plans 里也有注释。
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
    data.value = await withError(() => api.fetchAttendanceReport(scheduleDate.value || undefined))
  } finally {
    loading.value = false
  }
}

const rows = computed(() => data.value?.by_type || [])

/** 柱状图：各车型计划保有量 vs 实际出车 */
const chartOption = computed(() => {
  const r = rows.value
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['计划保有量', '建档车辆', '当日可出勤', '实际出车'] },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: r.map((x) => x.name) },
    yAxis: { type: 'value', name: '台' },
    series: [
      { name: '计划保有量', type: 'bar', data: r.map((x) => x.planned_count), itemStyle: { color: '#c0c4cc' } },
      { name: '建档车辆', type: 'bar', data: r.map((x) => x.total), itemStyle: { color: '#409eff' } },
      { name: '当日可出勤', type: 'bar', data: r.map((x) => x.available), itemStyle: { color: '#67c23a' } },
      { name: '实际出车', type: 'bar', data: r.map((x) => x.used), itemStyle: { color: '#e6a23c' } },
    ],
  }
})

onMounted(async () => {
  await loadDates()
  await load()
})

async function reload() {
  await load()
}
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">车辆出勤</h2>
        <p class="page-desc">
          对比「计划保有量 / 建档车辆 / 当日可出勤 / 实际出车」。
          需求要求<strong>不保障每天 28/3/9 台满勤</strong>，可动态调节，所以出勤率低于 100% 是正常的。
        </p>
      </div>
      <div class="actions">
        <el-select
          v-model="scheduleDate"
          placeholder="全部日期"
          clearable
          style="width: 160px"
          @change="reload"
        >
          <el-option v-for="d in dates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button :icon="Refresh" @click="reload">刷新</el-button>
      </div>
    </div>

    <el-row v-if="data" :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">建档车辆</div>
          <div class="stat-value">{{ data.vehicle_total }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">当日可出勤</div>
          <div class="stat-value ok">{{ data.vehicle_available }}</div>
          <div class="stat-note">不可出勤 {{ data.vehicle_unavailable }} 台</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">实际出车</div>
          <div class="stat-value warn">{{ data.vehicle_used }}</div>
          <div class="stat-note">
            出勤率
            {{ data.vehicle_available ? ((data.vehicle_used / data.vehicle_available) * 100).toFixed(1) : 0 }}%
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">已下发趟次</div>
          <div class="stat-value">{{ data.dispatched_trips }}</div>
          <div class="stat-note">来自下发记录（幂等去重后）</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card v-loading="loading" shadow="never" class="mb">
      <template #header>
        <span class="card-title">出勤对比</span>
      </template>
      <EChart :option="chartOption" height="300px" />
    </el-card>

    <el-card shadow="never">
      <template #header>
        <span class="card-title">按车型明细</span>
      </template>
      <el-table :data="rows" stripe>
        <el-table-column prop="name" label="车型" width="110" />
        <el-table-column prop="planned_count" label="计划保有量" width="120" align="center" />
        <el-table-column prop="total" label="建档车辆" width="110" align="center" />
        <el-table-column label="当日可出勤" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.available === row.planned_count ? 'success' : 'warning'" size="small" effect="plain">
              {{ row.available }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="used" label="实际出车" width="110" align="center" />
        <el-table-column label="出勤率（vs 计划）" min-width="220">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.min(100, row.attendance_rate)"
              :stroke-width="14"
              :color="row.attendance_rate >= 100 ? '#67c23a' : '#e6a23c'"
              :format="() => `${row.attendance_rate.toFixed(1)}%`"
            />
          </template>
        </el-table-column>
        <el-table-column prop="trips_per_day" label="日趟次" width="90" align="center" />
      </el-table>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        出勤率 = 实际出车 ÷ 计划保有量。例如四米二计划 28 台，若某天只出动 6 台，
        出勤率 21.4% —— 这是「动态车辆调节」的体现，不是异常。
        后端只统计<strong>最近一次调度</strong>的推荐方案，避免同日多次调度被重复累加。
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

.stat-note {
  font-size: 11px;
  color: #c0c4cc;
}
</style>
