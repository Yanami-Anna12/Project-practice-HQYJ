<script setup>
/**
 * 人工确认 —— 需求文档明确「真实商业项目必须有人工确认环节」。
 *
 * ★ 未确认前不允许下发：后端的 dispatch 接口会检查 scheduling_confirmation
 *   表里是否存在 approved=1 的记录，没有就返回 409。
 *   这里界面上也把「下发」按钮置灰，但那只是体验优化。
 *
 * ★ 下发是幂等的：task_id + plan_id + trip_id 唯一，
 *   重复点「下发」不会产生重复任务，页面会显示「跳过 N 个」。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Select, CloseBold, Promotion, View } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { taskStatus } from '@/utils/enums'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canConfirm = computed(() => auth.has('scheduling:confirm'))

const loading = ref(false)
const tasks = ref([])
const selectedTaskId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const acting = ref(false)

/** 已确认的方案 id（从任务状态推断；确认后任务变为 confirmed） */
const confirmedPlanIds = ref(new Set())

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = (await withError(() => api.fetchSchedulingTasks())) || []
    // 默认选中最近一个待确认的任务
    const pending = tasks.value.find((t) => t.status === 'pending_confirm')
    if (pending) {
      selectedTaskId.value = pending.id
      await openTask(pending.id)
    } else if (tasks.value.length) {
      selectedTaskId.value = tasks.value[0].id
      await openTask(tasks.value[0].id)
    }
  } finally {
    loading.value = false
  }
}

async function openTask(taskId) {
  detailLoading.value = true
  try {
    detail.value = await withError(() => api.fetchSchedulingTask(taskId))
  } finally {
    detailLoading.value = false
  }
}

const pendingTasks = computed(() => tasks.value.filter((t) => t.status === 'pending_confirm'))
const confirmedTasks = computed(() =>
  tasks.value.filter((t) => ['confirmed', 'dispatched', 'completed'].includes(t.status)),
)

/** 当前任务是否处于可确认状态 */
const canAct = computed(() =>
  detail.value && ['pending_confirm', 'created'].includes(detail.value.task.status),
)

/** 当前任务是否已确认（可下发） */
const isConfirmed = computed(() =>
  detail.value && ['confirmed', 'dispatched', 'completed'].includes(detail.value.task.status),
)

async function approve(plan) {
  if (!canConfirm.value) return
  acting.value = true
  const { ok } = await tryAction(
    () =>
      api.confirmPlan(detail.value.task.id, {
        plan_id: plan.id,
        approved: true,
        remark: `确认方案 ${plan.plan_code}`,
      }),
    null,
  )
  acting.value = false
  if (!ok) return
  ElMessage.success(`已确认方案 ${plan.plan_code}（${plan.strategy}），现在可以下发`)
  await loadTasks()
}

async function reject(plan) {
  if (!canConfirm.value) return
  acting.value = true
  const { ok } = await tryAction(
    () =>
      api.confirmPlan(detail.value.task.id, {
        plan_id: plan.id,
        approved: false,
        remark: '驳回，需重新生成方案',
      }),
    null,
  )
  acting.value = false
  if (!ok) return
  ElMessage.warning(`已驳回方案 ${plan.plan_code}`)
  await loadTasks()
}

