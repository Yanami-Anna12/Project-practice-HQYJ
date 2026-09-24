<script setup>
/**
 * 异常重排。
 *
 * ★ 需求文档的重排策略（本页逐条体现）：
 *     1. 锁定已执行趟次，不重排        → 页面显示「已锁定 N 个趟次」
 *     2. 只重排未执行、未完成部分
 *     3. 优先局部修复，失败再全局重排  → 重排范围可选「局部 / 全局」
 *     4. 记录 replan_count，避免无限循环 → 达到上限后按钮禁用、后端 409
 *
 * ★ 异常来源：车辆故障、司机缺勤、门店临时加/减货、交通管制、地形临时管控。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Warning, RefreshRight, Plus } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { taskStatus } from '@/utils/enums'

/** 异常类型选项（对应需求文档的异常来源） */
const EVENT_TYPES = [
  { value: 'vehicle_breakdown', label: '车辆故障', type: 'danger' },
  { value: 'driver_absence', label: '司机缺勤', type: 'warning' },
  { value: 'demand_change', label: '门店临时加减货', type: 'primary' },
  { value: 'traffic_control', label: '交通管制', type: 'info' },
  { value: 'terrain_control', label: '地形临时管控', type: 'warning' },
]

function eventMeta(type) {
  return EVENT_TYPES.find((e) => e.value === type) || { label: type, type: 'info' }
}

const loading = ref(false)
const tasks = ref([])
const events = ref([])
const selectedTaskId = ref(null)
const acting = ref(false)

/** 重排上限（与后端参数默认值一致；后端仍会独立校验） */
const REPLAN_LIMIT = 3

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = (await withError(() => api.fetchSchedulingTasks())) || []
    if (!selectedTaskId.value && tasks.value.length) {
      selectedTaskId.value = tasks.value[0].id
    }
    await loadEvents()
  } finally {
    loading.value = false
  }
}

async function loadEvents() {
  events.value = (await withError(() => api.fetchExceptions(selectedTaskId.value))) || []
}

const selectedTask = computed(() =>
  tasks.value.find((t) => t.id === selectedTaskId.value),
)

/** 重排次数是否已达上限 */
const replanExhausted = computed(
  () => (selectedTask.value?.replan_count || 0) >= REPLAN_LIMIT,
)

/* ---------------- 上报异常 ---------------- */
const dialogVisible = ref(false)
const submitting = ref(false)
const form = ref({ event_type: 'vehicle_breakdown', source: '', detail: '' })

function openReport() {
  if (!selectedTaskId.value) {
    ElMessage.warning('请先选择一个调度任务')
    return
  }
  form.value = { event_type: 'vehicle_breakdown', source: '', detail: '' }
  dialogVisible.value = true
}

async function submitEvent() {
  submitting.value = true
  const { ok } = await tryAction(
    () =>
      api.createException({
        task_id: selectedTaskId.value,
        event_type: form.value.event_type,
        source: form.value.source || '调度员',
        payload: { detail: form.value.detail },
      }),
    '异常已上报',
  )
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  await loadEvents()
}

/* ---------------- 重排 ---------------- */
const replanScope = ref('local')

async function doReplan(eventId = null) {
  if (replanExhausted.value) {
    ElMessage.warning(`该任务重排次数已达上限 ${REPLAN_LIMIT}，需人工介入`)
    return
  }
  acting.value = true
  const { ok, result } = await tryAction(
    () => api.replanTask(selectedTaskId.value, { eventId, scope: replanScope.value }),
    null,
  )
  acting.value = false
  if (!ok) return
  ElMessage.success(result.message)
  await loadTasks()
}

async function selectTask(id) {
  selectedTaskId.value = id
  await loadEvents()
}

