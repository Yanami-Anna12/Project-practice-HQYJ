<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><FileTextOutlined /> 运维分析建议报告</h2>
        <div class="page-subtitle">
          日运营简报 · 周运维分析 · 月度深度报告 · 即时分析（PDF 3.12 / 4.6）
        </div>
      </div>
      <a-space>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button type="primary" @click="openGenerate">
          <template #icon><PlusOutlined /></template>
          生成报告
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 报告类型 ---------------- -->
    <a-row :gutter="[14, 14]">
      <a-col v-for="t in REPORT_TYPES" :key="t.value" :xs="12" :sm="12" :md="6">
        <div class="type-card" :class="{ active: query.report_type === t.value }" @click="filterType(t.value)">
          <div class="type-icon"><component :is="t.icon" /></div>
          <div class="type-name">{{ t.label }}</div>
          <div class="type-desc">{{ t.desc }}</div>
          <div class="type-time">{{ t.schedule }}</div>
        </div>
      </a-col>
    </a-row>

    <!-- ---------------- 报告列表 ---------------- -->
    <a-card :bordered="false" style="margin-top: 14px">
      <a-table
        :columns="columns"
        :data-source="rows"
        :loading="loading"
        row-key="id"
        size="middle"
        :pagination="pagination"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'title'">
            <a class="clickable" @click="router.push(`/reports/${record.id}`)">
              {{ record.title }}
            </a>
            <div class="mono text-muted" style="font-size: 12px">{{ record.report_no }}</div>
          </template>
          <template v-else-if="column.key === 'report_type'">
            <a-tag :color="typeColor(record.report_type)">
              {{ typeLabel(record.report_type) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'period'">
            {{ record.period_start }} ~ {{ record.period_end }}
          </template>
          <template v-else-if="column.key === 'summary'">
            <span class="text-muted" style="font-size: 12px">
              {{ (record.summary || '').replace(/[#*\n]/g, ' ').slice(0, 80) }}…
            </span>
          </template>
          <template v-else-if="column.key === 'method'">
            <a-tag v-if="record.llm_used" color="purple">LLM 增强</a-tag>
            <a-tag v-else-if="record.degraded" color="orange">规则引擎</a-tag>
            <span v-else class="text-muted">-</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space size="small">
              <a @click="router.push(`/reports/${record.id}`)">查看</a>
              <a v-if="record.file_url" :href="downloadUrl(record)" target="_blank">PDF</a>
              <a @click="openPush(record)">推送</a>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ---------------- 生成报告 ---------------- -->
    <a-modal
      v-model:open="genOpen"
      title="生成运维分析报告"
      :confirm-loading="generating"
      @ok="submitGenerate"
    >
      <a-form layout="vertical">
        <a-form-item label="报告类型">
          <a-radio-group v-model:value="genForm.report_type" button-style="solid">
            <a-radio-button value="daily">日运营简报</a-radio-button>
            <a-radio-button value="weekly">周运维分析</a-radio-button>
            <a-radio-button value="monthly">月度深度报告</a-radio-button>
            <a-radio-button value="instant">即时分析</a-radio-button>
          </a-radio-group>
        </a-form-item>

        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="统计开始日期">
              <a-date-picker v-model:value="genForm.period_start" style="width: 100%" value-format="YYYY-MM-DD" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="统计结束日期">
              <a-date-picker v-model:value="genForm.period_end" style="width: 100%" value-format="YYYY-MM-DD" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="所属项目">
          <a-select v-model:value="genForm.project_id" allow-clear placeholder="全平台">
            <a-select-option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item label="推送通道（可选）">
          <a-select v-model:value="genForm.push_channels" mode="multiple" allow-clear placeholder="不推送">
            <a-select-option value="站内信">站内信</a-select-option>
            <a-select-option value="微信">微信</a-select-option>
            <a-select-option value="飞书">飞书</a-select-option>
            <a-select-option value="邮件">邮件</a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item>
          <a-checkbox v-model:checked="genForm.use_llm">
            使用 LLM 生成深度分析（PDF 4.1：LLM 只做解释与建议）
          </a-checkbox>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- ---------------- 推送 ---------------- -->
    <a-modal
      v-model:open="pushOpen"
      title="报告推送"
      :confirm-loading="pushing"
      @ok="submitPush"
    >
      <a-form layout="vertical">
        <a-form-item label="推送通道">
          <a-select v-model:value="pushForm.channels" mode="multiple">
            <a-select-option value="站内信">站内信</a-select-option>
            <a-select-option value="微信">微信</a-select-option>
            <a-select-option value="飞书">飞书</a-select-option>
            <a-select-option value="邮件">邮件</a-select-option>
          </a-select>
        </a-form-item>
        <a-alert
          type="info"
          show-icon
          message="未配置凭据的通道会被安全跳过"
          description="需要在 backend/.env 中配置飞书 Webhook / SMTP / 微信凭据后才能真正投递；站内信始终可用。"
        />
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  CalendarOutlined,
  ClockCircleOutlined,
  FieldTimeOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { adminApi, aiApi } from '@/api'

const router = useRouter()

const REPORT_TYPES = [
  {
    value: 'daily',
    label: '日运营简报',
    desc: '每日运行概览与异常',
    schedule: 'T+1 凌晨 2 点',
    icon: CalendarOutlined,
    color: 'blue',
  },
  {
    value: 'weekly',
    label: '周运维分析',
    desc: '本周趋势与环比',
    schedule: '每周一凌晨 3 点',
    icon: FieldTimeOutlined,
    color: 'green',
  },
  {
    value: 'monthly',
    label: '月度深度报告',
    desc: '月度深度分析与建议',
    schedule: '每月 1 日凌晨 4 点',
    icon: FileTextOutlined,
    color: 'purple',
  },
  {
    value: 'instant',
    label: '即时分析运营报告',
    desc: '用户触发即时分析',
    schedule: '用户手动触发',
    icon: ThunderboltOutlined,
    color: 'orange',
  },
]

const loading = ref(false)
const generating = ref(false)
const pushing = ref(false)
const rows = ref([])
const total = ref(0)
const projects = ref([])
const query = reactive({ report_type: undefined, page: 1, page_size: 10 })

const genOpen = ref(false)
const genForm = reactive({
  report_type: 'daily',
  period_start: undefined,
  period_end: undefined,
  project_id: undefined,
  push_channels: [],
  use_llm: true,
})

const pushOpen = ref(false)
const pushTarget = ref(null)
const pushForm = reactive({ channels: ['站内信'] })

const pagination = computed(() => ({
  current: query.page,
  pageSize: query.page_size,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

const columns = [
  { title: '报告标题', key: 'title', width: 280, fixed: 'left' },
  { title: '类型', key: 'report_type', width: 120 },
  { title: '统计周期', key: 'period', width: 200 },
  { title: '摘要', key: 'summary', ellipsis: true },
  { title: '生成方式', key: 'method', width: 110 },
  { title: '操作', key: 'action', width: 170, fixed: 'right' },
]

function typeLabel(t) {
  return { daily: '日运营简报', weekly: '周运维分析', monthly: '月度深度报告', instant: '即时分析' }[t] || t
}
function typeColor(t) {
  return { daily: 'blue', weekly: 'green', monthly: 'purple', instant: 'orange' }[t] || 'default'
}
function downloadUrl(record) {
  // 后端把报告文件挂在 /static/data 下
  return record.file_url?.replace(/\\/g, '/').replace(/^.*?data\//, '/static/data/')
}

async function load() {
  loading.value = true
  try {
    const res = await aiApi.reportList({ ...query })
    rows.value = res.data?.items || []
    total.value = res.data?.meta?.total || 0
  } finally {
    loading.value = false
  }
}

function filterType(t) {
  query.report_type = query.report_type === t ? undefined : t
  query.page = 1
  load()
}

function onTableChange(pag) {
  query.page = pag.current
  query.page_size = pag.pageSize
  load()
}

async function openGenerate() {
  genOpen.value = true
  if (!projects.value.length) {
    const res = await adminApi.projects()
    projects.value = res.data || []
  }
}

async function submitGenerate() {
  generating.value = true
  try {
    const res = await aiApi.reportGenerate({ ...genForm })
    message.success(`报告已生成：${res.data.report_no}`)
    genOpen.value = false
    await load()
    if (res.data.report_id) {
      router.push(`/reports/${res.data.report_id}`)
    }
  } catch {
    /* 已提示 */
  } finally {
    generating.value = false
  }
}

function openPush(record) {
  pushTarget.value = record
  pushForm.channels = ['站内信']
  pushOpen.value = true
}

async function submitPush() {
  pushing.value = true
  try {
    const res = await aiApi.reportPush(pushTarget.value.id, { channels: pushForm.channels })
    message.success(`已推送到 ${res.data.pushed} 人（通道：${res.data.channels.join('、')}）`)
    pushOpen.value = false
    load()
  } finally {
    pushing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.type-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.2s;
  height: 100%;
}

.type-card:hover,
.type-card.active {
  border-color: #2f6fb5;
  background: #f6f9ff;
  box-shadow: 0 4px 14px rgba(47, 111, 181, 0.12);
}

.type-icon {
  font-size: 20px;
  color: #2f6fb5;
  margin-bottom: 8px;
}

.type-name {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 4px;
}

.type-desc {
  font-size: 12px;
  color: #8c8c8c;
  line-height: 1.6;
}

.type-time {
  font-size: 11px;
  color: #a0a6ad;
  margin-top: 6px;
}
</style>
