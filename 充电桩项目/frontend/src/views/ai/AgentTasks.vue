<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><ClusterOutlined /> Agent 任务管理</h2>
        <div class="page-subtitle">
          任务状态 · 节点追踪 · 人工确认 · 异常重排（PDF 5.3 / 4.8 / 4.9）
        </div>
      </div>
      <a-space>
        <a-select v-model:value="query.status" style="width: 150px" allow-clear placeholder="全部状态" @change="search">
          <a-select-option value="running">执行中</a-select-option>
          <a-select-option value="waiting_confirmation">待人工确认</a-select-option>
          <a-select-option value="dispatched">已下发</a-select-option>
          <a-select-option value="completed">已完成</a-select-option>
          <a-select-option value="failed">执行失败</a-select-option>
        </a-select>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <a-card :bordered="false">
      <a-table
        :columns="columns"
        :data-source="rows"
        :loading="loading"
        row-key="id"
        size="middle"
        :scroll="{ x: 1200 }"
        :pagination="pagination"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'task'">
            <div>{{ record.task_name || record.agent_type }}</div>
            <div class="mono text-muted" style="font-size: 12px">{{ record.task_no }}</div>
          </template>
          <template v-else-if="column.key === 'agent_type'">
            <a-tag color="blue">{{ record.agent_type }}</a-tag>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'progress'">
            <a-progress :percent="record.progress || 0" size="small" />
            <span class="text-muted" style="font-size: 11px">{{ record.current_node || '-' }}</span>
          </template>
          <template v-else-if="column.key === 'llm'">
            <a-tag v-if="record.llm_used" color="purple">LLM</a-tag>
            <a-tag v-else-if="record.degraded" color="orange">降级</a-tag>
            <span v-else class="text-muted">-</span>
          </template>
          <template v-else-if="column.key === 'replan'">
            <a-tag v-if="record.replan_count" color="volcano">{{ record.replan_count }} 次</a-tag>
            <span v-else class="text-muted">-</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space size="small">
              <a @click="openDetail(record)">详情</a>
              <a v-if="record.status === 'waiting_confirmation'" @click="quickConfirm(record)">
                确认
              </a>
              <a v-if="record.status === 'failed'" @click="openReplan(record)">重排</a>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ---------------- 详情 ---------------- -->
    <a-drawer v-model:open="detailOpen" title="Agent 任务详情" width="760" placement="right">
      <a-spin :spinning="detailLoading">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="任务编号">
            <span class="mono">{{ current.task_no }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="Agent 类型">{{ current.agent_type }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="statusColor(current.status)">{{ statusText(current.status) }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="进度">
            <a-progress :percent="current.progress || 0" size="small" />
          </a-descriptions-item>
          <a-descriptions-item label="当前节点">{{ current.current_node || '-' }}</a-descriptions-item>
          <a-descriptions-item label="规则版本">{{ current.rule_version || '-' }}</a-descriptions-item>
          <a-descriptions-item label="重排次数">{{ current.replan_count || 0 }}</a-descriptions-item>
          <a-descriptions-item label="耗时">
            {{ current.duration_ms ? `${Math.round(current.duration_ms)} ms` : '-' }}
          </a-descriptions-item>
          <a-descriptions-item v-if="current.error" label="错误信息">
            <span class="text-danger">{{ current.error }}</span>
          </a-descriptions-item>
        </a-descriptions>

        <template v-if="current.selected_plan">
          <a-divider>选中方案</a-divider>
          <a-descriptions :column="1" bordered size="small">
            <a-descriptions-item label="方案">
              {{ current.selected_plan.name }}（{{ current.selected_plan.plan_id }}）
            </a-descriptions-item>
            <a-descriptions-item label="得分">{{ current.selected_plan.score }}</a-descriptions-item>
            <a-descriptions-item label="子任务数">
              {{ current.selected_plan.subtask_count }}
            </a-descriptions-item>
          </a-descriptions>
        </template>

        <template v-if="current.plan_explanation">
          <a-divider>方案解释</a-divider>
          <div class="explanation">{{ current.plan_explanation }}</div>
        </template>

        <template v-if="current.confirmation">
          <a-divider>人工确认记录</a-divider>
          <a-descriptions :column="1" bordered size="small">
            <a-descriptions-item label="结果">
              <a-tag :color="current.confirmation.approved ? 'green' : 'red'">
                {{ current.confirmation.approved ? '通过' : '驳回' }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="方案">{{ current.confirmation.plan_id || '-' }}</a-descriptions-item>
            <a-descriptions-item label="确认人">
              {{ current.confirmation.confirmed_by || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="确认时间">
              {{ current.confirmation.confirmed_at || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="意见">
              {{ current.confirmation.comment || '-' }}
            </a-descriptions-item>
          </a-descriptions>
        </template>

        <template v-if="traces.length">
          <a-divider>节点追踪</a-divider>
          <a-timeline>
            <a-timeline-item
              v-for="t in traces"
              :key="t.step_index"
              :color="t.status === 'failed' ? 'red' : 'green'"
            >
              <div>
                <strong>{{ t.node_name }}</strong>
                <span class="text-muted" style="font-size: 12px; margin-left: 8px">
                  {{ t.output_summary }}
                </span>
              </div>
              <a-collapse v-if="t.detail && Object.keys(t.detail).length" ghost size="small">
                <a-collapse-panel key="1" header="详细数据">
                  <pre class="ai-trace">{{ JSON.stringify(t.detail, null, 2) }}</pre>
                </a-collapse-panel>
              </a-collapse>
            </a-timeline-item>
          </a-timeline>
        </template>
      </a-spin>
    </a-drawer>

    <!-- ---------------- 异常重排 ---------------- -->
    <a-modal
      v-model:open="replanOpen"
      title="异常重排（PDF 4.9）"
      :confirm-loading="replanLoading"
      @ok="submitReplan"
    >
      <a-alert
        type="info"
        show-icon
        style="margin-bottom: 14px"
        message="重排策略"
        description="锁定已执行工单 / 已核查故障 / 已完成巡检不重排；只重排未完成部分；优先局部修复，失败再全局重排；replan_count 达上限后停止自动重排。"
      />
      <a-form layout="vertical">
        <a-form-item label="异常类型">
          <a-select v-model:value="replanForm.exception_type">
            <a-select-option value="工单逾期">工单逾期</a-select-option>
            <a-select-option value="人员缺勤">人员缺勤</a-select-option>
            <a-select-option value="车辆故障">车辆故障</a-select-option>
            <a-select-option value="故障误报">故障误报</a-select-option>
            <a-select-option value="故障等级变更">故障等级变更</a-select-option>
            <a-select-option value="巡检未完成">巡检未完成</a-select-option>
            <a-select-option value="定位异常">定位异常</a-select-option>
            <a-select-option value="天气">天气</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="重排策略">
          <a-radio-group v-model:value="replanForm.strategy" button-style="solid">
            <a-radio-button value="local_first">优先局部修复</a-radio-button>
            <a-radio-button value="global">全局重排</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="异常说明">
          <a-textarea v-model:value="replanForm.description" :rows="3" />
        </a-form-item>
        <a-form-item>
          <a-checkbox v-model:checked="replanForm.lock_executed">锁定已执行任务</a-checkbox>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { ClusterOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { aiApi } from '@/api'

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

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ status: undefined, page: 1, page_size: 20 })

const detailOpen = ref(false)
const detailLoading = ref(false)
const current = ref({})
const traces = ref([])

const replanOpen = ref(false)
const replanLoading = ref(false)
const replanTarget = ref(null)
const replanForm = reactive({
  exception_type: '工单逾期',
  description: '',
  strategy: 'local_first',
  lock_executed: true,
})

const pagination = computed(() => ({
  current: query.page,
  pageSize: query.page_size,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

const columns = [
  { title: '任务', key: 'task', width: 220, fixed: 'left' },
  { title: 'Agent 类型', key: 'agent_type', width: 140 },
  { title: '状态', key: 'status', width: 110 },
  { title: '进度', key: 'progress', width: 160 },
  { title: '方式', key: 'llm', width: 90 },
  { title: '重排', key: 'replan', width: 80 },
  { title: '创建时间', dataIndex: 'created_at', width: 165 },
  { title: '操作', key: 'action', width: 150, fixed: 'right' },
]

function statusText(s) {
  return STATUS_TEXT[s] || s || '-'
}
function statusColor(s) {
  return (
    {
      running: 'blue',
      created: 'blue',
      waiting_confirmation: 'orange',
      dispatched: 'green',
      completed: 'green',
      failed: 'red',
      replanning: 'volcano',
    }[s] || 'default'
  )
}

async function load() {
  loading.value = true
  try {
    const res = await aiApi.taskList({ ...query })
    rows.value = res.data?.items || []
    total.value = res.data?.meta?.total || 0
    rows.value.forEach((r) => {
      if (typeof r.created_at === 'string') r.created_at = r.created_at.replace('T', ' ').slice(0, 19)
    })
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function onTableChange(pag) {
  query.page = pag.current
  query.page_size = pag.pageSize
  load()
}

async function openDetail(record) {
  current.value = record
  traces.value = []
  detailOpen.value = true
  detailLoading.value = true
  try {
    const res = await aiApi.taskState(record.id)
    current.value = res.data?.task || record
    traces.value = res.data?.traces || []
  } finally {
    detailLoading.value = false
  }
}

async function quickConfirm(record) {
  try {
    const res = await aiApi.confirmTask(record.id, { approved: true })
    message.success(
      res.data?.dispatch_result
        ? `已确认并下发：${res.data.dispatch_result.order_no}`
        : '已确认，正在下发…',
    )
    load()
  } catch {
    /* 已提示 */
  }
}

function openReplan(record) {
  replanTarget.value = record
  replanForm.description = record.error || ''
  replanOpen.value = true
}

async function submitReplan() {
  replanLoading.value = true
  try {
    const res = await aiApi.replanTask(replanTarget.value.id, { ...replanForm })
    message.success(`已创建重排任务 ${res.data.task_no}（第 ${res.data.replan_count + 1} 次重排）`)
    replanOpen.value = false
    load()
  } catch {
    /* 已提示 */
  } finally {
    replanLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.explanation {
  line-height: 1.9;
  font-size: 13px;
}
</style>
