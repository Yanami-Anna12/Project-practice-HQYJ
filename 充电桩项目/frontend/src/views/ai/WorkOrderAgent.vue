<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><ThunderboltOutlined /> 智能工单调度 Agent</h2>
        <div class="page-subtitle">
          生成工单与子任务多方案 → 人工确认 → 下发员工端（PDF 3.11 / 4.3 / 4.8）
        </div>
      </div>
      <a-space>
        <a-button :disabled="!taskId" @click="reset">
          <template #icon><PlusOutlined /></template>
          新建调度
        </a-button>
      </a-space>
    </div>

    <a-row :gutter="[14, 14]">
      <!-- ---------------- 左：参数 ---------------- -->
      <a-col :xs="24" :lg="9">
        <a-card title="调度参数" size="small" :bordered="false">
          <a-form layout="vertical" :model="form">
            <a-form-item label="工单类型">
              <a-select v-model:value="form.order_type">
                <a-select-option v-for="t in ORDER_TYPES" :key="t" :value="t">{{ t }}</a-select-option>
              </a-select>
            </a-form-item>

            <a-form-item label="所属项目">
              <a-select v-model:value="form.project_id" allow-clear placeholder="全部项目" @change="onProjectChange">
                <a-select-option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</a-select-option>
              </a-select>
            </a-form-item>

            <a-form-item label="站点（留空表示项目下全部站点）">
              <a-select
                v-model:value="form.station_ids"
                mode="multiple"
                allow-clear
                placeholder="选择站点"
                :options="stationOptions"
                :field-names="{ label: 'name', value: 'id' }"
              />
            </a-form-item>

            <a-row :gutter="10">
              <a-col :span="8">
                <a-form-item label="巡检频率">
                  <a-select v-model:value="form.inspect_frequency">
                    <a-select-option value="日">日</a-select-option>
                    <a-select-option value="周">周</a-select-option>
                    <a-select-option value="月">月</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
              <a-col :span="8">
                <a-form-item label="巡检周期">
                  <a-input-number v-model:value="form.inspect_cycle" :min="1" :max="24" style="width: 100%" />
                </a-form-item>
              </a-col>
              <a-col :span="8">
                <a-form-item label="巡检次数">
                  <a-input-number v-model:value="form.inspect_count" :min="1" :max="50" style="width: 100%" />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item label="计划开始日期">
              <a-date-picker
                v-model:value="form.schedule_date"
                style="width: 100%"
                value-format="YYYY-MM-DD"
              />
            </a-form-item>

            <a-form-item label="时间窗">
              <a-input v-model:value="form.time_window" placeholder="09:00-18:00" />
            </a-form-item>

            <a-form-item>
              <a-checkbox v-model:checked="form.explain_with_llm">
                使用 LLM 生成方案解释（PDF 4.1：LLM 只做解释）
              </a-checkbox>
            </a-form-item>

            <a-button
              type="primary"
              block
              size="large"
              :loading="starting"
              :disabled="running"
              @click="start"
            >
              <template #icon><ThunderboltOutlined /></template>
              开始智能调度
            </a-button>
          </a-form>
        </a-card>

        <!-- 执行进度 -->
        <a-card
          v-if="taskId"
          title="执行进度"
          size="small"
          :bordered="false"
          style="margin-top: 14px"
        >
          <a-progress
            :percent="progress"
            :status="taskStatus === 'failed' ? 'exception' : undefined"
            :stroke-color="taskStatus === 'dispatched' ? '#52c41a' : '#2f6fb5'"
          />
          <div style="margin-top: 8px">
            <a-tag :color="statusTagColor">{{ statusText }}</a-tag>
            <span class="text-muted" style="font-size: 12px">
              当前节点：{{ currentNodeLabel }}
            </span>
          </div>
          <div v-if="ruleVersion" class="text-muted" style="font-size: 12px; margin-top: 6px">
            规则版本：{{ ruleVersion }}
          </div>
          <div v-if="llmUsed" style="margin-top: 6px">
            <a-tag color="purple">LLM 增强</a-tag>
          </div>
          <div v-if="degraded" style="margin-top: 6px">
            <a-tag color="orange">规则引擎降级</a-tag>
          </div>
        </a-card>
      </a-col>

      <!-- ---------------- 右：方案与追踪 ---------------- -->
      <a-col :xs="24" :lg="15">
        <!-- 方案比选 -->
        <a-card title="候选方案比选（多方案 + 评分）" size="small" :bordered="false">
          <a-empty v-if="!plans.length" description="尚未生成方案，请先点击「开始智能调度」" />
          <a-row v-else :gutter="[12, 12]">
            <a-col v-for="(p, i) in plans" :key="p.plan_id" :xs="24" :sm="12" :xl="8">
              <div
                class="plan-card"
                :class="{ recommended: i === 0, selected: selectedPlanId === p.plan_id }"
                @click="selectedPlanId = p.plan_id"
              >
                <div class="plan-name">
                  {{ p.name }}
                  <a-tag v-if="i === 0" color="green" style="margin-left: 4px">推荐</a-tag>
                </div>
                <div class="plan-score">{{ p.score }}</div>
                <div class="text-muted" style="font-size: 12px; margin-bottom: 8px">
                  子任务 {{ p.subtask_count }} 个　策略 {{ p.strategy }}
                </div>
                <div class="plan-detail">
                  <div v-for="(v, k) in p.detail || {}" :key="k" class="plan-detail-row">
                    <span class="text-muted">{{ k }}</span>
                    <span>{{ typeof v === 'object' ? JSON.stringify(v) : v }}</span>
                  </div>
                </div>
              </div>
            </a-col>
          </a-row>
        </a-card>

        <!-- 方案解释 -->
        <a-card v-if="explanation" title="方案解释" size="small" :bordered="false" style="margin-top: 14px">
          <div class="explanation">{{ explanation }}</div>
        </a-card>

        <!-- 人工确认 -->
        <a-card
          v-if="taskStatus === 'waiting_confirmation'"
          title="人工确认（PDF 4.8）"
          size="small"
          :bordered="false"
          class="ai-panel"
          style="margin-top: 14px"
        >
          <a-alert
            type="warning"
            show-icon
            style="margin-bottom: 14px"
            message="流程已挂起，等待人工确认"
            description="未确认前不会创建任何工单。确认后系统将按所选方案建单并下发到员工端。"
          />
          <a-form layout="vertical">
            <a-form-item label="选择方案">
              <a-radio-group v-model:value="selectedPlanId" button-style="solid">
                <a-radio-button v-for="p in plans" :key="p.plan_id" :value="p.plan_id">
                  {{ p.plan_id }}（{{ p.score }} 分）
                </a-radio-button>
              </a-radio-group>
            </a-form-item>
            <a-form-item label="确认意见">
              <a-textarea v-model:value="comment" :rows="2" placeholder="选填，例如：同意按方案 A 执行" />
            </a-form-item>
            <a-space>
              <a-button type="primary" :loading="confirming" @click="confirm(true)">
                <template #icon><CheckOutlined /></template>
                确认并下发工单
              </a-button>
              <a-button danger :loading="confirming" @click="confirm(false)">驳回</a-button>
            </a-space>
          </a-form>
        </a-card>

        <!-- 下发结果 -->
        <a-card
          v-if="dispatchResult"
          title="下发结果"
          size="small"
          :bordered="false"
          style="margin-top: 14px"
        >
          <a-result
            status="success"
            :title="`工单 ${dispatchResult.order_no} 已下发`"
            :sub-title="`生成子任务 ${dispatchResult.created} 个 · 覆盖站点 ${dispatchResult.station_count} 个 · 通知 ${dispatchResult.notified_users} 人`"
          >
            <template #extra>
              <a-button type="primary" @click="router.push(`/work-orders/${dispatchResult.work_order_id}`)">
                查看工单
              </a-button>
            </template>
          </a-result>
        </a-card>

        <!-- 节点追踪 -->
        <a-card
          v-if="traces.length"
          title="节点执行追踪（ai_agent_trace）"
          size="small"
          :bordered="false"
          style="margin-top: 14px"
        >
          <a-timeline>
            <a-timeline-item
              v-for="t in traces"
              :key="t.step_index"
              :color="t.status === 'failed' ? 'red' : 'green'"
            >
              <div class="trace-head">
                <strong>{{ nodeLabel(t.node_name) }}</strong>
                <span class="mono text-muted" style="font-size: 11px">{{ t.node_name }}</span>
                <a-tag v-if="t.status !== 'success'" color="red" style="margin-left: 6px">
                  {{ t.status }}
                </a-tag>
              </div>
              <div class="trace-summary">{{ t.output_summary }}</div>
              <a-collapse ghost size="small" v-if="t.detail && Object.keys(t.detail).length">
                <a-collapse-panel key="1" header="查看详细数据">
                  <pre class="ai-trace">{{ pretty(t.detail) }}</pre>
                </a-collapse-panel>
              </a-collapse>
            </a-timeline-item>
          </a-timeline>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  CheckOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { adminApi, aiApi, openTaskSocket, pollAgentTask } from '@/api'