onMounted(loadTasks)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">异常重排</h2>
        <p class="page-desc">
          上报异常后可触发重排。重排会<strong>锁定已执行趟次不予改动</strong>，
          并且次数有上限（防止无限循环）。需要
          <code class="perm-code">scheduling:replan</code>。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="loadTasks">刷新</el-button>
        <el-button type="warning" :icon="Plus" @click="openReport">上报异常</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 任务选择与重排 -->
      <el-col :xs="24" :lg="9">
        <el-card shadow="never" class="mb">
          <template #header>
            <span class="card-title">选择任务</span>
          </template>
          <el-select
            v-model="selectedTaskId"
            placeholder="选择调度任务"
            style="width: 100%"
            @change="selectTask"
          >
            <el-option
              v-for="t in tasks"
              :key="t.id"
              :label="`${t.code}（${t.schedule_date} · ${taskStatus(t.status).text}）`"
              :value="t.id"
            />
          </el-select>

          <template v-if="selectedTask">
            <el-descriptions :column="1" border size="small" class="mt-sm">
              <el-descriptions-item label="任务编号">
                <span class="perm-code">{{ selectedTask.code }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="调度日期">
                {{ selectedTask.schedule_date }}
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="taskStatus(selectedTask.status).type" size="small">
                  {{ taskStatus(selectedTask.status).text }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="重排次数">
                <span :class="{ 'replan-warn': selectedTask.replan_count > 0 }">
                  {{ selectedTask.replan_count }} / {{ REPLAN_LIMIT }}
                </span>
                <el-progress
                  :percentage="(selectedTask.replan_count / REPLAN_LIMIT) * 100"
                  :stroke-width="8"
                  :show-text="false"
                  :color="replanExhausted ? '#f56c6c' : '#e6a23c'"
                  class="mt-xs"
                />
              </el-descriptions-item>
            </el-descriptions>

            <el-radio-group v-model="replanScope" class="mt-sm" :disabled="replanExhausted">
              <el-radio-button value="local">局部重排</el-radio-button>
              <el-radio-button value="global">全局重排</el-radio-button>
            </el-radio-group>
            <div class="scope-note">
              {{ replanScope === 'local'
                ? '局部：优先修复受影响的部分，改动最小'
                : '全局：整单重新求解，改动较大但可能更优' }}
            </div>

            <el-button
              type="primary"
              :icon="RefreshRight"
              :loading="acting"
              :disabled="replanExhausted"
              style="width: 100%; margin-top: 12px"
              @click="doReplan(null)"
            >
              {{ replanExhausted ? '已达重排上限，需人工介入' : '触发重排（人工）' }}
            </el-button>

            <el-alert v-if="replanExhausted" type="error" :closable="false" class="mt-sm">
              <template #title>
                重排次数已达上限（{{ REPLAN_LIMIT }} 次）。这是需求文档里
                「异常重排死循环」风险的应对措施 —— 继续重排会被后端拒绝（409）。
              </template>
            </el-alert>
          </template>
        </el-card>
      </el-col>

      <!-- 异常事件列表 -->
      <el-col :xs="24" :lg="15">
        <el-card v-loading="loading" shadow="never">
          <template #header>
            <span class="card-title">异常事件（{{ events.length }}）</span>
          </template>

          <el-table :data="events" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column label="类型" width="140">
              <template #default="{ row }">
                <el-tag :type="eventMeta(row.event_type).type" size="small">
                  {{ eventMeta(row.event_type).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="110" />
            <el-table-column label="详情" min-width="200">
              <template #default="{ row }">
                <span class="muted detail-text">{{ row.payload }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag
                  :type="row.status === 'handled' ? 'success' : 'warning'"
                  size="small"
                  effect="plain"
                >
                  {{ row.status === 'handled' ? '已处理' : '待处理' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="发生时间" width="170">
              <template #default="{ row }">
                <span class="perm-code">{{ String(row.occurred_at).replace('T', ' ').slice(0, 19) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  link
                  :disabled="row.status === 'handled' || replanExhausted"
                  @click="doReplan(row.id)"
                >
                  重排
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !events.length" description="暂无异常事件" />
        </el-card>
      </el-col>
    </el-row>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        <el-icon><Warning /></el-icon>
        验证重排上限：连续点「触发重排」4 次，第 4 次会被拒绝并提示
        「已重排 3 次，达到上限 3，请人工介入处理（防止无限重排）」。
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" title="上报异常事件" width="500px">
      <el-form label-width="90px">
        <el-form-item label="异常类型">
          <el-select v-model="form.event_type" style="width: 100%">
            <el-option
              v-for="e in EVENT_TYPES"
              :key="e.value"
              :label="e.label"
              :value="e.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="form.source" placeholder="例如 司机 / 门店 / 系统" />
        </el-form-item>
        <el-form-item label="详情">
          <el-input
            v-model="form.detail"
            type="textarea"
            :rows="3"
            placeholder="例如 沪A1001 发动机故障，无法出车"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitEvent">上报</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.card-title {
  font-weight: 600;
}

.mb {
  margin-bottom: 16px;
}

.mt-sm {
  margin-top: 12px;
}

.mt-xs {
  margin-top: 6px;
}

.scope-note {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.replan-warn {
  color: #e6a23c;
  font-weight: 600;
}

.detail-text {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-size: 11px;
  word-break: break-all;
}
</style>
