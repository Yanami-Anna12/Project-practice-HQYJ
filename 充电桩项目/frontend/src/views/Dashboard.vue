<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><DashboardOutlined /> 运维首页看板</h2>
        <div class="page-subtitle">
          {{ periodLabel }}　·　数据权限：{{ store.dataScope }}
        </div>
      </div>
      <a-space>
        <a-select v-model:value="query.period" style="width: 108px" @change="load">
          <a-select-option value="day">今日</a-select-option>
          <a-select-option value="week">本周</a-select-option>
          <a-select-option value="month">本月</a-select-option>
          <a-select-option value="quarter">本季度</a-select-option>
          <a-select-option value="year">本年</a-select-option>
        </a-select>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 工单核心指标 ---------------- -->
    <a-row :gutter="[14, 14]">
      <a-col :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard label="工单总数" :value="wo.total" tone="primary" :icon="ProfileOutlined" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard label="待办工单" :value="wo.pending" tone="warning" :icon="ClockCircleOutlined" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard label="已办工单" :value="wo.done" tone="success" :icon="CheckCircleOutlined" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard
          label="完成率"
          :value="wo.completion_rate"
          suffix="%"
          tone="success"
          :icon="RiseOutlined"
        />
      </a-col>
      <a-col :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard
          label="逾期工单"
          :value="wo.overdue"
          tone="danger"
          :icon="ExclamationCircleOutlined"
        />
      </a-col>
      <a-col :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard
          label="逾期率"
          :value="wo.overdue_rate"
          suffix="%"
          tone="danger"
          :icon="FallOutlined"
        />
      </a-col>
    </a-row>

    <!-- ---------------- 故障 / 巡检 / 资产 ---------------- -->
    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col :xs="24" :md="8">
        <StatCard
          label="故障总数"
          :value="fault.total"
          :hint="`待核查 ${fault.pending}　核查率 ${fault.verify_rate}%`"
          :icon="WarningOutlined"
        />
      </a-col>
      <a-col :xs="24" :md="8">
        <StatCard
          label="巡检记录"
          :value="inspection.total"
          :hint="`异常记录 ${inspection.abnormal_records}　异常率 ${inspection.abnormal_rate}%`"
          :icon="ScheduleOutlined"
        />
      </a-col>
      <a-col :xs="24" :md="8">
        <StatCard
          label="在管资产"
          :value="pileTotal"
          suffix="台充电桩"
          :hint="`离线 ${pileOffline} 台　充电枪 ${gunTotal} 把`"
          :icon="ThunderboltOutlined"
        />
      </a-col>
    </a-row>

    <!-- ---------------- 图表 ---------------- -->
    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col :xs="24" :lg="12">
        <a-card title="工单类型分布（5 类）" size="small" :bordered="false">
          <BaseChart :option="typeOption" :loading="loading" height="290px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :lg="12">
        <a-card title="时间状态分布（正常 / 紧急 / 逾期）" size="small" :bordered="false">
          <BaseChart :option="timeOption" :loading="loading" height="290px" />
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col :xs="24" :lg="14">
        <a-card title="近 30 天工单趋势" size="small" :bordered="false">
          <BaseChart :option="trendOption" :loading="trendLoading" height="280px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :lg="10">
        <a-card title="项目工单排名" size="small" :bordered="false">
          <BaseChart :option="projectRankOption" :loading="loading" height="280px" />
        </a-card>
      </a-col>
    </a-row>

    <!-- ---------------- 待核查故障卡片 ---------------- -->
    <a-card title="待核查故障（PDF 3.5 故障卡片）" size="small" :bordered="false" style="margin-top: 14px">
      <template #extra>
        <a class="clickable" @click="router.push('/faults')">查看全部</a>
      </template>
      <a-empty v-if="!faultCards.length" description="暂无待核查故障" />
      <a-row v-else :gutter="[12, 12]">
        <a-col v-for="f in faultCards" :key="f.id" :xs="24" :sm="12" :lg="8" :xl="6">
          <div class="fault-card" @click="router.push(`/faults/${f.id}`)">
            <div class="fault-card-head">
              <a-tag :color="levelColor(f.fault_level)">{{ f.fault_level }}</a-tag>
              <a-tag :color="statusColor(f.status)">{{ f.status }}</a-tag>
              <span v-if="f.sla_overdue" class="text-danger" style="font-size: 12px">
                SLA 超期
              </span>
            </div>
            <div class="fault-card-title">{{ f.fault_type || '未分类故障' }}</div>
            <div class="fault-card-line">站点：{{ f.station_name || '-' }}</div>
            <div class="fault-card-line">资产码：{{ f.pile_asset_code || '-' }}</div>
            <div class="fault-card-desc">{{ f.description || '无描述' }}</div>
          </div>
        </a-col>
      </a-row>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  DashboardOutlined,
  ExclamationCircleOutlined,
  FallOutlined,
  ProfileOutlined,
  ReloadOutlined,
  RiseOutlined,
  ScheduleOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import BaseChart from '@/components/BaseChart.vue'
import StatCard from '@/components/StatCard.vue'
import { adminApi, faultApi, statisticsApi } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const loading = ref(false)
const trendLoading = ref(false)
const query = reactive({ period: 'month' })

