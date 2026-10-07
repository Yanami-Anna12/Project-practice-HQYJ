<script setup>
/**
 * 监控预警（需求 二.8）。
 *
 * ★ 本页只展示**真实可测**的指标。测不到的（API QPS、P95 延迟、
 *   Redis 命中率、MQ 堆积）明确标注「需外部监控栈采集」，
 *   而不是编一个数字 —— 假监控数据比没有监控更危险。
 *
 * ★ 预警不是随机生成的：每条都有明确的判断依据（未处理异常、
 *   调度失败、重排接近上限、求解耗时偏长、待确认过期、维保占比偏高等）。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh, Warning, Bell } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import EChart from '@/components/EChart.vue'

const loading = ref(false)
const metrics = ref(null)
const alerts = ref([])
const dashboard = ref(null)

async function load() {
  loading.value = true
  try {
    const [m, a, d] = await Promise.all([
      withError(() => api.fetchMonitorSystem()),
      withError(() => api.fetchMonitorAlerts()),
      withError(() => api.fetchMonitorDashboard()),
    ])
    metrics.value = m
    alerts.value = a || []
    dashboard.value = d
  } finally {
    loading.value = false
  }
}

const scheduling = computed(() => metrics.value?.scheduling || {})
const confirmation = computed(() => metrics.value?.confirmation || {})
const exception = computed(() => metrics.value?.exception || {})
const database = computed(() => metrics.value?.database || {})
const tables = computed(() => metrics.value?.tables || {})
const external = computed(() => metrics.value?.external_metrics || [])

const alertStats = computed(() => {
  const s = { error: 0, warning: 0, info: 0 }
  for (const a of alerts.value) s[a.level] = (s[a.level] || 0) + 1
  return s
})

/** 调度活动趋势 */
const trendOption = computed(() => {
  const t = dashboard.value?.trend || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['调度任务', '已下发', '失败', '平均耗时(ms)'] },
    grid: { left: 60, right: 70, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: t.map((x) => x.date) },
    yAxis: [
      { type: 'value', name: '任务数' },
      { type: 'value', name: '耗时(ms)' },
    ],
    series: [
      { name: '调度任务', type: 'bar', data: t.map((x) => x.tasks), itemStyle: { color: '#409eff' } },
      { name: '已下发', type: 'bar', data: t.map((x) => x.dispatched), itemStyle: { color: '#67c23a' } },
      { name: '失败', type: 'bar', data: t.map((x) => x.failed), itemStyle: { color: '#f56c6c' } },
      {
        name: '平均耗时(ms)',
        type: 'line',
        yAxisIndex: 1,
        data: t.map((x) => x.avg_duration_ms),
        itemStyle: { color: '#e6a23c' },
        smooth: true,
      },
    ],
  }
})

