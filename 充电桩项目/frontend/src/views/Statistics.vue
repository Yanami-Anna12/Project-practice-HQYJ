<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><BarChartOutlined /> 统计分析与看板</h2>
        <div class="page-subtitle">
          {{ periodText }}　·　工单统计 · 5 类分布 · 逾期率 · 项目与站点排名
        </div>
      </div>
      <a-space>
        <a-select v-model:value="query.period" style="width: 110px" @change="loadAll">
          <a-select-option value="day">今日</a-select-option>
          <a-select-option value="week">本周</a-select-option>
          <a-select-option value="month">本月</a-select-option>
          <a-select-option value="quarter">本季度</a-select-option>
          <a-select-option value="year">本年</a-select-option>
        </a-select>
        <a-button :loading="loading" @click="loadAll">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button @click="exportData">
          <template #icon><ExportOutlined /></template>
          导出统计
        </a-button>
      </a-space>
    </div>

    <a-row :gutter="[14, 14]">
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="工单总数" :value="wo.total" tone="primary" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="待办工单" :value="wo.pending" tone="warning" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="已办工单" :value="wo.done" tone="success" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="完成率" :value="wo.completion_rate" suffix="%" tone="success" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="逾期工单" :value="wo.overdue" tone="danger" />
      </a-col>
      <a-col :xs="12" :sm="8" :md="4">
        <StatCard label="逾期率" :value="wo.overdue_rate" suffix="%" tone="danger" />
      </a-col>
    </a-row>

    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col :xs="24" :lg="8">
        <a-card title="5 种工单数量分布" size="small" :bordered="false">
          <BaseChart :option="typeOption" :loading="loading" height="300px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :lg="8">
        <a-card title="时间状态分布" size="small" :bordered="false">
          <BaseChart :option="timeOption" :loading="loading" height="300px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :lg="8">
        <a-card title="故障 / 巡检概览" size="small" :bordered="false">
          <BaseChart :option="faultInspOption" :loading="loading" height="300px" />
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col :xs="24" :lg="12">
        <a-card title="项目工单排名" size="small" :bordered="false">
          <BaseChart :option="projectRankOption" :loading="loading" height="320px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :lg="12">
        <a-card title="站点消缺工单排名" size="small" :bordered="false">
          <BaseChart :option="defectRankOption" :loading="loading" height="320px" />
        </a-card>
      </a-col>
    </a-row>

    <a-card title="统计日报趋势（近 30 天）" size="small" :bordered="false" style="margin-top: 14px">
      <BaseChart :option="dailyTrendOption" :loading="trendLoading" height="320px" />
    </a-card>

    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <a-col :xs="24" :lg="12">
        <a-card title="项目排名明细" size="small" :bordered="false">
          <a-table
            :columns="rankColumns"
            :data-source="data.project_rank || []"
            row-key="name"
            size="small"
            :pagination="false"
          />
        </a-card>
      </a-col>
      <a-col :xs="24" :lg="12">
        <a-card title="站点消缺排名明细" size="small" :bordered="false">
          <a-table
            :columns="rankColumns"
            :data-source="data.defect_station_rank || []"
            row-key="name"
            size="small"
            :pagination="false"
          />
        </a-card>
      </a-col>
    </a-row>

    <!-- ---------------- 导出进度 ---------------- -->
    <a-modal v-model:open="exportOpen" title="统计数据导出" :footer="null" :closable="!exporting">
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
import { message } from 'ant-design-vue'
import { BarChartOutlined, ExportOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import BaseChart from '@/components/BaseChart.vue'
import StatCard from '@/components/StatCard.vue'
import { exportApi, statisticsApi } from '@/api'

const loading = ref(false)
const trendLoading = ref(false)
const query = reactive({ period: 'month' })

const data = reactive({
  work_order: {},
  order_type_dist: [],
  time_status_dist: [],
  project_rank: [],
  defect_station_rank: [],
  fault: {},
  inspection: {},
  period: {},
})
const dailyTrend = ref([])

const wo = computed(() => data.work_order || {})
const periodText = computed(() =>
  data.period?.start ? `${data.period.start} ~ ${data.period.end}` : '本月',
)

const rankColumns = [
  { title: '排名', key: 'idx', width: 70, customRender: ({ index }) => index + 1 },
  { title: '名称', dataIndex: 'name', ellipsis: true },
  { title: '工单数', dataIndex: 'value', width: 100 },
]

const palette = ['#2f6fb5', '#52c41a', '#faad14', '#f5222d', '#722ed1']

const typeOption = computed(() => ({
  color: palette,
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, icon: 'circle', textStyle: { fontSize: 11 } },
  series: [
    {
      type: 'pie',
      radius: ['42%', '66%'],
      center: ['50%', '43%'],
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{c}', fontSize: 11 },
      data: data.order_type_dist.length ? data.order_type_dist : [{ name: '暂无数据', value: 0 }],
    },
  ],
}))

const timeOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 40, right: 20, top: 30, bottom: 30 },
  xAxis: { type: 'category', data: data.time_status_dist.map((i) => i.name), axisTick: { show: false } },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      type: 'bar',
      barWidth: '46%',
      data: data.time_status_dist.map((i) => ({
        value: i.value,
        itemStyle: {
          color: { 正常: '#52c41a', 紧急: '#faad14', 逾期: '#f5222d' }[i.name] || '#2f6fb5',
        },
      })),
      label: { show: true, position: 'top' },
    },
  ],
}))

const faultInspOption = computed(() => ({
  tooltip: { trigger: 'item' },
  legend: { bottom: 0, icon: 'circle', textStyle: { fontSize: 11 } },
  series: [
    {
      type: 'pie',
      radius: ['0%', '62%'],
      center: ['50%', '43%'],
      roseType: 'radius',
      itemStyle: { borderRadius: 5 },
      label: { fontSize: 11 },
      data: [
        { name: '故障总数', value: data.fault?.total || 0, itemStyle: { color: '#f5222d' } },
        { name: '故障已核查', value: data.fault?.verified || 0, itemStyle: { color: '#52c41a' } },
        { name: '巡检记录', value: data.inspection?.total || 0, itemStyle: { color: '#2f6fb5' } },
        {
          name: '巡检异常',
          value: data.inspection?.abnormal_records || 0,
          itemStyle: { color: '#faad14' },
        },
      ],
    },
  ],
}))

function rankOption(list) {
  const items = [...(list || [])].slice(0, 10).reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 46, top: 16, bottom: 10, containLabel: true },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: {
      type: 'category',
      data: items.map((i) => (i.name || '').slice(0, 16)),
      axisTick: { show: false },
      axisLabel: { fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        barWidth: '55%',
        data: items.map((i) => i.value),
        label: { show: true, position: 'right' },
        itemStyle: { borderRadius: [0, 4, 4, 0], color: '#2f6fb5' },
      },
    ],
  }
}

const projectRankOption = computed(() => rankOption(data.project_rank))
const defectRankOption = computed(() => ({
  ...rankOption(data.defect_station_rank),
  series: [
    {
      type: 'bar',
      barWidth: '55%',
      data: [...(data.defect_station_rank || [])]
        .slice(0, 10)
        .reverse()
        .map((i) => i.value),
      label: { show: true, position: 'right' },
      itemStyle: { borderRadius: [0, 4, 4, 0], color: '#f5222d' },
    },
  ],
}))

const dailyTrendOption = computed(() => ({
  color: ['#2f6fb5', '#52c41a', '#f5222d'],
  tooltip: { trigger: 'axis' },
  legend: { data: ['工单总数', '已办工单', '逾期工单'], right: 10, top: 0 },
  grid: { left: 44, right: 22, top: 42, bottom: 30 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: dailyTrend.value.map((i) => i.date.slice(5)),
    axisLabel: { fontSize: 11 },
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '工单总数',
      type: 'line',
      smooth: true,
      areaStyle: { opacity: 0.1 },
      data: dailyTrend.value.map((i) => i.order_total),
    },
    {
      name: '已办工单',
      type: 'line',
      smooth: true,
      areaStyle: { opacity: 0.1 },
      data: dailyTrend.value.map((i) => i.order_done),
    },
    {
      name: '逾期工单',
      type: 'line',
      smooth: true,
      data: dailyTrend.value.map((i) => i.order_overdue),
    },
  ],
}))

async function load() {
  loading.value = true
  try {
    const res = await statisticsApi.dashboard({ period: query.period })
    Object.assign(data, res.data || {})
  } finally {
    loading.value = false
  }
}

async function loadTrend() {
  trendLoading.value = true
  try {
    const res = await statisticsApi.trend({ days: 30 })
    dailyTrend.value = res.data?.series || []
  } finally {
    trendLoading.value = false
  }
}

function loadAll() {
  load()
  loadTrend()
}

// ---------------------------------------------------------------- 导出
const exportOpen = ref(false)
const exporting = ref(false)
const exportTask = reactive({ progress: 0, status: '', message: '', file_name: '' })

async function exportData() {
  exportOpen.value = true
  exporting.value = true
  Object.assign(exportTask, { progress: 0, status: '', message: '正在创建导出任务…' })
  try {
    const res = await exportApi.createStatistics({ period: query.period })
    const final = await exportApi.poll(res.data.task_id, (t) => {
      Object.assign(exportTask, { progress: t.progress, status: t.status, message: t.message })
    })
    exportTask.file_name = final.file_name
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
    message.warning('未找到可下载的文件')
    return
  }
  await exportApi.download(latest.task_id, latest.file_name)
  message.success('已开始下载')
}

onMounted(loadAll)
</script>
