<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><SafetyOutlined /> 智能风控</h2>
        <div class="page-subtitle">
          识别异常工单、异常故障、异常巡检、异常核销（PDF 3.11 智能风控 Agent）
        </div>
      </div>
      <a-space>
        <a-select v-model:value="scope" style="width: 140px">
          <a-select-option value="whole">全量检查</a-select-option>
          <a-select-option value="work_order">仅工单</a-select-option>
          <a-select-option value="fault">仅故障</a-select-option>
          <a-select-option value="inspection">仅巡检</a-select-option>
        </a-select>
        <a-select v-model:value="days" style="width: 120px">
          <a-select-option :value="7">近 7 天</a-select-option>
          <a-select-option :value="30">近 30 天</a-select-option>
          <a-select-option :value="90">近 90 天</a-select-option>
        </a-select>
        <a-button type="primary" :loading="loading" @click="run">
          <template #icon><SafetyOutlined /></template>
          开始风控检查
        </a-button>
      </a-space>
    </div>

    <a-row :gutter="[14, 14]">
      <a-col :xs="12" :sm="6">
        <StatCard label="风险总数" :value="result.total || 0" tone="primary" />
      </a-col>
      <a-col :xs="12" :sm="6">
        <StatCard label="高风险" :value="result.summary?.高 || 0" tone="danger" />
      </a-col>
      <a-col :xs="12" :sm="6">
        <StatCard label="中风险" :value="result.summary?.中 || 0" tone="warning" />
      </a-col>
      <a-col :xs="12" :sm="6">
        <StatCard label="低风险" :value="result.summary?.低 || 0" />
      </a-col>
    </a-row>

    <a-card :bordered="false" style="margin-top: 14px">
      <a-spin :spinning="loading">
        <a-empty v-if="!findings.length" description="尚未执行检查，或未发现风险项" />
        <a-table
          v-else
          :columns="columns"
          :data-source="findings"
          row-key="title"
          size="middle"
          :pagination="{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'level'">
              <a-tag :color="{ 高: 'red', 中: 'orange', 低: 'default' }[record.level]">
                {{ record.level }}
              </a-tag>
            </template>
            <template v-else-if="column.key === 'risk_type'">
              <a-tag color="blue">{{ record.risk_type }}</a-tag>
            </template>
            <template v-else-if="column.key === 'target'">
              <a
                v-if="record.target_type === 'work_order'"
                class="clickable"
                @click="router.push(`/work-orders/${record.target_id}`)"
              >
                查看工单
              </a>
              <a
                v-else-if="record.target_type === 'fault'"
                class="clickable"
                @click="router.push(`/faults/${record.target_id}`)"
              >
                查看故障
              </a>
              <span v-else class="mono text-muted" style="font-size: 11px">
                {{ (record.target_id || '').slice(0, 8) }}
              </span>
            </template>
          </template>
        </a-table>
      </a-spin>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { SafetyOutlined } from '@ant-design/icons-vue'
import StatCard from '@/components/StatCard.vue'
import { aiApi } from '@/api'

const router = useRouter()

const loading = ref(false)
const scope = ref('whole')
const days = ref(90)
const result = reactive({ total: 0, summary: {}, findings: [] })

const findings = computed(() => result.findings || [])

const columns = [
  { title: '风险等级', key: 'level', width: 100 },
  { title: '风险类型', key: 'risk_type', width: 120 },
  { title: '风险标题', dataIndex: 'title', ellipsis: true },
  { title: '详情', dataIndex: 'detail', ellipsis: true },
  { title: '处理建议', dataIndex: 'suggestion', ellipsis: true },
  { title: '关联对象', key: 'target', width: 100 },
]

async function run() {
  loading.value = true
  try {
    const res = await aiApi.riskCheck({ scope: scope.value, days: days.value })
    Object.assign(result, res.data || {})
  } finally {
    loading.value = false
  }
}

onMounted(run)
</script>
