<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">
          <a-button type="text" size="small" @click="router.push('/reports')">
            <template #icon><ArrowLeftOutlined /></template>
          </a-button>
          {{ report.title || '报告详情' }}
        </h2>
        <div class="page-subtitle">
          {{ report.report_no }}　·　{{ report.period_start }} ~ {{ report.period_end }}
        </div>
      </div>
      <a-space>
        <a-tag v-if="report.llm_used" color="purple">LLM 增强</a-tag>
        <a-tag v-else-if="report.degraded" color="orange">规则引擎</a-tag>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button @click="pushOpen = true">
          <template #icon><SendOutlined /></template>
          推送
        </a-button>
      </a-space>
    </div>

    <a-spin :spinning="loading">
      <a-row :gutter="[14, 14]">
        <!-- ---------------- 左：核心指标 ---------------- -->
        <a-col :xs="24" :lg="8">
          <a-card title="核心指标" size="small" :bordered="false">
            <a-descriptions :column="1" size="small" bordered>
              <a-descriptions-item
                v-for="m in metricRows"
                :key="m.label"
                :label="m.label"
              >
                {{ m.value }}
              </a-descriptions-item>
            </a-descriptions>
          </a-card>

          <a-card
            v-if="(report.suggestions || []).length"
            title="运维建议"
            size="small"
            :bordered="false"
            style="margin-top: 14px"
          >
            <div v-for="(s, i) in report.suggestions" :key="i" class="suggestion">
              <div class="suggestion-head">
                <a-tag :color="{ 高: 'red', 中: 'orange', 低: 'default' }[s.priority]">
                  {{ s.priority }}
                </a-tag>
                <strong>{{ s.title }}</strong>
              </div>
              <div class="suggestion-body">{{ s.detail }}</div>
            </div>
          </a-card>

          <a-card
            v-if="(report.pushed_channels || []).length"
            title="推送记录"
            size="small"
            :bordered="false"
            style="margin-top: 14px"
          >
            <a-space wrap>
              <a-tag v-for="c in report.pushed_channels" :key="c" color="blue">{{ c }}</a-tag>
            </a-space>
          </a-card>
        </a-col>

        <!-- ---------------- 右：报告全文 ---------------- -->
        <a-col :xs="24" :lg="16">
          <a-card title="报告全文" size="small" :bordered="false">
            <template #extra>
              <a-space>
                <a v-if="reportHtmlUrl" :href="reportHtmlUrl" target="_blank">HTML</a>
                <a v-if="reportPdfUrl" :href="reportPdfUrl" target="_blank">PDF</a>
              </a-space>
            </template>
            <div class="report-body" v-html="renderedMarkdown" />
          </a-card>

          <!-- 追问下钻 -->
          <a-card title="追问下钻（PDF 3.12）" size="small" :bordered="false" style="margin-top: 14px">
            <a-space style="width: 100%">
              <a-input
                v-model:value="question"
                placeholder="例如：本周逾期工单有多少？主要原因是通信故障吗？"
                @press-enter="ask"
              />
              <a-button type="primary" :loading="asking" @click="ask">
                <template #icon><SendOutlined /></template>
                追问
              </a-button>
            </a-space>

            <div v-if="followUps.length" style="margin-top: 16px">
              <div v-for="(f, i) in followUps" :key="i" class="followup">
                <div class="followup-q">
                  <QuestionCircleOutlined /> {{ f.question }}
                </div>
                <div class="followup-a" v-html="renderMarkdown(f.answer)" />
                <div v-if="(f.refs || []).length" class="followup-refs">
                  引用：{{ f.refs.map((r) => `《${r.title}》`).join('、') }}
                </div>
              </div>
            </div>
          </a-card>

          <!-- 历史对比 -->
          <a-card title="历史对比" size="small" :bordered="false" style="margin-top: 14px">
            <template #extra>
              <a @click="loadCompare">加载对比</a>
            </template>
            <a-empty v-if="!compare" description="点击「加载对比」查看同类报告环比" />
            <template v-else>
              <BaseChart :option="compareOption" height="300px" />
              <a-table
                :columns="deltaColumns"
                :data-source="deltaRows"
                row-key="label"
                size="small"
                :pagination="false"
                style="margin-top: 10px"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'delta'">
                    <span :class="record.delta > 0 ? 'text-danger' : record.delta < 0 ? 'text-success' : ''">
                      {{ record.delta > 0 ? '+' : '' }}{{ record.delta }}
                    </span>
                  </template>
                </template>
              </a-table>
            </template>
          </a-card>
        </a-col>
      </a-row>
    </a-spin>

    <!-- ---------------- 推送 ---------------- -->
    <a-modal v-model:open="pushOpen" title="报告推送" :confirm-loading="pushing" @ok="submitPush">
      <a-form layout="vertical">
        <a-form-item label="推送通道">
          <a-select v-model:value="pushChannels" mode="multiple">
            <a-select-option value="站内信">站内信</a-select-option>
            <a-select-option value="微信">微信</a-select-option>
            <a-select-option value="飞书">飞书</a-select-option>
            <a-select-option value="邮件">邮件</a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons-vue'
import BaseChart from '@/components/BaseChart.vue'
import { aiApi } from '@/api'

const route = useRoute()
const router = useRouter()
const reportId = route.params.id

const loading = ref(false)
const asking = ref(false)
const pushing = ref(false)
const report = reactive({})
const followUps = ref([])
const question = ref('')
const pushOpen = ref(false)
const pushChannels = ref(['站内信'])
const compare = ref(null)