const router = useRouter()

const ORDER_TYPES = ['巡视', '特巡', '消缺', '设备检查', '其他']
const NODE_LABELS = {
  load_task: '加载任务',
  data_perception: '数据感知',
  constraint_parse: '规则解析',
  rule_validation: '规则校验',
  work_order_generation: '工单生成',
  task_scheduling: '任务调度',
  inspection_processing: '巡检处理',
  fault_diagnosis: '故障诊断',
  report_generation: '报告生成',
  human_confirmation: '人工确认',
  dispatch_execution: '下发执行',
  relax_constraints: '约束松弛',
  exception_handler: '异常处理',
  await_confirmation: '等待确认',
}
const STATUS_TEXT = {
  created: '已创建',
  running: '执行中',
  waiting_confirmation: '待人工确认',
  confirmed: '已确认',
  dispatched: '已下发',
  completed: '已完成',
  failed: '执行失败',
  replanning: '重排中',
  cancelled: '已取消',
}

const starting = ref(false)
const confirming = ref(false)
const taskId = ref('')
const taskStatus = ref('')
const progress = ref(0)
const currentNode = ref('')
const traces = ref([])
const plans = ref([])
const explanation = ref('')
const selectedPlanId = ref('')
const comment = ref('')
const dispatchResult = ref(null)
const ruleVersion = ref('')
const llmUsed = ref(false)
const degraded = ref(false)
const errorText = ref('')