const wo = reactive({ total: 0, pending: 0, done: 0, overdue: 0, completion_rate: 0, overdue_rate: 0 })
const fault = reactive({ total: 0, pending: 0, verify_rate: 0 })
const inspection = reactive({ total: 0, abnormal_records: 0, abnormal_rate: 0 })
const typeDist = ref([])
const timeDist = ref([])
const projectRank = ref([])
const trend = ref([])
const faultCards = ref([])
const pileTotal = ref(0)
const pileOffline = ref(0)
const gunTotal = ref(0)

const periodLabel = computed(
  () =>
    ({
      day: '今日',
      week: '本周',
      month: '本月',
      quarter: '本季度',
      year: '本年',
    })[query.period] || '本月',
)

function levelColor(level) {
  return { 一般: 'green', 严重: 'orange', 危急: 'red' }[level] || 'default'
}
function statusColor(status) {
  return (
    {
      待上报: 'default',
      待核查: 'orange',
      核查通过: 'green',
      核查驳回: 'red',
    }[status] || 'default'
  )
}

// ---------------------------------------------------------------- 图表配置
const palette = ['#2f6fb5', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2']

const typeOption = computed(() => ({
  color: palette,
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, icon: 'circle' },
  series: [
    {
      type: 'pie',
      radius: ['45%', '68%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{c}' },
      data: typeDist.value.length
        ? typeDist.value
        : [{ name: '暂无数据', value: 0 }],
    },
  ],
}))

const timeOption = computed(() => ({
  color: ['#52c41a', '#faad14', '#f5222d'],
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 40, right: 20, top: 30, bottom: 30 },
  xAxis: {
    type: 'category',
    data: timeDist.value.map((i) => i.name),
    axisTick: { show: false },
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      type: 'bar',
      barWidth: '46%',
      data: timeDist.value.map((i, idx) => ({
        value: i.value,
        itemStyle: { color: ['#52c41a', '#faad14', '#f5222d'][idx] || '#2f6fb5' },
      })),
      label: { show: true, position: 'top' },
    },
  ],
}))

const projectRankOption = computed(() => {
  const items = [...projectRank.value].slice(0, 8).reverse()
  return {
    color: ['#2f6fb5'],
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 40, top: 16, bottom: 10, containLabel: true },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: {
      type: 'category',
      data: items.map((i) => (i.name || '').slice(0, 14)),
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        barWidth: '55%',
        data: items.map((i) => i.value),
        label: { show: true, position: 'right' },
        itemStyle: { borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

const trendOption = computed(() => ({
  color: ['#2f6fb5', '#52c41a'],
  tooltip: { trigger: 'axis' },
  legend: { data: ['工单数', '已办数'], right: 10, top: 0 },
  grid: { left: 40, right: 20, top: 40, bottom: 30 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: trend.value.map((i) => i.date.slice(5)),
    axisLabel: { fontSize: 11 },
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '工单数',
      type: 'line',
      smooth: true,
      areaStyle: { opacity: 0.12 },
      data: trend.value.map((i) => i.order_total),
    },
    {
      name: '已办数',
      type: 'line',
      smooth: true,
      areaStyle: { opacity: 0.12 },
      data: trend.value.map((i) => i.order_done),
    },
  ],
}))

// ---------------------------------------------------------------- 数据加载
async function load() {
  loading.value = true
  try {
    const res = await statisticsApi.dashboard({ period: query.period })
    const d = res.data || {}
    Object.assign(wo, d.work_order || {})
    Object.assign(fault, d.fault || {})
    Object.assign(inspection, d.inspection || {})
    typeDist.value = d.order_type_dist || []
    timeDist.value = d.time_status_dist || []
    projectRank.value = d.project_rank || []
  } finally {
    loading.value = false
  }
}

async function loadTrend() {
  trendLoading.value = true
  try {
    const res = await statisticsApi.trend({ days: 30 })
    trend.value = res.data?.series || []
  } finally {
    trendLoading.value = false
  }
}

async function loadFaultCards() {
  try {
    const res = await faultApi.cards({ limit: 8 })
    faultCards.value = (res.data || []).filter((f) => f.status === '待核查').slice(0, 8)
    if (!faultCards.value.length) faultCards.value = (res.data || []).slice(0, 8)
  } catch {
    faultCards.value = []
  }
}

async function loadAssets() {
  try {
    const [summary, piles] = await Promise.all([
      adminApi.pileStatusSummary(),
      adminApi.piles({ page: 1, page_size: 1 }),
    ])
    gunTotal.value = summary.data?.gun_total || 0
    pileTotal.value = piles.data?.meta?.total || 0
    const offline = (summary.data?.status_dist || []).find((i) => i.name === '离线')
    pileOffline.value = offline?.value || 0
  } catch {
    /* 忽略 */
  }
}

onMounted(() => {
  load()
  loadTrend()
  loadFaultCards()
  loadAssets()
})
</script>

<style scoped>
.fault-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s;
  height: 100%;
  background: #fff;
}

.fault-card:hover {
  border-color: #2f6fb5;
  box-shadow: 0 4px 14px rgba(47, 111, 181, 0.14);
}

.fault-card-head {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.fault-card-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 6px;
}

.fault-card-line {
  font-size: 12px;
  color: #646a73;
  line-height: 1.8;
}

.fault-card-desc {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