async function dispatch(plan) {
  if (!canConfirm.value) return
  acting.value = true
  const { ok, result } = await tryAction(
    () => api.dispatchPlan(detail.value.task.id, plan.id),
    null,
  )
  acting.value = false
  if (!ok) return

  if (result.dispatched_trips === 0 && result.skipped_duplicated > 0) {
    ElMessage.info(`幂等生效：${result.skipped_duplicated} 个趟次此前已下发，本次未新增`)
  } else {
    ElMessage.success(result.message)
  }
  await loadTasks()
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

const tripCount = computed(() => {
  const set = new Set(details.value.map((d) => `${d.plate_no}#${d.trip_no}`))
  return set.size
})

onMounted(loadTasks)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">人工确认</h2>
        <p class="page-desc">
          方案必须经人工确认后才能下发。<strong>未确认前下发会被后端拒绝（409）</strong>；
          下发是幂等的，重复下发不会产生重复任务。
          需要 <code class="perm-code">scheduling:confirm</code>。
        </p>
      </div>
      <el-button :icon="Refresh" @click="loadTasks">刷新</el-button>
    </div>

    <el-row :gutter="16">
      <!-- 左：任务列表 -->
      <el-col :xs="24" :lg="7">
        <el-card v-loading="loading" shadow="never">
          <template #header>
            <span class="card-title">
              待确认任务
              <el-tag v-if="pendingTasks.length" type="warning" size="small" class="ml">
                {{ pendingTasks.length }}
              </el-tag>
            </span>
          </template>

          <div v-if="!tasks.length" class="empty-tip">暂无调度任务</div>

          <div v-else class="task-list">
            <div
              v-for="t in tasks"
              :key="t.id"
              class="task-item"
              :class="{ active: t.id === selectedTaskId }"
              @click="((selectedTaskId = t.id), openTask(t.id))"
            >
              <div class="task-row">
                <span class="perm-code">{{ t.code }}</span>
                <el-tag :type="taskStatus(t.status).type" size="small">
                  {{ taskStatus(t.status).text }}
                </el-tag>
              </div>
              <div class="task-meta">
                {{ t.schedule_date }} · {{ t.time_window }} · {{ t.duration_ms }}ms
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右：方案与操作 -->
      <el-col :xs="24" :lg="17">
        <el-card v-loading="detailLoading" shadow="never">
          <template #header>
            <div class="card-head">
              <span class="card-title">
                方案确认
                <template v-if="detail">
                  · {{ detail.task.code }}
                  <el-tag :type="taskStatus(detail.task.status).type" size="small" class="ml">
                    {{ taskStatus(detail.task.status).text }}
                  </el-tag>
                </template>
              </span>
              <span v-if="detail" class="muted">
                规则版本 {{ detail.task.rule_version }}
              </span>
            </div>
          </template>

          <el-empty v-if="!detail" description="请从左侧选择一个调度任务" />

          <template v-else>
            <el-alert v-if="canAct" type="warning" :closable="false" class="mb">
              <template #title>
                该任务尚未确认。<strong>必须先确认一个方案</strong>，之后才能下发执行。
              </template>
            </el-alert>
            <el-alert
              v-else-if="isConfirmed"
              type="success"
              :closable="false"
              class="mb"
            >
              <template #title>
                方案已确认，可执行下发。重复下发会被幂等拦截（不会产生重复任务）。
              </template>
            </el-alert>

            <el-table :data="detail.plans" stripe>
              <el-table-column label="方案" width="80">
                <template #default="{ row }">
                  <el-tag v-if="row.is_recommended" type="success" size="small">
                    ★ {{ row.plan_code }}
                  </el-tag>
                  <el-tag v-else size="small" effect="plain">{{ row.plan_code }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="strategy" label="策略" width="170" />
              <el-table-column label="趟次 / 用车" width="110" align="center">
                <template #default="{ row }">{{ row.trip_count }} / {{ row.vehicle_count }}</template>
              </el-table-column>
              <el-table-column label="四米二" width="90" align="right">
                <template #default="{ row }">{{ Number(row.four_two_usage).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column label="装载率" width="90" align="right">
                <template #default="{ row }">{{ Number(row.avg_load_rate).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column label="评分" width="90" align="right">
                <template #default="{ row }">
                  <span class="score">{{ Number(row.score).toFixed(1) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="230" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" link :icon="View" @click="openDetails(row)">
                    明细
                  </el-button>
                  <el-button
                    v-if="canConfirm && canAct"
                    size="small"
                    type="primary"
                    link
                    :icon="Select"
                    :loading="acting"
                    @click="approve(row)"
                  >
                    确认
                  </el-button>
                  <el-button
                    v-if="canConfirm && canAct"
                    size="small"
                    type="danger"
                    link
                    :icon="CloseBold"
                    :loading="acting"
                    @click="reject(row)"
                  >
                    驳回
                  </el-button>
                  <el-button
                    v-if="canConfirm && isConfirmed"
                    size="small"
                    type="success"
                    link
                    :icon="Promotion"
                    :loading="acting"
                    @click="dispatch(row)"
                  >
                    下发
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <div v-if="detail.plans.find((p) => p.is_recommended)" class="explain">
              <div class="explain-title">推荐方案解释</div>
              <pre class="explain-body">{{ detail.plans.find((p) => p.is_recommended).explanation }}</pre>
            </div>
          </template>
        </el-card>
      </el-col>
    </el-row>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        验证要点：先点「确认」再点「下发」；连续点两次「下发」，
        第二次会提示「幂等生效，N 个趟次此前已下发」。
        若先点「下发」（未确认），后端返回 409 并说明原因。
      </template>
    </el-alert>

    <el-dialog
      v-model="detailsVisible"
      :title="`方案 ${currentPlan?.plan_code} 明细（${tripCount} 个趟次）`"
      width="820px"
      top="8vh"
    >
      <el-table v-loading="detailsLoading" :data="details" stripe max-height="500">
        <el-table-column prop="plate_no" label="车辆" width="100">
          <template #default="{ row }">
            <span class="perm-code">{{ row.plate_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="趟次" width="80" align="center">
          <template #default="{ row }">第 {{ row.trip_no }} 趟</template>
        </el-table-column>
        <el-table-column prop="time_window" label="时段" width="70" align="center" />
        <el-table-column prop="store_code" label="门店" width="80">
          <template #default="{ row }">
            <span class="perm-code">{{ row.store_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="store_name" label="门店名称" min-width="140" />
        <el-table-column label="配送量" width="90" align="right">
          <template #default="{ row }">{{ row.load_amount.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100" />
      </el-table>
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
}

.mb {
  margin-bottom: 16px;
}

.ml {
  margin-left: 6px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 560px;
  overflow-y: auto;
}

.task-item {
  padding: 10px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.task-item:hover {
  border-color: #409eff;
  background: #ecf5ff;
}

.task-item.active {
  border-color: #409eff;
  background: #ecf5ff;
}

.task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.task-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
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
  max-height: 220px;
  overflow: auto;
}

.empty-tip {
  padding: 24px;
  text-align: center;
  color: #909399;
}
</style>