const projects = ref([])
const stationOptions = ref([])

const form = reactive({
  order_type: '巡视',
  project_id: undefined,
  station_ids: [],
  inspect_frequency: '月',
  inspect_cycle: 1,
  inspect_count: 1,
  schedule_date: undefined,
  time_window: '09:00-18:00',
  explain_with_llm: true,
})

const running = computed(() => ['running', 'created'].includes(taskStatus.value))
const statusText = computed(() => STATUS_TEXT[taskStatus.value] || taskStatus.value || '-')
const statusTagColor = computed(
  () =>
    ({
      running: 'blue',
      created: 'blue',
      waiting_confirmation: 'orange',
      dispatched: 'green',
      completed: 'green',
      failed: 'red',
    })[taskStatus.value] || 'default',
)
const currentNodeLabel = computed(() => NODE_LABELS[currentNode.value] || currentNode.value || '-')

function nodeLabel(n) {
  return NODE_LABELS[n] || n
}
function pretty(obj) {
  return JSON.stringify(obj, null, 2)
}

let ws = null
let timer = null

function applyState(state) {
  if (!state) return
  const task = state.task || {}
  taskStatus.value = task.status || ''
  progress.value = task.progress || 0
  currentNode.value = task.current_node || ''
  ruleVersion.value = task.rule_version || ''
  llmUsed.value = Boolean(task.llm_used)
  degraded.value = Boolean(task.degraded)
  errorText.value = task.error || ''
  traces.value = state.traces || []
  explanation.value = task.plan_explanation || ''
  dispatchResult.value = task.result?.dispatch_result || null

  const conf = task.result?.confirmation_request
  const list = conf?.plans || []
  if (list.length) {
    plans.value = list
    if (!selectedPlanId.value) {
      selectedPlanId.value = conf?.recommended?.plan_id || list[0].plan_id
    }
  }
}

