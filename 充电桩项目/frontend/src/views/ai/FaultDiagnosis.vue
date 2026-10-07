<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><ExperimentOutlined /> 智能故障诊断</h2>
        <div class="page-subtitle">
          RAG 知识库 + 设备手册 + 历史工单根因分析（PDF 3.11 智能故障诊断 Agent）
        </div>
      </div>
      <a-tag :color="llmReady ? 'purple' : 'orange'">
        {{ llmReady ? 'LLM 增强已启用' : '规则引擎模式' }}
      </a-tag>
    </div>

    <a-row :gutter="[14, 14]">
      <!-- ---------------- 输入 ---------------- -->
      <a-col :xs="24" :lg="8">
        <a-card title="诊断输入" size="small" :bordered="false">
          <a-form layout="vertical" :model="form">
            <a-form-item label="选择已有故障（可选）">
              <a-select
                v-model:value="form.fault_id"
                allow-clear
                show-search
                placeholder="从待核查故障中选择"
                :filter-option="filterFault"
                @change="onFaultChange"
              >
                <a-select-option v-for="f in faultOptions" :key="f.id" :value="f.id">
                  {{ f.fault_no }} · {{ f.fault_type || '未分类' }} · {{ f.fault_level }}
                </a-select-option>
              </a-select>
            </a-form-item>

            <a-divider style="margin: 4px 0 14px">
              <span class="text-muted" style="font-size: 12px">或手工描述故障</span>
            </a-divider>

            <a-form-item label="故障类型">
              <a-select v-model:value="form.fault_type" allow-clear placeholder="选择或输入">
                <a-select-option v-for="t in FAULT_TYPES" :key="t" :value="t">{{ t }}</a-select-option>
              </a-select>
            </a-form-item>

            <a-form-item label="资产编码">
              <a-input v-model:value="form.pile_asset_code" placeholder="选填，如 CP0010001" />
            </a-form-item>

            <a-form-item label="故障现象描述" required>
              <a-textarea
                v-model:value="form.description"
                :rows="5"
                placeholder="例如：充电功率仅能维持 30kW，桩体报 E05 故障码，散热风扇声音异常"
              />
            </a-form-item>

            <a-space>
              <a-button type="primary" :loading="loading" @click="diagnose">
                <template #icon><ExperimentOutlined /></template>
                开始诊断
              </a-button>
              <a-button @click="askSuggest" :loading="suggestLoading">生成运维建议</a-button>
            </a-space>
          </a-form>
        </a-card>

        <a-card
          v-if="diagnosis.matched_category"
          title="系统判定"
          size="small"
          :bordered="false"
          style="margin-top: 14px"
        >
          <a-descriptions :column="1" size="small">
            <a-descriptions-item label="根因类别">
              <a-tag color="blue">{{ diagnosis.matched_category }}</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="置信度">
              <a-progress
                :percent="Math.round((diagnosis.confidence || 0) * 100)"
                size="small"
                :stroke-color="confidenceColor"
              />
            </a-descriptions-item>
            <a-descriptions-item label="SLA 时限">
              {{ diagnosis.sla_hours }} 小时
            </a-descriptions-item>
            <a-descriptions-item label="分析方式">
              <a-tag :color="llmUsed ? 'purple' : 'orange'">
                {{ llmUsed ? 'RAG + LLM' : '规则引擎（LLM 降级）' }}
              </a-tag>
            </a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>

      <!-- ---------------- 结果 ---------------- -->
      <a-col :xs="24" :lg="16">
        <a-spin :spinning="loading">
          <a-empty v-if="!diagnosis.matched_category" description="尚未诊断，请在左侧输入故障信息" />

          <template v-else>
            <a-row :gutter="[14, 14]">
              <a-col :xs="24" :md="12">
                <a-card title="可能根因（按可能性排序）" size="small" :bordered="false">
                  <a-list :data-source="diagnosis.possible_causes || []" size="small">
                    <template #renderItem="{ item, index }">
                      <a-list-item>
                        <a-badge
                          :count="index + 1"
                          :number-style="{ backgroundColor: '#f5222d' }"
                          style="margin-right: 10px"
                        />
                        {{ item }}
                      </a-list-item>
                    </template>
                  </a-list>
                </a-card>
              </a-col>

              <a-col :xs="24" :md="12">
                <a-card title="现场检查项" size="small" :bordered="false">
                  <a-list :data-source="diagnosis.checks || []" size="small">
                    <template #renderItem="{ item }">
                      <a-list-item>
                        <CheckCircleOutlined style="color: #2f6fb5; margin-right: 8px" />
                        {{ item }}
                      </a-list-item>
                    </template>
                  </a-list>
                </a-card>
              </a-col>
            </a-row>

            <a-card title="建议处置措施" size="small" :bordered="false" style="margin-top: 14px">
              <a-list :data-source="diagnosis.actions || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <ToolOutlined style="color: #52c41a; margin-right: 8px" />
                    {{ item }}
                  </a-list-item>
                </template>
              </a-list>
            </a-card>

            <!-- LLM 分析 -->
            <a-card
              v-if="diagnosis.llm_analysis"
              title="LLM 深度分析"
              size="small"
              :bordered="false"
              class="ai-panel"
              style="margin-top: 14px"
            >
              <div class="report-body" v-html="renderMarkdown(diagnosis.llm_analysis)" />
            </a-card>

            <!-- 知识库引用 -->
            <a-card
              v-if="(diagnosis.references || []).length"
              title="知识库引用（RAG 检索命中）"
              size="small"
              :bordered="false"
              style="margin-top: 14px"
            >
              <a-list :data-source="diagnosis.references" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #title>
                        《{{ item.title }}》
                        <a-tag color="blue" style="margin-left: 6px">{{ item.category }}</a-tag>
                      </template>
                      <template #description>
                        相关度 {{ item.score }}
                        <span v-if="item.tags?.length">　标签：{{ item.tags.join('、') }}</span>
                      </template>
                    </a-list-item-meta>
                  </a-list-item>
                </template>
              </a-list>
            </a-card>

            <!-- 运维建议 -->
            <a-card
              v-if="suggestions.length"
              title="智能运维建议（含责任角色与时限）"
              size="small"
              :bordered="false"
              style="margin-top: 14px"
            >
              <a-table
                :columns="suggestColumns"
                :data-source="suggestions"
                row-key="title"
                size="small"
                :pagination="false"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'priority'">
                    <a-tag :color="{ 高: 'red', 中: 'orange', 低: 'default' }[record.priority]">
                      {{ record.priority }}
                    </a-tag>
                  </template>
                </template>
              </a-table>

              <div v-if="llmSuggestions" class="report-body" style="margin-top: 14px" v-html="renderMarkdown(llmSuggestions)" />
            </a-card>
          </template>
        </a-spin>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  CheckCircleOutlined,
  ExperimentOutlined,
  ToolOutlined,
} from '@ant-design/icons-vue'
import { aiApi, faultApi } from '@/api'