/** 表规模分布（只取前 6 大，避免图上太挤） */
const tableOption = computed(() => {
  const entries = Object.entries(tables.value)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 110, right: 40, top: 20, bottom: 30 },
    xAxis: { type: 'value', name: '行数' },
    yAxis: { type: 'category', data: entries.map((e) => e[0]).reverse() },
    series: [
      {
        type: 'bar',
        data: entries.map((e) => e[1]).reverse(),
        itemStyle: { color: '#409eff' },
        label: { show: true, position: 'right' },
      },
    ],
  }
})

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">监控预警</h2>
        <p class="page-desc">
          展示<strong>实际可测</strong>的运行指标与按真实数据推导的预警。
          需要外部监控栈采集的指标会明确标注，不伪造数字。需要
          <code class="perm-code">monitor:read</code>。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <!-- 预警概览 -->
    <el-row :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat" :class="{ 'has-error': alertStats.error }">
          <div class="stat-label">错误级预警</div>
          <div class="stat-value danger">{{ alertStats.error }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat" :class="{ 'has-warning': alertStats.warning }">
          <div class="stat-label">警告级预警</div>
          <div class="stat-value warn">{{ alertStats.warning }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">提示级预警</div>
          <div class="stat-value muted-value">{{ alertStats.info }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">未处理异常事件</div>
          <div class="stat-value" :class="exception.pending ? 'danger' : 'ok'">
            {{ exception.pending || 0 }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 预警清单 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="card-head">
          <span class="card-title">
            <el-icon><Bell /></el-icon>
            预警清单（{{ alerts.length }}）
          </span>
          <span class="muted">每条预警都有明确判断依据，非随机生成</span>
        </div>
      </template>

      <el-table v-if="alerts.length" :data="alerts" size="small">
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag
              :type="row.level === 'error' ? 'danger' : row.level === 'warning' ? 'warning' : 'info'"
              size="small"
            >
              {{ row.level === 'error' ? '错误' : row.level === 'warning' ? '警告' : '提示' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="170" />
        <el-table-column prop="message" label="说明" min-width="380" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <span class="perm-code">
              {{ String(row.occurred_at).replace('T', ' ').slice(0, 19) }}
            </span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="当前没有预警" />
    </el-card>

    <el-row :gutter="16" class="mb">
      <!-- 调度健康度 -->
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">调度健康度</span>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="调度任务总数">
              {{ scheduling.total_tasks || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="成功率">
              <el-progress
                :percentage="scheduling.success_rate || 0"
                :stroke-width="12"
                :color="(scheduling.success_rate || 0) >= 90 ? '#67c23a' : '#e6a23c'"
              />
            </el-descriptions-item>
            <el-descriptions-item label="失败任务">
              <span :class="{ danger: scheduling.failed_tasks }">
                {{ scheduling.failed_tasks || 0 }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="平均求解耗时">
              {{ scheduling.avg_duration_ms || 0 }} ms
            </el-descriptions-item>
            <el-descriptions-item label="最长求解耗时">
              {{ scheduling.max_duration_ms || 0 }} ms
            </el-descriptions-item>
            <el-descriptions-item label="人工确认次数">
              {{ confirmation.total || 0 }}（通过 {{ confirmation.approved || 0 }} /
              驳回 {{ confirmation.rejected || 0 }}）
            </el-descriptions-item>
            <el-descriptions-item label="确认驳回率">
              {{ confirmation.reject_rate || 0 }}%
            </el-descriptions-item>
            <el-descriptions-item label="异常事件">
              {{ exception.total || 0 }} 起（未处理 {{ exception.pending || 0 }}）
            </el-descriptions-item>
            <el-descriptions-item label="重排次数合计">
              {{ exception.replan_count || 0 }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <!-- 基础设施 -->
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">基础设施</span>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="数据库连通性">
              <el-tag :type="database.available ? 'success' : 'danger'" size="small">
                {{ database.available ? '正常' : '异常' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="数据库版本">
              <span class="perm-code">{{ database.version }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="连接串">
              <span class="perm-code">{{ database.url }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="LLM 方案解释">
              <el-tag :type="metrics?.llm?.enabled ? 'success' : 'info'" size="small">
                {{ metrics?.llm?.enabled ? '已启用' : '未配置（降级）' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="说明">
              <span class="muted">{{ metrics?.llm?.note }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <el-divider content-position="left">未采集的指标（需外部监控栈）</el-divider>
          <el-table :data="external" size="small" border>
            <el-table-column prop="name" label="指标" min-width="220" />
            <el-table-column prop="collector" label="应由谁采集" min-width="200" />
            <el-table-column label="状态" width="90">
              <template #default>
                <el-tag type="info" size="small" effect="plain">未接入</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div class="note">
            这三类指标需要 Prometheus + Grafana / LangSmith 等外部组件采集。
            本项目未引入这些中间件，所以不展示数字 —— 编造的监控数据比没有更危险。
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">调度活动趋势（最近 {{ dashboard?.days || 7 }} 天）</span>
          </template>
          <EChart :option="trendOption" height="300px" />
          <div v-if="!(dashboard?.trend || []).length" class="note">
            最近 {{ dashboard?.days || 7 }} 天没有调度任务，趋势图为空。
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">数据规模（前 6 大表）</span>
          </template>
          <EChart :option="tableOption" height="300px" />
        </el-card>
      </el-col>
    </el-row>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        <el-icon><Warning /></el-icon>
        预警阈值说明：重排「接近上限」按参数
        <code class="perm-code">scheduling.replan.max_count</code> 判定；
        求解「耗时偏长」阈值为 60 秒；「维保占比偏高」阈值为 20%。
        这些判断依据都写在 backend/app/services/monitor.py 里，可自行调整。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.card-title {
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.mb {
  margin-bottom: 16px;
}

.h-full {
  height: 100%;
}

.stat {
  text-align: center;
}

.stat.has-error {
  border: 1px solid #f56c6c;
}

.stat.has-warning {
  border: 1px solid #e6a23c;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
}

.stat-value.danger {
  color: #f56c6c;
}

.stat-value.warn {
  color: #e6a23c;
}

.stat-value.ok {
  color: #67c23a;
}

.stat-value.muted-value {
  color: #909399;
}

.danger {
  color: #f56c6c;
  font-weight: 600;
}

.note {
  margin-top: 10px;
  font-size: 11px;
  color: #909399;
  line-height: 1.7;
}
</style>
