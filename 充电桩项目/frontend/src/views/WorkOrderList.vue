<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><ProfileOutlined /> 工单管理</h2>
        <div class="page-subtitle">
          巡视 / 特巡 / 消缺 / 设备检查 / 其他　·　子任务数量由公式自动计算（硬约束）
        </div>
      </div>
      <a-space>
        <a-button @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button type="primary" @click="openCreate">
          <template #icon><PlusOutlined /></template>
          工单申请
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 工单首页统计 ---------------- -->
    <a-row :gutter="[14, 14]">
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="工单总数" :value="home.total" tone="primary" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="待办工单" :value="home.pending" tone="warning" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="已办工单" :value="home.done" tone="success" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="完成率" :value="home.completion_rate" suffix="%" tone="success" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="紧急工单" :value="home.urgent" tone="warning" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="逾期工单" :value="home.overdue" tone="danger" />
      </a-col>
    </a-row>

    <!-- ---------------- 筛选 ---------------- -->
    <div class="filter-bar" style="margin-top: 14px">
      <a-form layout="inline" :model="query">
        <a-form-item label="模糊查询">
          <a-input
            v-model:value="query.keyword"
            placeholder="工单编号 / 名称 / 站点名称"
            style="width: 220px"
            allow-clear
            @press-enter="search"
          >
            <template #prefix><SearchOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="工单类型">
          <a-select v-model:value="query.order_type" style="width: 130px" allow-clear placeholder="全部">
            <a-select-option v-for="t in ORDER_TYPES" :key="t" :value="t">{{ t }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="工单状态">
          <a-select v-model:value="query.status" style="width: 120px" allow-clear placeholder="全部">
            <a-select-option v-for="s in ORDER_STATUS" :key="s" :value="s">{{ s }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="时间状态">
          <a-select v-model:value="query.time_status" style="width: 110px" allow-clear placeholder="全部">
            <a-select-option value="正常">正常</a-select-option>
            <a-select-option value="紧急">紧急</a-select-option>
            <a-select-option value="逾期">逾期</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" :loading="loading" @click="search">查询</a-button>
            <a-button @click="reset">重置</a-button>
            <a-button @click="exportOrders">
              <template #icon><ExportOutlined /></template>
              导出 Excel
            </a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </div>

    <!-- ---------------- 列表 ---------------- -->
    <a-card :bordered="false">
      <a-table
        :columns="columns"
        :data-source="rows"
        :loading="loading"
        row-key="id"
        size="middle"
        :scroll="{ x: 1280 }"
        :pagination="pagination"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'order'">
            <a class="clickable" @click="router.push(`/work-orders/${record.id}`)">
              {{ record.order_name }}
            </a>
            <div class="mono text-muted" style="font-size: 12px">{{ record.order_no }}</div>
          </template>

          <template v-else-if="column.key === 'order_type'">
            <a-tag :color="typeColor(record.order_type)">{{ record.order_type }}</a-tag>
          </template>

          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
          </template>

          <template v-else-if="column.key === 'time_status'">
            <a-tag :color="timeColor(record.time_status)">{{ record.time_status }}</a-tag>
          </template>

          <template v-else-if="column.key === 'progress'">
            <a-progress
              :percent="percent(record)"
              size="small"
              :stroke-color="percent(record) >= 100 ? '#52c41a' : '#2f6fb5'"
            />
            <span class="text-muted" style="font-size: 12px">
              {{ record.subtask_done }} / {{ record.subtask_total }}
            </span>
          </template>

          <template v-else-if="column.key === 'period'">
            <div style="font-size: 12px">
              {{ record.inspect_start_date || '-' }} ~ {{ record.inspect_end_date || '-' }}
            </div>
            <div class="text-muted" style="font-size: 12px">
              频率 {{ record.inspect_frequency }} · 次数 {{ record.inspect_count }} · 周期 {{ record.inspect_cycle }}
            </div>
          </template>

          <template v-else-if="column.key === 'source'">
            <a-tag :color="record.source === 'AI 生成' ? 'purple' : 'default'">
              {{ record.source }}
            </a-tag>
          </template>

          <template v-else-if="column.key === 'action'">
            <a-space size="small">
              <a @click="router.push(`/work-orders/${record.id}`)">详情</a>
              <a v-if="record.status === '待接单'" @click="doAccept(record)">接受</a>
              <a v-if="record.status === '待接单'" @click="openReject(record)">退回</a>
              <a
                v-if="['待接单', '待完成', '已退回'].includes(record.status)"
                class="text-danger"
                @click="openCancel(record)"
              >
                取消
              </a>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ---------------- 工单申请 ---------------- -->
    <a-modal
      v-model:open="createOpen"
      title="工单申请"
      width="720px"
      :confirm-loading="creating"
      @ok="submitCreate"
    >
      <a-alert
        v-if="formulaHint"
        type="info"
        show-icon
        style="margin-bottom: 14px"
        :message="`子任务数量公式：${formulaHint}`"
        :description="`按当前选择将生成 ${previewCount} 个子任务（由后端确定性代码保证）`"
      />

      <a-form :model="form" layout="vertical">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="工单名称" required>
              <a-input v-model:value="form.order_name" placeholder="例如：阳澄湖服务区巡视工单" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="工单类型" required>
              <a-select v-model:value="form.order_type">
                <a-select-option v-for="t in ORDER_TYPES" :key="t" :value="t">{{ t }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item label="所属项目">
              <a-select v-model:value="form.project_id" allow-clear placeholder="选择项目" @change="onProjectChange">
                <a-select-option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="站点（可多选）">
              <a-select
                v-model:value="form.station_ids"
                mode="multiple"
                allow-clear
                placeholder="选择站点"
                :options="stationOptions"
                :field-names="{ label: 'name', value: 'id' }"
              />
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item label="巡检人员">
              <a-select v-model:value="form.inspector_id" allow-clear placeholder="分配巡检人员">
                <a-select-option v-for="u in staffList" :key="u.id" :value="u.id">
                  {{ u.real_name }}
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="巡检频率">
              <a-select v-model:value="form.inspect_frequency">
                <a-select-option value="日">日</a-select-option>
                <a-select-option value="周">周</a-select-option>
                <a-select-option value="月">月</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="巡检周期">
              <a-input-number v-model:value="form.inspect_cycle" :min="1" :max="24" style="width: 100%" />
            </a-form-item>
          </a-col>

          <a-col :span="8">
            <a-form-item label="巡检开始日期">
              <a-date-picker
                v-model:value="form.inspect_start_date"
                style="width: 100%"
                value-format="YYYY-MM-DD"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="巡检结束日期">
              <a-date-picker
                v-model:value="form.inspect_end_date"
                style="width: 100%"
                value-format="YYYY-MM-DD"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="巡检次数（特巡）">
              <a-input-number v-model:value="form.inspect_count" :min="1" :max="50" style="width: 100%" />
            </a-form-item>
          </a-col>

          <a-col :span="24">
            <a-form-item label="备注">
              <a-textarea v-model:value="form.remark" :rows="2" placeholder="选填" />
            </a-form-item>
          </a-col>

          <a-col :span="24">
            <a-form-item>
              <a-checkbox v-model:checked="form.auto_dispatch">
                同时提交「智能工单调度 Agent」优化排期（生成多方案供人工确认）
              </a-checkbox>
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>

    <!-- ---------------- 退回 / 取消 ---------------- -->
    <a-modal
      v-model:open="actionOpen"
      :title="actionType === 'reject' ? '退回工单' : '取消工单'"
      :confirm-loading="actionLoading"
      @ok="submitAction"
    >
      <a-form layout="vertical">
        <a-form-item :label="actionType === 'reject' ? '退回原因' : '取消原因'" required>
          <a-textarea v-model:value="actionReason" :rows="3" placeholder="请填写原因" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- ---------------- 导出进度 ---------------- -->
    <a-modal v-model:open="exportOpen" title="工单导出" :footer="null" :closable="!exporting">
      <div style="text-align: center; padding: 12px 0">
        <a-progress
          type="circle"
          :percent="exportTask.progress || 0"
          :status="exportTask.status === 'failed' ? 'exception' : undefined"
        />
        <div style="margin-top: 14px">{{ exportTask.message || '正在准备…' }}</div>
        <div v-if="exportTask.status === 'success'" style="margin-top: 10px">
          <a-button type="primary" @click="downloadExport">下载 Excel</a-button>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ExportOutlined,
  PlusOutlined,
  ProfileOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import StatCard from '@/components/StatCard.vue'
import { adminApi, exportApi, workOrderApi } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const ORDER_TYPES = ['巡视', '特巡', '消缺', '设备检查', '其他']
const ORDER_STATUS = ['待接单', '待完成', '已完成', '已取消', '已退回']

const loading = ref(false)
const creating = ref(false)
const rows = ref([])
const home = reactive({ total: 0, pending: 0, done: 0, overdue: 0, urgent: 0, completion_rate: 0 })
const projects = ref([])
const stationOptions = ref([])
const staffList = ref([])

const query = reactive({
  keyword: '',
  order_type: undefined,
  status: undefined,
  time_status: undefined,
  page: 1,
  page_size: 20,
})

const pagination = computed(() => ({
  current: query.page,
  pageSize: query.page_size,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))
const total = ref(0)

const columns = [
  { title: '工单编号 / 名称', key: 'order', width: 230, fixed: 'left' },
  { title: '类型', key: 'order_type', width: 100 },
  { title: '站点', dataIndex: 'station_name', width: 190, ellipsis: true },
  { title: '巡检人员', dataIndex: 'inspector_name', width: 100 },
  { title: '巡检周期', key: 'period', width: 230 },
  { title: '子任务进度', key: 'progress', width: 160 },
  { title: '状态', key: 'status', width: 90 },
  { title: '时间状态', key: 'time_status', width: 90 },
  { title: '来源', key: 'source', width: 90 },
  { title: '操作', key: 'action', width: 170, fixed: 'right' },
]

// ---------------------------------------------------------------- 展示辅助
function percent(r) {
  if (!r.subtask_total) return 0
  return Math.round((r.subtask_done / r.subtask_total) * 100)
}
function typeColor(t) {
  return (
    { 巡视: 'blue', 特巡: 'purple', 消缺: 'red', 设备检查: 'cyan', 其他: 'default' }[t] ||
    'default'
  )
}
function statusColor(s) {
  return (
    {
      待接单: 'orange',
      待完成: 'blue',
      已完成: 'green',
      已取消: 'default',
      已退回: 'red',
    }[s] || 'default'
  )
}
function timeColor(s) {
  return { 正常: 'green', 紧急: 'orange', 逾期: 'red' }[s] || 'default'
}

// ---------------------------------------------------------------- 数据
async function load() {
  loading.value = true
  try {
    const [listRes, homeRes] = await Promise.all([
      workOrderApi.list({ ...query }),
      workOrderApi.home(),
    ])
    rows.value = listRes.data?.items || []
    total.value = listRes.data?.meta?.total || 0
    Object.assign(home, homeRes.data || {})
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  Object.assign(query, {
    keyword: '',
    order_type: undefined,
    status: undefined,
    time_status: undefined,
    page: 1,
  })
  load()
}

function onTableChange(pag) {
  query.page = pag.current
  query.page_size = pag.pageSize
  load()
}

// ---------------------------------------------------------------- 工单申请
const createOpen = ref(false)
const form = reactive({
  order_name: '',
  order_type: '巡视',
  project_id: undefined,
  station_ids: [],
  inspector_id: undefined,
  inspect_frequency: '月',
  inspect_cycle: 1,
  inspect_count: 1,
  inspect_start_date: undefined,
  inspect_end_date: undefined,
  remark: '',
  auto_dispatch: false,
})

const FORMULA = {
  巡视: '站点数量 × 巡检周期 × 巡检频率',
  设备检查: '站点数量 × 巡检周期 × 巡检频率',
  其他: '站点数量 × 巡检周期 × 巡检频率',
  特巡: '站点数量 × 巡检次数',
  消缺: '固定 1 个子任务',
}
const FREQ = { 日: 30, 周: 4, 月: 1 }

const formulaHint = computed(() => FORMULA[form.order_type])
const previewCount = computed(() => {
  const n = form.station_ids?.length || 0
  if (form.order_type === '消缺') return n ? 1 : 0
  if (form.order_type === '特巡') return n * (form.inspect_count || 1)
  return n * (form.inspect_cycle || 1) * (FREQ[form.inspect_frequency] || 1)
})

async function openCreate() {
  createOpen.value = true
  if (!projects.value.length) {
    const res = await adminApi.projects()
    projects.value = res.data || []
  }
  if (!staffList.value.length) {
    const res = await adminApi.users({ page: 1, page_size: 100 })
    staffList.value = (res.data?.items || []).filter((u) => u.user_type === 'staff' && u.status)
  }
}

async function onProjectChange(pid) {
  form.station_ids = []
  const res = await adminApi.stationOptions({ project_id: pid })
  stationOptions.value = res.data || []
}

async function submitCreate() {
  if (!form.order_name) {
    message.warning('请填写工单名称')
    return
  }
  if (!form.station_ids?.length) {
    message.warning('请至少选择一个站点')
    return
  }
  creating.value = true
  try {
    const res = await workOrderApi.create({ ...form })
    message.success(res.message || '工单创建成功')
    createOpen.value = false
    Object.assign(form, {
      order_name: '',
      station_ids: [],
      remark: '',
      auto_dispatch: false,
    })
    await load()
  } catch {
    /* 已提示 */
  } finally {
    creating.value = false
  }
}

// ---------------------------------------------------------------- 接单 / 退回 / 取消
async function doAccept(record) {
  try {
    await workOrderApi.accept(record.id)
    message.success('已接受工单')
    load()
  } catch {
    /* 已提示 */
  }
}

const actionOpen = ref(false)
const actionType = ref('reject')
const actionReason = ref('')
const actionLoading = ref(false)
const actionTarget = ref(null)

function openReject(record) {
  actionType.value = 'reject'
  actionTarget.value = record
  actionReason.value = ''
  actionOpen.value = true
}

function openCancel(record) {
  actionType.value = 'cancel'
  actionTarget.value = record
  actionReason.value = ''
  actionOpen.value = true
}

async function submitAction() {
  if (!actionReason.value.trim()) {
    message.warning('请填写原因')
    return
  }
  actionLoading.value = true
  try {
    const payload = { reason: actionReason.value }
    if (actionType.value === 'reject') {
      await workOrderApi.reject(actionTarget.value.id, payload)
      message.success('工单已退回')
    } else {
      await workOrderApi.cancel(actionTarget.value.id, payload)
      message.success('工单已取消')
    }
    actionOpen.value = false
    load()
  } catch {
    /* 已提示 */
  } finally {
    actionLoading.value = false
  }
}

// ---------------------------------------------------------------- 导出
const exportOpen = ref(false)
const exporting = ref(false)
const exportTask = reactive({ progress: 0, status: '', message: '', file_name: '' })

async function exportOrders() {
  exportOpen.value = true
  exporting.value = true
  Object.assign(exportTask, { progress: 0, status: '', message: '正在创建导出任务…', file_name: '' })
  try {
    const res = await exportApi.createWorkOrders({})
    const taskId = res.data.task_id
    const final = await exportApi.poll(taskId, (t) => {
      Object.assign(exportTask, {
        progress: t.progress,
        status: t.status,
        message: t.message,
        file_name: t.file_name,
      })
    })
    Object.assign(exportTask, { file_name: final.file_name })
  } catch (e) {
    exportTask.status = 'failed'
    exportTask.message = e.message || '导出失败'
  } finally {
    exporting.value = false
  }
}

async function downloadExport() {
  const res = await exportApi.tasks({ limit: 1 })
  const latest = res.data?.[0]
  if (!latest) {
    message.warning('未找到可下载的导出文件')
    return
  }
  await exportApi.download(latest.task_id, latest.file_name)
  message.success('已开始下载')
}

onMounted(load)
</script>