const FAULT_TYPES = [
  '充电枪故障',
  '通信故障',
  '计费异常',
  '功率模块故障',
  '急停按钮异常',
  '绝缘监测报警',
  '屏幕显示异常',
  '刷卡模块故障',
]

const loading = ref(false)
const suggestLoading = ref(false)
const llmReady = ref(false)
const llmUsed = ref(false)
const diagnosis = reactive({})
const suggestions = ref([])
const llmSuggestions = ref('')
const faultOptions = ref([])

const form = reactive({
  fault_id: undefined,
  fault_type: undefined,
  pile_asset_code: '',
  description: '',
})

const suggestColumns = [
  { title: '措施', dataIndex: 'title', ellipsis: true },
  { title: '优先级', key: 'priority', width: 90 },
  { title: '责任角色', dataIndex: 'owner', width: 110 },
  { title: '时限(小时)', dataIndex: 'deadline_hours', width: 100 },
]

const confidenceColor = computed(() => {
  const c = diagnosis.confidence || 0
  if (c >= 0.8) return '#52c41a'
  if (c >= 0.6) return '#faad14'
  return '#f5222d'
})

function filterFault(input, option) {
  const text = option?.children?.[0]?.children || option?.label || ''
  return String(text).toLowerCase().includes(String(input).toLowerCase())
}

function onFaultChange(id) {
  const f = faultOptions.value.find((x) => x.id === id)
  if (!f) return
  form.fault_type = f.fault_type
  form.description = f.description
  form.pile_asset_code = f.pile_asset_code
}

/** 极简 Markdown 渲染（覆盖 LLM 输出常用语法） */
function renderMarkdown(text) {
  if (!text) return ''
  const esc = (s) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const lines = esc(text).split('\n')
  const out = []
  let inList = false
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      continue
    }
    const bold = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    if (/^[-*]\s+/.test(bold)) {
      if (!inList) {
        out.push('<ul>')
        inList = true
      }
      out.push(`<li>${bold.replace(/^[-*]\s+/, '')}</li>`)
    } else if (/^#{1,4}\s+/.test(bold)) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      const level = bold.match(/^#+/)[0].length + 1
      out.push(`<h${level}>${bold.replace(/^#+\s+/, '')}</h${level}>`)
    } else {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      out.push(`<p>${bold}</p>`)
    }
  }
  if (inList) out.push('</ul>')
  return out.join('')
}

async function diagnose() {
  if (!form.fault_id && !form.description) {
    message.warning('请选择已有故障，或填写故障现象描述')
    return
  }
  loading.value = true
  try {
    const res = await aiApi.diagnoseFault({ ...form })
    Object.assign(diagnosis, res.data?.diagnosis || {})
    llmUsed.value = Boolean(res.data?.llm_used)
    suggestions.value = []
    llmSuggestions.value = ''
    if (!llmUsed.value && res.data?.llm_error) {
      message.info(`LLM 未启用，已使用规则引擎：${res.data.llm_error}`)
    }
  } finally {
    loading.value = false
  }
}

async function askSuggest() {
  if (!form.fault_id && !form.description) {
    message.warning('请先填写故障信息')
    return
  }
  suggestLoading.value = true
  try {
    const res = await aiApi.maintenanceSuggest({
      fault_id: form.fault_id,
      fault_type: form.fault_type,
      diagnosis: form.description,
      use_llm: true,
    })
    suggestions.value = res.data?.suggestions || []
    llmSuggestions.value = res.data?.llm_suggestions || ''
    message.success('运维建议已生成')
  } finally {
    suggestLoading.value = false
  }
}

onMounted(async () => {
  try {
    const h = await aiApi.health()
    llmReady.value = h.data?.status === 'ok'
  } catch {
    llmReady.value = false
  }
  try {
    const res = await faultApi.list({ tab: '待核查', page: 1, page_size: 50 })
    faultOptions.value = res.data?.items || []
  } catch {
    faultOptions.value = []
  }
})
</script>
