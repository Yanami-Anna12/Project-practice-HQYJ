<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><RobotOutlined /> AI Agent 中心</h2>
        <div class="page-subtitle">
          8 类 Agent 协同　·　硬约束代码化，LLM 只做解释和辅助（PDF 3.11 / 4.1）
        </div>
      </div>
      <a-space>
        <a-tag :color="aiTagColor">{{ aiTagText }}</a-tag>
        <a-button :loading="loading" @click="loadAll">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- AI 能力状态 ---------------- -->
    <a-card :bordered="false" class="ai-panel">
      <a-row :gutter="[14, 14]">
        <a-col :xs="24" :md="12">
          <a-descriptions size="small" :column="1" title="LLM 接入状态">
            <a-descriptions-item label="状态">
              <a-tag :color="aiTagColor">{{ health.status || '-' }}</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="模型">{{ health.model || '-' }}</a-descriptions-item>
            <a-descriptions-item label="接口地址">
              <span class="mono" style="font-size: 12px">{{ health.base_url || '-' }}</span>
            </a-descriptions-item>
            <a-descriptions-item label="API Key">
              <a-tag :color="health.api_key_configured ? 'green' : 'orange'">
                {{ health.api_key_configured ? '已配置' : '未配置（规则引擎降级）' }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="知识库文档">
              {{ health.knowledge_docs ?? 0 }} 条
            </a-descriptions-item>
          </a-descriptions>
        </a-col>

        <a-col :xs="24" :md="12">
          <a-descriptions size="small" :column="1" title="任务概览">
            <a-descriptions-item label="Agent 任务总数">
              {{ summary.total_tasks ?? 0 }}
            </a-descriptions-item>
            <a-descriptions-item label="待人工确认">
              <a-tag :color="summary.pending_confirmation ? 'orange' : 'default'">
                {{ summary.pending_confirmation ?? 0 }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="LLM 增强任务">
              {{ summary.llm_enhanced_tasks ?? 0 }}
            </a-descriptions-item>
            <a-descriptions-item label="已生成报告">
              {{ summary.report_count ?? 0 }}
            </a-descriptions-item>
            <a-descriptions-item label="工作流节点">
              {{ (graphInfo.normal_flow || []).length }} 个（正常）+ {{ (graphInfo.replan_flow || []).length }} 个（重排）
            </a-descriptions-item>
          </a-descriptions>
        </a-col>
      </a-row>
    </a-card>

    <!-- ---------------- 8 类 Agent ---------------- -->
    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col v-for="a in agentCards" :key="a.code" :xs="24" :sm="12" :lg="6">
        <div class="agent-card" @click="go(a.path)">
          <div class="agent-icon" :style="{ background: a.color }">
            <component :is="a.icon" />
          </div>
          <div class="agent-body">
            <div class="agent-name">{{ a.name }}</div>
            <div class="agent-desc">{{ a.desc }}</div>
            <div class="agent-stat">
              任务数：<strong>{{ a.count }}</strong>
            </div>
          </div>
        </div>
      </a-col>
    </a-row>

    <!-- ---------------- 工作流 ---------------- -->
    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col :xs="24" :lg="14">
        <a-card title="LangGraph 工作流（PDF 4.3）" size="small" :bordered="false">
          <div class="flow-title">正常工单 / 巡检流程</div>
          <div class="flow-chain">
            <template v-for="(n, i) in graphInfo.normal_flow || []" :key="n">
              <span class="flow-node">{{ nodeLabel(n) }}</span>
              <span v-if="i < (graphInfo.normal_flow || []).length - 1" class="flow-arrow">→</span>
            </template>
          </div>
          <div class="flow-title" style="margin-top: 16px">异常重排入口</div>
          <div class="flow-chain">
            <template v-for="(n, i) in graphInfo.replan_flow || []" :key="n">
              <span class="flow-node replan">{{ nodeLabel(n) }}</span>
              <span v-if="i < (graphInfo.replan_flow || []).length - 1" class="flow-arrow">→</span>
            </template>
          </div>
          <a-alert
            style="margin-top: 16px"
            type="info"
            show-icon
            message="人工确认机制"
            description="阶段一生成多方案后任务挂起为「待确认」，通过 /confirm 接口确认方案后阶段二才建单下发。未确认不会产生任何工单，确保人工把关。"
          />
        </a-card>
      </a-col>

      <a-col :xs="24" :lg="10">
        <a-card title="Agent 任务统计" size="small" :bordered="false">
          <BaseChart :option="statOption" height="300px" :loading="loading" />
        </a-card>
      </a-col>
    </a-row>

    <!-- ---------------- 异常事件 ---------------- -->
    <a-card title="异常事件与重排（PDF 4.9）" size="small" :bordered="false" style="margin-top: 14px">
      <template #extra>
        <a-space>
          <a-button size="small" :loading="scanning" @click="scan">扫描异常事件</a-button>
          <a @click="router.push('/ai/tasks')">查看 Agent 任务</a>
        </a-space>
      </template>
      <a-table
        :columns="excColumns"
        :data-source="exceptions"
        row-key="id"
        size="small"
        :pagination="{ pageSize: 5 }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'severity'">
            <a-tag :color="{ 高: 'red', 中: 'orange', 低: 'default' }[record.severity]">
              {{ record.severity }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'handled'">
            <a-tag :color="record.handled ? 'green' : 'orange'">
              {{ record.handled ? '已处理' : '待处理' }}
            </a-tag>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ---------------- 定时任务 ---------------- -->
    <a-card title="定时任务（PDF 3.2 / 3.12 数据更新策略）" size="small" :bordered="false" style="margin-top: 14px">
      <a-table :columns="jobColumns" :data-source="jobs" row-key="job_code" size="small" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'enabled'">
            <a-tag :color="record.enabled ? 'green' : 'default'">
              {{ record.enabled ? '启用' : '停用' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'schedule'">
            <span class="mono" style="font-size: 12px">{{ record.cron_expr || '-' }}</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a :class="{ 'text-muted': running === record.job_code }" @click="runJob(record)">
              {{ running === record.job_code ? '执行中…' : '立即执行' }}
            </a>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup>
import { computed, h, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  BellOutlined,
  BookOutlined,
  ClusterOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import BaseChart from '@/components/BaseChart.vue'
import { aiApi } from '@/api'

const router = useRouter()

const loading = ref(false)
const scanning = ref(false)
const running = ref('')
const health = reactive({})
const graphInfo = reactive({ normal_flow: [], replan_flow: [] })
const summary = reactive({})
const stats = ref([])
const exceptions = ref([])
const jobs = ref([])

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
  monitor_exception: '异常监控',
  impact_analysis: '影响分析',
  replan: '异常重排',
  plan_scoring: '方案评分',
}
function nodeLabel(n) {
  return NODE_LABELS[n] || n
}

const aiTagText = computed(() =>
  health.status === 'ok' ? `LLM 在线 · ${health.model}` : '规则引擎模式',
)
const aiTagColor = computed(() => (health.status === 'ok' ? 'green' : 'orange'))

/** PDF 3.11 模块 10：AI Agent 中心八类 Agent */
const AGENT_DEFS = [
  {
    code: '智能工单调度',
    name: '智能工单调度 Agent',
    desc: '按类型/站点/频率/排班/地形生成多方案',
    color: '#2f6fb5',
    icon: ThunderboltOutlined,
    path: '/ai/work-order',
  },
  {
    code: '智能故障诊断',
    name: '智能故障诊断 Agent',
    desc: 'RAG 知识库 + 设备手册根因分析',
    color: '#f5222d',
    icon: ExperimentOutlined,
    path: '/ai/fault',
  },
  {
    code: '知识库 RAG',
    name: '知识库 RAG',
    desc: '设备手册 / SOP / 故障案例检索问答',
    color: '#722ed1',
    icon: BookOutlined,
    path: '/ai/knowledge',
  },
  {
    code: '智能风控',
    name: '智能风控 Agent',
    desc: '异常工单/故障/巡检/核销识别',
    color: '#fa8c16',
    icon: SafetyOutlined,
    path: '/ai/risk',
  },
  {
    code: '智能报告',
    name: '智能报告 Agent',
    desc: '日/周/月/即时运维分析报告',
    color: '#13c2c2',
    icon: FileTextOutlined,
    path: '/reports',
  },
  {
    code: '智能巡检报告',
    name: '智能巡检报告 Agent',
    desc: '巡检记录 + 异常项生成巡检报告',
    color: '#52c41a',
    icon: FileTextOutlined,
    path: '/ai/tasks',
  },
  {
    code: '智能运维建议',
    name: '智能运维建议 Agent',
    desc: '基于诊断结果与 SOP 给可执行建议',
    color: '#eb2f96',
    icon: RobotOutlined,
    path: '/ai/fault',
  },
  {
    code: '编排',
    name: '编排 Agent',
    desc: '协调子 Agent，控制报告质量与一致性',
    color: '#595959',
    icon: ClusterOutlined,
    path: '/ai/tasks',
  },
]

const agentCards = computed(() =>
  AGENT_DEFS.map((a) => {
    const found = stats.value.find((s) => s.agent_type === a.code)
    return { ...a, count: found?.total ?? 0 }
  }),
)

const statOption = computed(() => ({
  color: ['#2f6fb5', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96', '#595959'],
  tooltip: { trigger: 'item', formatter: '{b}: {c}' },
  legend: { bottom: 0, icon: 'circle', textStyle: { fontSize: 11 } },
  series: [
    {
      type: 'pie',
      radius: ['38%', '64%'],
      center: ['50%', '43%'],
      itemStyle: { borderRadius: 5, borderColor: '#fff', borderWidth: 2 },
      label: { fontSize: 11, formatter: '{b}\n{c}' },
      data: agentCards.value.filter((a) => a.count > 0).map((a) => ({ name: a.code, value: a.count })),
    },
  ],
}))

const excColumns = [
  { title: '事件编号', dataIndex: 'event_no', width: 170 },
  { title: '异常类型', dataIndex: 'event_type', width: 130 },
  { title: '来源', dataIndex: 'source', width: 100 },
  { title: '严重程度', key: 'severity', width: 90 },
  { title: '描述', dataIndex: 'description', ellipsis: true },
  { title: '状态', key: 'handled', width: 90 },
]

const jobColumns = [
  { title: '任务编码', dataIndex: 'job_code', width: 170 },
  { title: '任务名称', dataIndex: 'job_name' },
  { title: '类型', dataIndex: 'job_type', width: 90 },
  { title: '调度表达式', key: 'schedule', width: 130 },
  { title: '状态', key: 'enabled', width: 80 },
  { title: '上次执行', dataIndex: 'last_run_at', width: 160 },
  { title: '操作', key: 'action', width: 100 },
]

function go(path) {
  router.push(path)
}

async function loadAll() {
  loading.value = true
  try {
    const [h, g, c, e, j] = await Promise.all([
      aiApi.health(),
      aiApi.graph(),
      aiApi.center(),
      aiApi.exceptions({ page: 1, page_size: 20 }),
      aiApi.jobs(),
    ])
    Object.assign(health, h.data || {})
    Object.assign(graphInfo, g.data || {})
    Object.assign(summary, c.data?.summary || {})
    stats.value = c.data?.stats || []
    exceptions.value = e.data?.items || []
    jobs.value = j.data || []
  } finally {
    loading.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const res = await aiApi.scanExceptions()
    message.success(
      `扫描完成：发现 ${res.data.scanned} 条异常，新增登记 ${res.data.created} 条` +
        `，生成提醒 ${res.data.reminders?.messages_created ?? 0} 条`,
    )
    loadAll()
  } finally {
    scanning.value = false
  }
}

async function runJob(job) {
  running.value = job.job_code
  try {
    const res = await aiApi.runJob(job.job_code)
    message.success(`任务「${job.job_name}」执行完成：${JSON.stringify(res.data.result)}`)
    loadAll()
  } finally {
    running.value = ''
  }
}

onMounted(loadAll)
</script>

<style scoped>
.agent-card {
  display: flex;
  gap: 12px;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.2s;
  height: 100%;
}

.agent-card:hover {
  border-color: #2f6fb5;
  box-shadow: 0 5px 18px rgba(47, 111, 181, 0.15);
  transform: translateY(-2px);
}

.agent-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 19px;
  flex-shrink: 0;
}

.agent-body {
  min-width: 0;
}

.agent-name {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 3px;
}

.agent-desc {
  font-size: 12px;
  color: #8c8c8c;
  line-height: 1.6;
  margin-bottom: 5px;
}

.agent-stat {
  font-size: 12px;
  color: #646a73;
}

.flow-title {
  font-weight: 600;
  font-size: 13px;
  color: #1f4e79;
  margin-bottom: 9px;
}

.flow-chain {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
}

.flow-node {
  background: #eef3fa;
  color: #1f4e79;
  border-radius: 5px;
  padding: 3px 9px;
  font-size: 12px;
  white-space: nowrap;
}

.flow-node.replan {
  background: #fff2e8;
  color: #d4380d;
}

.flow-arrow {
  color: #bfbfbf;
  font-size: 12px;
}
</style>
