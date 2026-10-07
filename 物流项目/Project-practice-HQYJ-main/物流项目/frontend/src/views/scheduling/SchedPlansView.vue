<script setup>
/**
 * 多方案比选 —— 把最近一次调度的 A/B/C/D 四套方案横向摊开对比。
 *
 * ★ 这是「多方案比选」需求的直接落地：四套方案由不同的权重驱动
 *   （A 四米二优先 / B 成本最低 / C 大包小包保障 / D 装载率均衡），
 *   各自的指标差异一目了然，调度员据此挑选而非盲选。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh, View, Document } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import { taskStatus, vehicleTypeCode, timeWindow } from '@/utils/enums'

const loading = ref(false)
const tasks = ref([])
const selectedTaskId = ref(null)
const detail = ref(null)

async function load() {
  loading.value = true
  try {
    tasks.value = (await withError(() => api.fetchSchedulingTasks())) || []
    const withPlans = tasks.value.find((t) => t.status !== 'failed')
    selectedTaskId.value = withPlans?.id || tasks.value[0]?.id || null
    if (selectedTaskId.value) await loadDetail()
  } finally {
    loading.value = false
  }
}

async function loadDetail() {
  if (!selectedTaskId.value) return
  detail.value = await withError(() => api.fetchSchedulingTask(selectedTaskId.value))
}

const plans = computed(() => detail.value?.plans || [])

/** 找出每个指标的最优值，用于高亮 */
const best = computed(() => {
  if (!plans.value.length) return {}
  const nums = (key) => plans.value.map((p) => Number(p[key]))
  return {
    four_two_usage: Math.max(...nums('four_two_usage')),
    avg_load_rate: Math.max(...nums('avg_load_rate')),
    total_cost: Math.min(...nums('total_cost')),
    trip_count: Math.min(...nums('trip_count')),
    score: Math.max(...nums('score')),
  }
})

function isBest(key, value) {
  return best.value[key] !== undefined && Math.abs(best.value[key] - Number(value)) < 0.01
}

/** 指标对比表：把方案放在列上，指标放在行上，更便于横向看 */
const compareRows = computed(() => {
  if (!plans.value.length) return []
  const defs = [
    { key: 'strategy', label: '策略说明', raw: true },
    { key: 'trip_count', label: '趟次数', unit: '趟', better: 'min' },
    { key: 'vehicle_count', label: '用车数', unit: '台', better: 'min' },
    { key: 'total_load', label: '配送货量', unit: '', better: 'max', fixed: 0 },
    { key: 'four_two_usage', label: '四米二使用率', unit: '%', better: 'max', fixed: 1 },
    { key: 'avg_load_rate', label: '平均装载率', unit: '%', better: 'max', fixed: 1 },
    { key: 'trip_achievement', label: '趟次保障度', unit: '%', better: 'max', fixed: 1 },
    { key: 'total_cost', label: '相对成本', unit: '', better: 'min', fixed: 1 },
    { key: 'score', label: '综合评分', unit: '', better: 'max', fixed: 1 },
  ]

  return defs.map((d) => {
    const values = plans.value.map((p) => Number(p[d.key]))
    let bestValue = null
    if (!d.raw && values.length) {
      bestValue = d.better === 'min' ? Math.min(...values) : Math.max(...values)
    }
    return { ...d, values, bestValue }
  })
})

/* ---------------- 明细 ---------------- */
const detailsVisible = ref(false)
const detailsLoading = ref(false)
const details = ref([])
const currentPlan = ref(null)

async function openDetails(plan) {
  currentPlan.value = plan
  detailsVisible.value = true
  detailsLoading.value = true
  try {
    details.value = (await withError(() => api.fetchPlanDetails(plan.id))) || []
  } finally {
    detailsLoading.value = false
  }
}

const tripGroups = computed(() => {
  const map = {}
  for (const d of details.value) {
    const key = `${d.plate_no}#${d.trip_no}`
    if (!map[key]) {
      map[key] = {
        plate_no: d.plate_no,
        vehicle_type: d.vehicle_type,
        trip_no: d.trip_no,
        time_window: d.time_window,
        stores: [],
        load: 0,
      }
    }
    map[key].stores.push(d)
    map[key].load += d.load_amount
  }
  return Object.values(map).sort(
    (a, b) => a.plate_no.localeCompare(b.plate_no) || a.trip_no - b.trip_no,
  )
})

