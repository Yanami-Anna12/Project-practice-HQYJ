<script setup>
/**
 * 成本与方案对比（需求文档 二.5）。
 *
 * ★ 成本口径：演示用的**相对系数**（四米二 1.0、大包 0.85、小包 0.5），
 *   真实项目应对接财务口径。页面上明确标注了这一点，避免被当成真实金额。
 *
 * ★ 方案对比部分展示同一天所有任务的方案，用于横向比选；
 *   而成本拆解只统计**最近一次调度**的推荐方案（与其它报表口径一致）。
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
    data.value = await withError(() => api.fetchCostReport(scheduleDate.value || undefined))
  } finally {
    loading.value = false
  }
}

const costRows = computed(() => data.value?.cost_by_type || [])
const plans = computed(() => data.value?.plans || [])

/** 成本构成环形图 */
const costPie = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0 },
  series: [
    {
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '44%'],
      data: costRows.value.map((c) => ({ name: c.name, value: c.cost })),
      label: { formatter: '{b}\n{d}%' },
    },
  ],
}))

/** 方案评分对比（只取最近一次任务的方案，避免同一天多任务混在一起看不清） */
const latestPlans = computed(() => {
  if (!plans.value.length) return []
  const maxTask = Math.max(...plans.value.map((p) => p.task_id))
  return plans.value.filter((p) => p.task_id === maxTask)
})

const planOption = computed(() => {
  const p = latestPlans.value
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['综合评分', '相对成本', '装载率', '四米二使用率'] },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: p.map((x) => `${x.plan_code} ${x.strategy}`) },
    yAxis: { type: 'value' },
    series: [
      { name: '综合评分', type: 'bar', data: p.map((x) => x.score), itemStyle: { color: '#409eff' } },
      { name: '相对成本', type: 'bar', data: p.map((x) => x.total_cost), itemStyle: { color: '#e6a23c' } },
      { name: '装载率', type: 'bar', data: p.map((x) => x.avg_load_rate), itemStyle: { color: '#67c23a' } },
      { name: '四米二使用率', type: 'bar', data: p.map((x) => x.four_two_usage), itemStyle: { color: '#909399' } },
    ],
  }
})

/** 成本最低的方案 */
const cheapest = computed(() => {
  const p = latestPlans.value
  if (!p.length) return null
  return p.reduce((a, b) => (a.total_cost <= b.total_cost ? a : b))
})

/** 评分最高的方案 */
const bestScore = computed(() => {
  const p = latestPlans.value
  if (!p.length) return null
  return p.reduce((a, b) => (a.score >= b.score ? a : b))
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
        <h2 class="page-title">成本与方案对比</h2>
        <p class="page-desc">
          成本按车型相对系数折算（四米二 1.0、大包 0.85、小包 0.5），用于<strong>方案之间的相对比较</strong>，
          不是真实金额。方案对比取最近一次调度的四套候选方案。
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
          <div class="stat-label">选中方案总成本</div>
          <div class="stat-value">{{ data.total_cost }}</div>
          <div class="stat-note">相对系数折算</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">候选方案数</div>
          <div class="stat-value">{{ data.plan_count }}</div>
          <div class="stat-note">累计所有任务的方案</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card v-if="cheapest" shadow="never" class="stat">
          <div class="stat-label">成本最低方案</div>
          <div class="stat-value small ok">
            {{ cheapest.plan_code }} · {{ cheapest.total_cost }}
          </div>
          <div class="stat-note">{{ cheapest.strategy }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card v-if="bestScore" shadow="never" class="stat">
          <div class="stat-label">评分最高方案</div>
          <div class="stat-value small">
            {{ bestScore.plan_code }} · {{ bestScore.score.toFixed(1) }}
          </div>
          <div class="stat-note">{{ bestScore.strategy }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mb">
      <el-col :xs="24" :lg="9">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">成本构成（按车型）</span>
          </template>
          <EChart :option="costPie" height="300px" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="15">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">方案指标对比（最近一次调度）</span>
          </template>
          <EChart :option="planOption" height="300px" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="mb">
      <template #header>
        <span class="card-title">成本拆解</span>
      </template>
      <el-table :data="costRows" stripe>
        <el-table-column prop="name" label="车型" width="110" />
        <el-table-column label="成本系数" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" class="perm-code">{{ row.factor }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="trips" label="趟次" width="90" align="center" />
        <el-table-column label="配送货量" width="120" align="right">
          <template #default="{ row }">{{ row.load.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="成本" width="100" align="right">
          <template #default="{ row }">
            <span class="qty">{{ row.cost.toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成本占比" min-width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="row.cost_share"
              :stroke-width="14"
              :format="() => `${row.cost_share.toFixed(1)}%`"
            />
          </template>
        </el-table-column>
      </el-table>
      <div class="note">{{ data?.cost_note }}</div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <span class="card-title">候选方案横向对比</span>
      </template>
      <el-table :data="plans" stripe max-height="420">
        <el-table-column label="任务" width="80" align="center">
          <template #default="{ row }">#{{ row.task_id }}</template>
        </el-table-column>
        <el-table-column label="方案" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_recommended" type="success" size="small">
              ★ {{ row.plan_code }}
            </el-tag>
            <el-tag v-else size="small" effect="plain">{{ row.plan_code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="strategy" label="策略" width="170" />
        <el-table-column prop="trip_count" label="趟次" width="80" align="center" />
        <el-table-column prop="vehicle_count" label="用车" width="80" align="center" />
        <el-table-column label="成本" width="90" align="right">
          <template #default="{ row }">{{ row.total_cost.toFixed(1) }}</template>
        </el-table-column>
        <el-table-column label="装载率" width="90" align="right">
          <template #default="{ row }">{{ row.avg_load_rate.toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="四米二" width="90" align="right">
          <template #default="{ row }">{{ row.four_two_usage.toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="评分" width="90" align="right">
          <template #default="{ row }">
            <span class="qty">{{ row.score.toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="未满足门店" min-width="140">
          <template #default="{ row }">
            <span v-if="row.uncovered_stores" class="muted">{{ row.uncovered_stores }}</span>
            <el-tag v-else type="success" size="small" effect="plain">无</el-tag>
          </template>
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

.stat-value.small {
  font-size: 17px;
  padding: 5px 0;
}

.stat-value.ok {
  color: #67c23a;
}

.stat-note {
  font-size: 11px;
  color: #c0c4cc;
}

.qty {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-weight: 600;
}

.note {
  margin-top: 10px;
  font-size: 11px;
  color: #c0c4cc;
}
</style>
