<script setup>
/**
 * 调度任务 —— 智能调度 Agent 的主入口。
 *
 * ★ 本页把需求文档 四「智能调度 Agent 详细设计」的核心环节都串起来了：
 *     可行性预检 → 创建任务（跑求解器）→ 查看 A/B/C/D 多方案 → 方案明细
 *   人工确认与下发在下一页（人工确认）里做。
 *
 * ★ 求解器是「启发式 + CP-SAT 三阶段混合求解」：
 *   每套方案先跑启发式保证有解，再用 CP-SAT 按各自权重优化。
 *   CP-SAT 较慢，页面上的「超时」参数控制每套方案的求解上限。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, MagicStick, View, Document } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { taskStatus, vehicleTypeCode, timeWindow } from '@/utils/enums'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canCreate = computed(() => auth.has('scheduling:create'))

const scheduleDate = ref(toISO(new Date(Date.now() + 86400000)))
function toISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const loading = ref(false)
const tasks = ref([])
const running = ref(false)

const form = ref({
  schedule_date: scheduleDate.value,
  time_window: 'FULL',
  use_cp_sat: true,
  timeout_seconds: 5,
})

/** 当前查看的任务详情 */
const detail = ref(null)
const detailLoading = ref(false)

/** 可行性预检结果 */
const feasibility = ref(null)

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = (await withError(() => api.fetchSchedulingTasks())) || []
  } finally {
    loading.value = false
  }
}

async function checkFeasibility() {
  feasibility.value = await withError(() =>
    api.fetchFeasibility(form.value.schedule_date, form.value.time_window),
  )
  if (feasibility.value && !feasibility.value.ready) {
    ElMessage.warning('可行性预检发现问题，详见下方提示')
  }
}

async function runScheduling() {
  running.value = true
  const started = Date.now()
  const { ok, result } = await tryAction(
    () => api.createSchedulingTask({ ...form.value, schedule_date: form.value.schedule_date }),
    null,
  )
  running.value = false

  if (!ok) return
  const elapsed = ((Date.now() - started) / 1000).toFixed(1)

  if (result.task.status === 'failed') {
    ElMessage.warning(`调度未生成方案：${result.task.solver_note || '输入不足'}`)
  } else {
    ElMessage.success(
      `已生成 ${result.plans.length} 套方案，耗时 ${elapsed}s（求解器 ${result.task.duration_ms}ms）`,
    )
  }
  detail.value = result
  await loadTasks()
  await checkFeasibility()
}

async function openTask(task) {
  detailLoading.value = true
  try {
    detail.value = await withError(() => api.fetchSchedulingTask(task.id))
  } finally {
    detailLoading.value = false
  }
}

/* ---------------- 方案明细 ---------------- */
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