/* ---------------- 报告 ---------------- */
const reportVisible = ref(false)
const reportLoading = ref(false)
const reportContent = ref('')

async function openReport() {
  if (!selectedTaskId.value) return
  reportVisible.value = true
  reportLoading.value = true
  reportContent.value = ''
  try {
    const r = await withError(() => api.fetchTaskReport(selectedTaskId.value))
    reportContent.value = r?.content || ''
  } finally {
    reportLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">多方案比选</h2>
        <p class="page-desc">
          四套方案由不同权重驱动，指标各有取舍。
          <strong>绿色为该指标的最优值</strong>，可据此挑选方案。
        </p>
      </div>
      <div class="actions">
        <el-select
          v-model="selectedTaskId"
          placeholder="选择调度任务"
          style="width: 220px"
          @change="loadDetail"
        >
          <el-option
            v-for="t in tasks"
            :key="t.id"
            :label="`${t.code}（${t.schedule_date}）`"
            :value="t.id"
          />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button :icon="Document" @click="openReport">调度报告</el-button>
      </div>
    </div>

    <el-empty v-if="!loading && !plans.length" description="还没有可对比的方案">
      <el-button type="primary" @click="$router.push('/scheduling/tasks')">
        去创建调度
      </el-button>
    </el-empty>

    <template v-else>
      <!-- 方案卡片 -->
      <el-row :gutter="16" class="mb">
        <el-col v-for="p in plans" :key="p.id" :xs="24" :sm="12" :lg="6">
          <el-card
            shadow="never"
            class="plan-card"
            :class="{ recommended: p.is_recommended }"
          >
            <div class="plan-head">
              <div>
                <span class="plan-code">{{ p.plan_code }}</span>
                <span class="plan-strategy">{{ p.strategy }}</span>
              </div>
              <el-tag v-if="p.is_recommended" type="success" size="small">推荐</el-tag>
            </div>

            <div class="plan-metrics">
              <div class="metric">
                <div class="metric-value">{{ p.trip_count }}</div>
                <div class="metric-label">趟次</div>
              </div>
              <div class="metric">
                <div class="metric-value">{{ p.vehicle_count }}</div>
                <div class="metric-label">用车</div>
              </div>
              <div class="metric">
                <div class="metric-value">{{ Number(p.avg_load_rate).toFixed(0) }}%</div>
                <div class="metric-label">装载率</div>
              </div>
              <div class="metric">
                <div class="metric-value">{{ Number(p.total_cost).toFixed(0) }}</div>
                <div class="metric-label">成本</div>
              </div>
            </div>

            <el-progress
              :percentage="Number(p.four_two_usage)"
              :stroke-width="10"
              :format="(v) => `四米二 ${v.toFixed(0)}%`"
            />

            <div class="plan-score">
              综合评分 <strong>{{ Number(p.score).toFixed(1) }}</strong>
            </div>

            <div v-if="p.uncovered_stores" class="plan-warn">
              未满足：{{ p.uncovered_stores }}
            </div>
            <div v-else class="plan-ok">全部门店已覆盖</div>

            <el-button size="small" type="primary" link :icon="View" @click="openDetails(p)">
              查看明细
            </el-button>
          </el-card>
        </el-col>
      </el-row>

      <!-- 指标对比表 -->
      <el-card shadow="never" class="mb">
        <template #header>
          <span class="card-title">
            指标横向对比 · 任务 {{ detail?.task?.code }}
            <el-tag
              v-if="detail?.task"
              :type="taskStatus(detail.task.status).type"
              size="small"
              class="ml"
            >
              {{ taskStatus(detail.task.status).text }}
            </el-tag>
          </span>
        </template>

        <el-table :data="compareRows" border>
          <el-table-column prop="label" label="指标" width="150" fixed />
          <el-table-column
            v-for="(p, idx) in plans"
            :key="p.id"
            :label="`${p.plan_code} · ${p.strategy}`"
            min-width="170"
            align="center"
          >
            <template #default="{ row }">
              <template v-if="row.raw">
                {{ plans[idx].strategy }}
              </template>
              <template v-else>
                <span
                  :class="{
                    'best-value': row.bestValue !== null && Math.abs(row.bestValue - row.values[idx]) < 0.01,
                  }"
                >
                  {{ row.fixed !== undefined ? row.values[idx].toFixed(row.fixed) : row.values[idx] }}
                  {{ row.unit }}
                </span>
                <el-icon
                  v-if="row.bestValue !== null && Math.abs(row.bestValue - row.values[idx]) < 0.01"
                  class="best-icon"
                >
                  <Select />
                </el-icon>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <div class="legend-note">
          <el-icon color="#67c23a"><Select /></el-icon>
          标记为该指标的相对最优值。注意各指标之间存在取舍：
          用车少通常意味着装载率高，但成本与趟次保障可能相反。
        </div>
      </el-card>

      <!-- 推荐方案解释 -->
      <el-card v-if="plans.find((p) => p.is_recommended)" shadow="never">
        <template #header>
          <span class="card-title">
            推荐方案 {{ plans.find((p) => p.is_recommended).plan_code }} 解释
          </span>
        </template>
        <pre class="explain-body">{{ plans.find((p) => p.is_recommended).explanation }}</pre>
      </el-card>
    </template>

    <el-dialog
      v-model="detailsVisible"
      :title="`方案 ${currentPlan?.plan_code} 明细（${tripGroups.length} 个趟次）`"
      width="900px"
      top="6vh"
    >
      <el-table v-loading="detailsLoading" :data="tripGroups" stripe max-height="520">
        <el-table-column prop="plate_no" label="车辆" width="100">
          <template #default="{ row }">
            <span class="perm-code">{{ row.plate_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="车型" width="90">
          <template #default="{ row }">
            <el-tag :type="vehicleTypeCode(row.vehicle_type).type" size="small">
              {{ vehicleTypeCode(row.vehicle_type).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="趟次" width="120" align="center">
          <template #default="{ row }">
            第 {{ row.trip_no }} 趟
            <el-tag :type="timeWindow(row.time_window).type" size="small" effect="plain">
              {{ timeWindow(row.time_window).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="装载量" width="90" align="right">
          <template #default="{ row }">{{ row.load.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="配送门店（数量）" min-width="300">
          <template #default="{ row }">
            <div class="store-list">
              <span v-for="s in row.stores" :key="s.id" class="store-chip">
                <span class="perm-code">{{ s.store_code }}</span>
                <span class="store-qty">{{ s.load_amount.toFixed(0) }}</span>
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="reportVisible" title="调度报告" width="860px" top="6vh">
      <div v-loading="reportLoading">
        <pre v-if="reportContent" class="explain-body report">{{ reportContent }}</pre>
        <el-empty v-else description="加载中…" />
      </div>
    </el-dialog>
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

.ml {
  margin-left: 6px;
}

.plan-card {
  margin-bottom: 16px;
  border: 2px solid transparent;
}

.plan-card.recommended {
  border-color: #67c23a;
}

.plan-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 14px;
}

.plan-code {
  display: block;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.1;
}

.plan-strategy {
  font-size: 12px;
  color: #909399;
}

.plan-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin-bottom: 14px;
}

.metric {
  text-align: center;
}

.metric-value {
  font-size: 17px;
  font-weight: 600;
}

.metric-label {
  font-size: 11px;
  color: #909399;
}

.plan-score {
  margin-top: 12px;
  font-size: 12px;
  color: #606266;
}

.plan-score strong {
  font-size: 15px;
  color: #409eff;
}

.plan-warn {
  margin-top: 6px;
  font-size: 11px;
  color: #e6a23c;
  line-height: 1.5;
}

.plan-ok {
  margin-top: 6px;
  font-size: 11px;
  color: #67c23a;
}

.best-value {
  color: #67c23a;
  font-weight: 700;
}

.best-icon {
  color: #67c23a;
  margin-left: 2px;
  vertical-align: middle;
}

.legend-note {
  margin-top: 12px;
  font-size: 12px;
  color: #909399;
  line-height: 1.7;
  display: flex;
  align-items: flex-start;
  gap: 4px;
}

.explain-body {
  margin: 0;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.8;
  white-space: pre-wrap;
  font-family: 'Cascadia Mono', Consolas, Monaco, monospace;
  max-height: 300px;
  overflow: auto;
}

.report {
  max-height: 62vh;
}

.store-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.store-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  background: #f0f2f5;
  border-radius: 3px;
  font-size: 12px;
}

.store-qty {
  color: #409eff;
  font-weight: 600;
}
</style>