const metricRows = computed(() => {
  const m = report.content?.metrics || {}
  const keys = [
    '工单总数',
    '待办工单',
    '已办工单',
    '完成率(%)',
    '逾期工单',
    '逾期率(%)',
    '故障总数',
    '待核查故障',
    '危急故障',
    '巡检记录数',
    '巡检异常记录',
    '巡检异常率(%)',
    '站点总数',
    '充电桩总数',
    '离线充电桩',
  ]
  return keys.filter((k) => m[k] !== undefined).map((k) => ({ label: k, value: m[k] }))
})

function toStaticUrl(p) {
  if (!p) return null
  return String(p).replace(/\\/g, '/').replace(/^.*?data\//, '/static/data/')
}
const reportHtmlUrl = computed(() => toStaticUrl(report.html_url))
const reportPdfUrl = computed(() => toStaticUrl(report.file_url))

/** 极简 Markdown 渲染（覆盖报告语法：标题/表格/列表/引用/加粗） */
function renderMarkdown(text) {
  if (!text) return ''
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s) =>
    s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`(.+?)`/g, '<code>$1</code>')

  const lines = esc(text).split('\n')
  const out = []
  let inTable = false
  let inList = false

  const closeAll = () => {
    if (inTable) {
      out.push('</table>')
      inTable = false
    }
    if (inList) {
      out.push('</ul>')
      inList = false
    }
  }

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) {
      closeAll()
      continue
    }

    if (line.startsWith('|') && line.endsWith('|')) {
      const cells = line.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue
      if (!inTable) {
        closeAll()
        out.push('<table>')
        inTable = true
        out.push('<tr>' + cells.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr>')
      } else {
        out.push('<tr>' + cells.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>')
      }
      continue
    }

    closeAll()

    if (line === '---') {
      out.push('<hr>')
    } else if (/^#{1,4}\s+/.test(line)) {
      const level = line.match(/^#+/)[0].length
      out.push(`<h${level}>${inline(line.replace(/^#+\s+/, ''))}</h${level}>`)
    } else if (line.startsWith('> ')) {
      out.push(`<blockquote>${inline(line.slice(2))}</blockquote>`)
    } else if (/^[-*]\s+/.test(line)) {
      out.push('<ul>')
      inList = true
      out.push(`<li>${inline(line.replace(/^[-*]\s+/, ''))}</li>`)
      out.push('</ul>')
      inList = false
    } else {
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  closeAll()
  return out.join('')
}

const renderedMarkdown = computed(() => renderMarkdown(report.markdown || ''))

const deltaColumns = [
  { title: '指标', dataIndex: 'label' },
  { title: '本期', dataIndex: 'current', width: 100 },
  { title: '上期', dataIndex: 'previous', width: 100 },
  { title: '变化', key: 'delta', width: 110 },
]

const deltaRows = computed(() => {
  const d = compare.value?.deltas || {}
  return Object.entries(d).map(([label, v]) => ({
    label,
    current: v.current,
    previous: v.previous,
    delta: v.delta,
  }))
})

const compareOption = computed(() => {
  const series = compare.value?.series || []
  return {
    color: ['#2f6fb5', '#52c41a', '#f5222d'],
    tooltip: { trigger: 'axis' },
    legend: { data: ['工单总数', '已办工单', '逾期工单'], top: 0 },
    grid: { left: 44, right: 20, top: 40, bottom: 36 },
    xAxis: {
      type: 'category',
      data: series.map((s) => (s.period_start || '').slice(5)),
      axisLabel: { fontSize: 11 },
    },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '工单总数', type: 'line', smooth: true, data: series.map((s) => s['工单总数']) },
      { name: '已办工单', type: 'line', smooth: true, data: series.map((s) => s['已办工单']) },
      { name: '逾期工单', type: 'line', smooth: true, data: series.map((s) => s['逾期工单']) },
    ],
  }
})

async function load() {
  loading.value = true
  try {
    const res = await aiApi.reportDetail(reportId)
    Object.assign(report, res.data || {})
  } finally {
    loading.value = false
  }
}

async function ask() {
  if (!question.value.trim()) {
    message.warning('请输入问题')
    return
  }
  asking.value = true
  try {
    const res = await aiApi.reportFollowUp(reportId, { question: question.value, use_llm: true })
    followUps.value.unshift(res.data)
    question.value = ''
  } finally {
    asking.value = false
  }
}

async function loadCompare() {
  try {
    const res = await aiApi.reportCompare(report.report_type || 'daily', { limit: 8 })
    compare.value = res.data
    message.success('已加载历史对比')
  } catch {
    compare.value = null
  }
}

async function submitPush() {
  pushing.value = true
  try {
    const res = await aiApi.reportPush(reportId, { channels: pushChannels.value })
    message.success(`已推送到 ${res.data.pushed} 人`)
    pushOpen.value = false
    load()
  } finally {
    pushing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.suggestion {
  border-left: 3px solid #2f6fb5;
  padding: 6px 0 6px 10px;
  margin-bottom: 12px;
}

.suggestion-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.suggestion-body {
  font-size: 12px;
  color: #646a73;
  line-height: 1.8;
}

.followup {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fafbfc;
}

.followup-q {
  font-weight: 600;
  color: #1f4e79;
  margin-bottom: 8px;
}

.followup-a {
  font-size: 13px;
  line-height: 1.9;
}

.followup-refs {
  font-size: 11px;
  color: #a0a6ad;
  margin-top: 8px;
}
</style>
