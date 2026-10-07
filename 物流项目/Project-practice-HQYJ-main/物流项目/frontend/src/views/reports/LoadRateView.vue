<script setup>
/**
 * 装载率分析（需求文档 二.5）。
 *
 * ★ 两个指标容易混：
 *   · 装载率 = 实际装载量 ÷ 最高装载量，看「车装得满不满」
 *   · 四米二使用率 = 四米二趟次 ÷ 总趟次，看「车型结构是否符合优先四米二」
 *   需求要求「多种派车方案优先用四米二」，后者就是它的度量。
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
    data.value = await withError(() => api.fetchLoadRateReport(scheduleDate.value || undefined))
  } finally {
    loading.value = false
  }
}

const rows = computed(() => data.value?.by_type || [])
const buckets = computed(() => data.value?.buckets || [])

/** 装载率分布柱状图 */
const distOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 50, right: 20, top: 30, bottom: 30 },
  xAxis: { type: 'category', data: buckets.value.map((b) => b.label) },
  yAxis: { type: 'value', name: '趟次' },
  series: [
    {
      type: 'bar',
      data: buckets.value.map((b) => b.count),
      itemStyle: {
        // 越接近 100% 越绿，装不满的区间偏黄
        color: (p) => ['#e6a23c', '#f0c78a', '#95d475', '#67c23a'][p.dataIndex] || '#409eff',
      },
      label: { show: true, position: 'top' },
      barMaxWidth: 70,
    },
  ],
}))

/** 各车型平均装载率 */
const typeOption = computed(() => {
  const r = rows.value
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 30, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: r.map((x) => x.name) },
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [
      {
        name: '平均装载率',
        type: 'bar',
        data: r.map((x) => x.avg_rate),
        itemStyle: { color: '#409eff' },
        label: { show: true, position: 'top', formatter: '{c}%' },
        barMaxWidth: 70,
        markLine: {
          silent: true,
          data: [{ yAxis: 95, name: '95% 目标' }],
          lineStyle: { color: '#67c23a', type: 'dashed' },
          label: { formatter: '95% 目标线' },
        },
      },
    ],
  }
})

onMounted(async () => {
  await loadDates()
  await load()
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">装载率分析</h2>
        <p class="page-desc">
          装载率反映车辆装得满不满；四米二使用率反映车型结构是否符合
          <strong>优先用四米二</strong>的要求。两者要一起看。
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
          <div class="stat-label">平均装载率</div>
          <div class="stat-value" :class="data.avg_load_rate >= 90 ? 'ok' : 'warn'">
            {{ data.avg_load_rate }}%
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">最低 / 最高</div>
          <div class="stat-value small">
            {{ data.min_load_rate }}% ~ {{ data.max_load_rate }}%
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">四米二使用率</div>
          <div class="stat-value">{{ data.four_two_usage }}%</div>
          <div class="stat-note">需求要求优先用四米二</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">统计趟次</div>
          <div class="stat-value">{{ data.trip_count }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mb">
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">装载率分布</span>
          </template>
          <EChart :option="distOption" height="300px" />
          <div class="chart-note">
            绝大部分趟次落在 95–100% 区间说明装车很满；
            大量趟次落在 &lt;70% 则说明存在半空车，可考虑合并趟次。
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">各车型平均装载率</span>
          </template>
          <EChart :option="typeOption" height="300px" />
          <div class="chart-note">
            小包最高装载量只有 300，装载率天然更容易接近上限；
            四米二区间大（630-800），要关注是否长期低位。
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <span class="card-title">按车型明细</span>
      </template>
      <el-table :data="rows" stripe>
        <el-table-column prop="name" label="车型" width="110" />
        <el-table-column prop="trips" label="趟次" width="90" align="center" />
        <el-table-column label="平均装载率" min-width="220">
          <template #default="{ row }">
            <el-progress
              :percentage="row.avg_rate"
              :stroke-width="14"
              :color="row.avg_rate >= 90 ? '#67c23a' : '#e6a23c'"
              :format="() => `${row.avg_rate.toFixed(1)}%`"
            />
          </template>
        </el-table-column>
        <el-table-column label="装载量上限" width="110" align="center">
          <template #default="{ row }">
            <span class="perm-code">{{ row.max_load }}</span>
          </template>
        </el-table-column>
        <el-table-column label="配送货量" width="120" align="right">
          <template #default="{ row }">{{ row.total_load.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="趟次占比" width="110" align="right">
          <template #default="{ row }">{{ row.trip_share.toFixed(1) }}%</template>
        </el-table-column>
      </el-table>
    </el-card>
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

.stat-value.small {
  font-size: 17px;
  padding: 5px 0;
}

.stat-note {
  font-size: 11px;
  color: #c0c4cc;
}

.chart-note {
  margin-top: 8px;
  font-size: 11px;
  color: #909399;
  line-height: 1.7;
}
</style>