async function start() {
  if (!form.project_id && !form.station_ids.length) {
    message.warning('请至少选择项目或站点')
    return
  }
  starting.value = true
  reset(false)
  try {
    const res = await aiApi.generateWorkOrder({ ...form, auto_start: true })
    taskId.value = res.data.task_id
    message.success('调度任务已创建，正在执行…')
    startPolling()
  } catch {
    /* 已提示 */
  } finally {
    starting.value = false
  }
}

function startPolling() {
  stopPolling()
  // WebSocket 实时进度（PDF 5.4）
  try {
    ws = openTaskSocket(taskId.value, (msg) => {
      if (msg.node) currentNode.value = msg.node
      if (typeof msg.progress === 'number') progress.value = msg.progress
      if (msg.status) taskStatus.value = msg.status
    })
  } catch {
    ws = null
  }

  // 轮询兜底（同时拉取方案与追踪）
  pollAgentTask(taskId.value, applyState, { interval: 1200 })
    .then((state) => {
      applyState(state)
      const s = state?.task?.status
      if (s === 'waiting_confirmation') {
        message.info('方案已生成，请人工确认后下发')
      } else if (s === 'failed') {
        message.error(state?.task?.error || '调度失败')
      } else if (s === 'dispatched') {
        message.success('工单已下发')
      }
      stopPolling()
    })
    .catch((e) => {
      message.error(e.message || '任务轮询失败')
      stopPolling()
    })
}

function stopPolling() {
  if (ws) {
    try {
      ws.close()
    } catch {
      /* 忽略 */
    }
    ws = null
  }
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

async function confirm(approved) {
  confirming.value = true
  try {
    const res = await aiApi.confirmTask(taskId.value, {
      approved,
      plan_id: selectedPlanId.value || undefined,
      comment: comment.value,
    })
    applyState({ task: res.data, traces: traces.value })
    if (approved) {
      dispatchResult.value = res.data.dispatch_result || null
      taskStatus.value = res.data.status
      if (res.data.dispatch_result) {
        message.success('已确认并完成工单下发')
      } else {
        // 阶段二可能仍在执行，继续轮询
        message.success('已确认，正在下发…')
        pollAgentTask(taskId.value, applyState, { interval: 1200 })
          .then((state) => {
            applyState(state)
            message.success('下发完成')
          })
          .catch(() => {})
      }
    } else {
      taskStatus.value = res.data.status
      message.info('已驳回，可调整参数后重新调度')
    }
  } catch {
    /* 已提示 */
  } finally {
    confirming.value = false
  }
}

function reset(clearTask = true) {
  stopPolling()
  if (clearTask) {
    taskId.value = ''
  }
  taskStatus.value = ''
  progress.value = 0
  currentNode.value = ''
  traces.value = []
  plans.value = []
  explanation.value = ''
  selectedPlanId.value = ''
  comment.value = ''
  dispatchResult.value = null
  errorText.value = ''
}

async function onProjectChange(pid) {
  form.station_ids = []
  if (!pid) {
    stationOptions.value = []
    return
  }
  const res = await adminApi.stationOptions({ project_id: pid })
  stationOptions.value = res.data || []
}

onMounted(async () => {
  const res = await adminApi.projects()
  projects.value = res.data || []
  if (projects.value.length) {
    form.project_id = projects.value[0].id
    await onProjectChange(form.project_id)
  }
})

onUnmounted(stopPolling)
</script>

<style scoped>
.plan-detail {
  border-top: 1px dashed #e8e8e8;
  padding-top: 8px;
}

.plan-detail-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  line-height: 1.9;
}

.explanation {
  line-height: 1.9;
  font-size: 13px;
  color: #1f2329;
}

.trace-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.trace-summary {
  font-size: 12px;
  color: #646a73;
  margin-top: 4px;
  line-height: 1.7;
}
</style>