/** 把明细按 (车牌, 趟次) 聚合成趟次视图，更贴近调度员看的方式 */
const tripGroups = computed(() => {
  const map = {}
  for (const d of details.value) {
    const key = `${d.plate_no}#${d.trip_no}`
    if (!map[key]) {
      map[key] = {
        plate_no: d.plate_no,
        driver_name: d.driver_name,
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
const reportContent = ref('')
const reportLoading = ref(false)

async function openReport(task) {
  reportVisible.value = true
  reportLoading.value = true
  reportContent.value = ''
  try {
    const r = await withError(() => api.fetchTaskReport(task.id))
    reportContent.value = r?.content || ''
  } finally {
    reportLoading.value = false
  }
}

const statusMeta = (s) => taskStatus(s)

/**
 * 进度条的文字格式。
 *
 * ★ 这里必须是具名函数，不能写成模板里的内联箭头函数 + 反引号模板字符串：
 *   Vue 模板属性用双引号包裹，里面再放反引号会导致模板编译失败
 *   （报 "Unexpected digit after hash token"）。
 */
function pct(v) {
  return `${Number(v).toFixed(1)}%`
}

onMounted(async () => {
  await loadTasks()
  await checkFeasibility()
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">调度任务</h2>
        <p class="page-desc">
          创建调度任务会执行<strong>三阶段混合求解</strong>（启发式 → CP-SAT → 多方案），
          产出 A/B/C/D 四套方案。需要 <code class="perm-code">scheduling:create</code>。
        </p>
      </div>
      <el-button :icon="Refresh" @click="loadTasks">刷新</el-button>
    </div>

    <!-- 创建调度 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <span class="card-title">创建调度任务</span>
      </template>

      <el-row :gutter="12" align="middle">
        <el-col :xs="24" :sm="5">
          <div class="field-label">调度日期</div>
          <el-date-picker
            v-model="form.schedule_date"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
            @change="checkFeasibility"
          />
        </el-col>
        <el-col :xs="12" :sm="4">
          <div class="field-label">时段</div>
          <el-select v-model="form.time_window" style="width: 100%" @change="checkFeasibility">
            <el-option label="全天（上午+下午）" value="FULL" />
            <el-option label="仅上午" value="AM" />
            <el-option label="仅下午" value="PM" />
          </el-select>
        </el-col>
        <el-col :xs="12" :sm="4">
          <div class="field-label">求解超时（秒/方案）</div>
          <el-input-number
            v-model="form.timeout_seconds"
            :min="1"
            :max="60"
            style="width: 100%"
          />
        </el-col>
        <el-col :xs="24" :sm="5">
          <div class="field-label">CP-SAT 精确求解</div>
          <el-switch
            v-model="form.use_cp_sat"
            active-text="开启"
            inactive-text="仅启发式"
            inline-prompt
          />
        </el-col>
        <el-col :xs="24" :sm="6">
          <el-button
            v-permission="'scheduling:create'"
            type="primary"
            :icon="MagicStick"
            :loading="running"
            style="width: 100%"
            @click="runScheduling"
          >
            {{ running ? '求解中…' : '开始调度' }}
          </el-button>
        </el-col>
      </el-row>

      <!-- 可行性预检 -->
      <div v-if="feasibility" class="feasibility">
        <el-alert
          :type="feasibility.ready ? 'success' : 'warning'"
          :closable="false"
        >
          <template #title>
            <span v-if="feasibility.ready">
              可行性预检通过：{{ feasibility.store_count }} 个门店有货量，
              {{ feasibility.vehicle_count }} 台可出勤车辆，
              总货量 {{ feasibility.total_demand.toFixed(0) }}，
              总运力 {{ feasibility.total_capacity.toFixed(0) }}
            </span>
            <span v-else>
              预检发现问题：
              <ul class="problem-list">
                <li v-for="(p, i) in feasibility.problems" :key="i">{{ p }}</li>
              </ul>
            </span>
          </template>
        </el-alert>
      </div>
    </el-card>

    <!-- 预检问题（来自最近一次调度） -->
    <el-alert
      v-if="detail?.problems?.length"
      type="warning"
      :closable="false"
      class="mb"
    >
      <template #title>
        本次调度的输入问题：
        <ul class="problem-list">
          <li v-for="(p, i) in detail.problems" :key="i">{{ p }}</li>
        </ul>
      </template>
    </el-alert>

    <!-- 多方案比选 -->
    <el-card v-if="detail?.plans?.length" shadow="never" class="mb">
      <template #header>
        <div class="card-head">
          <span class="card-title">
            多方案比选 · 任务 {{ detail.task.code }}
            <el-tag :type="statusMeta(detail.task.status).type" size="small" class="ml">
              {{ statusMeta(detail.task.status).text }}
            </el-tag>
          </span>
          <span class="muted">
            求解耗时 {{ detail.task.duration_ms }}ms · 规则版本 {{ detail.task.rule_version }}
          </span>
        </div>
      </template>

      <el-table :data="detail.plans" stripe>
        <el-table-column label="方案" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_recommended" type="success" size="small">★ {{ row.plan_code }}</el-tag>
            <el-tag v-else size="small" effect="plain">{{ row.plan_code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="strategy" label="策略" width="180" />
        <el-table-column label="趟次" width="80" align="center">
          <template #default="{ row }">{{ row.trip_count }}</template>
        </el-table-column>
        <el-table-column label="用车" width="80" align="center">
          <template #default="{ row }">{{ row.vehicle_count }}</template>
        </el-table-column>
        <el-table-column label="四米二使用率" width="130">
          <template #default="{ row }">
            <el-progress :percentage="Number(row.four_two_usage)" :stroke-width="12" :format="pct" />
          </template>
        </el-table-column>
        <el-table-column label="装载率" width="130">
          <template #default="{ row }">
            <el-progress
              :percentage="Number(row.avg_load_rate)"
              :stroke-width="12"
              :color="'#67c23a'"
              :format="pct"
            />
          </template>
        </el-table-column>
        <el-table-column label="相对成本" width="100" align="center">
          <template #default="{ row }">{{ Number(row.total_cost).toFixed(1) }}</template>
        </el-table-column>
        <el-table-column label="评分" width="100" align="center">
          <template #default="{ row }">
            <span class="score">{{ Number(row.score).toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="未满足门店" width="120">
          <template #default="{ row }">
            <span v-if="row.uncovered_stores" class="muted">{{ row.uncovered_stores }}</span>
            <el-tag v-else type="success" size="small" effect="plain">无</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link :icon="View" @click="openDetails(row)">
              明细
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 推荐方案解释 -->
      <div v-if="detail.plans.find((p) => p.is_recommended)" class="explain">
        <div class="explain-title">推荐方案解释</div>
        <pre class="explain-body">{{ detail.plans.find((p) => p.is_recommended).explanation }}</pre>
      </div>
    </el-card>

    <!-- 任务列表 -->
    <el-card shadow="never">
      <template #header>
        <span class="card-title">历史调度任务（{{ tasks.length }}）</span>
      </template>
      <el-table v-loading="loading" :data="tasks" stripe>
        <el-table-column prop="code" label="任务编号" width="150">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="schedule_date" label="调度日期" width="110" />
        <el-table-column label="时段" width="70">
          <template #default="{ row }">{{ row.time_window }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" size="small">
              {{ statusMeta(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="求解耗时" width="100" align="right">
          <template #default="{ row }">{{ row.duration_ms }} ms</template>
        </el-table-column>
        <el-table-column label="重排次数" width="90" align="center">
          <template #default="{ row }">
            <span :class="{ 'replan-warn': row.replan_count > 0 }">{{ row.replan_count }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_by" label="创建人" width="100" />
        <el-table-column prop="solver_note" label="求解说明" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openTask(row)">查看</el-button>
            <el-button size="small" link :icon="Document" @click="openReport(row)">报告</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !tasks.length" description="还没有调度任务" />
    </el-card>

    <!-- 方案明细弹窗：按趟次聚合展示 -->
    <el-dialog
      v-model="detailsVisible"
      :title="`方案 ${currentPlan?.plan_code} · ${currentPlan?.strategy} 明细`"
      width="900px"
      top="6vh"
    >
      <div v-loading="detailsLoading">
        <el-alert type="info" :closable="false" class="mb">
          <template #title>
            共 {{ tripGroups.length }} 个趟次、{{ details.length }} 条配送记录。
            <strong>同一门店可能出现在多个趟次里</strong> —— 单店货量超过单车容量时需要拆单配送。
          </template>
        </el-alert>

        <el-table :data="tripGroups" stripe max-height="520">
          <el-table-column label="车辆" width="110">
            <template #default="{ row }">
              <span class="perm-code">{{ row.plate_no }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="driver_name" label="司机" width="90">
            <template #default="{ row }">
              <span v-if="row.driver_name">{{ row.driver_name }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="车型" width="90">
            <template #default="{ row }">
              <el-tag :type="vehicleTypeCode(row.vehicle_type).type" size="small">
                {{ vehicleTypeCode(row.vehicle_type).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="趟次" width="90" align="center">
            <template #default="{ row }">
              第 {{ row.trip_no }} 趟
              <el-tag
                :type="timeWindow(row.time_window).type"
                size="small"
                effect="plain"
                class="ml-sm"
              >
                {{ timeWindow(row.time_window).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="装载量" width="100" align="right">
            <template #default="{ row }">
              <span class="qty">{{ row.load.toFixed(0) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="配送门店（数量）" min-width="320">
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
      </div>
    </el-dialog>

    <!-- 调度报告 -->
    <el-dialog v-model="reportVisible" title="调度报告" width="860px" top="6vh">
      <div v-loading="reportLoading">
        <pre v-if="reportContent" class="report">{{ reportContent }}</pre>
        <el-empty v-else description="报告生成中…" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.card-title {
  font-weight: 600;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.mb {
  margin-bottom: 16px;
}

.ml {
  margin-left: 8px;
}

.ml-sm {
  margin-left: 4px;
}

.field-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.feasibility {
  margin-top: 14px;
}

.problem-list {
  margin: 4px 0 0;
  padding-left: 18px;
  line-height: 1.8;
}

.score {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-weight: 600;
}

.explain {
  margin-top: 16px;
  border-top: 1px dashed #e4e7ed;
  padding-top: 12px;
}

.explain-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
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
  max-height: 240px;
  overflow: auto;
}

.qty {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-weight: 600;
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

.replan-warn {
  color: #e6a23c;
  font-weight: 600;
}

.report {
  margin: 0;
  font-size: 12px;
  line-height: 1.8;
  white-space: pre-wrap;
  font-family: 'Cascadia Mono', Consolas, Monaco, monospace;
  max-height: 62vh;
  overflow: auto;
}
</style>
