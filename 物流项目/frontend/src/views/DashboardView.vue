<script setup>
/**
 * 调度看板（登录后的落地页）。
 *
 * ★ 首版这里只有《需求文档》里的静态条件与「待接入」占位；
 *   现在**顶部接入了真实数据**：今日趟次明细 + 执行完成情况 + 任务/趟次/在途/异常。
 *   底下那几块（车型规模、核心约束、规划看板）保持原样 —— 它们本来就是文档口径的说明，
 *   不是实时指标，改了反而误导。
 *
 * ★ 数据来源：`/api/mobile/manager/overview`（与小程序「今日看板」同一个接口）。
 *   路径带 `mobile` 只是因为历史原因，它的准入是 `scheduling:read`，
 *   admin / dispatcher / viewer 都能看，司机 403。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Van, Box, TakeawayBox, MagicStick, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

/* ---------------- 实时看板数据 ---------------- */
const overview = ref(null)
const loading = ref(false)
/** 看板日期：默认今天，可回看历史（演示数据是 10-10 那几天的） */
const boardDate = ref(toISO(new Date()))

function toISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await withError(() => api.fetchManagerOverview(boardDate.value))
    if (!overview.value) ElMessage.warning('看板数据加载失败，请检查后端是否在运行')
  } finally {
    loading.value = false
  }
}

/** 看板上的任务状态 → 中文（后端给的是 status 英文码） */
const TASK_STATUS_TEXT = {
  created: '待调度',
  running: '求解中',
  pending_confirm: '待确认',
  confirmed: '已确认',
  dispatched: '已下发',
  completed: '已完成',
  failed: '求解失败',
}

const taskStatusRows = computed(() => {
  const by = (overview.value && overview.value.tasks && overview.value.tasks.by_status) || {}
  return Object.keys(by)
    .map((k) => ({ key: k, label: TASK_STATUS_TEXT[k] || k, count: by[k] }))
    .filter((r) => r.count > 0)
    .sort((a, b) => b.count - a.count)
})

/** 趟次明细：四态文案与颜色（与小程序看板、司机端三色同一套语义） */
const BRIEF_STATE = {
  running: { text: '正在跑', type: 'primary' },
  accepted: { text: '已接单', type: 'warning' },
  pending: { text: '待确认', type: 'danger' },
  done: { text: '已完成', type: 'success' },
}
const briefState = (s) => BRIEF_STATE[s] || { text: s, type: 'info' }

const briefs = computed(() => (overview.value && overview.value.trip_briefs) || [])

/** 分布小结：各档各多少（顺序与后端排序一致：要盯的在前） */
const briefSummary = computed(() =>
  ['running', 'accepted', 'pending', 'done']
    .map((state) => ({ state, ...briefState(state), count: briefs.value.filter((t) => t.state === state).length }))
    .filter((s) => s.count > 0),
)

const completion = computed(() => (overview.value && overview.value.completion) || {})
const doneRate = computed(() =>
  completion.value.stores_total
    ? Math.round((completion.value.stores_done / completion.value.stores_total) * 100)
    : 0,
)

/** 深色/浅色标签：明细行「进度」列用 */
function briefProgress(row) {
  if (row.store_count && row.done_stores >= row.store_count) return { text: '已完成', type: 'success' }
  if (row.done_stores || row.arrived_stores) return { text: `进行中 ${row.done_stores}/${row.store_count}`, type: 'warning' }
  return { text: `未开始 0/${row.store_count}`, type: 'info' }
}

onMounted(loadOverview)

/** 现有条件（来源：需求文档 一.3） */
const fleet = [
  { type: '四米二', count: 28, min: 630, max: 800, trips: 2, split: '上午1 + 下午1', icon: Van, color: '#409eff' },
  { type: '大包', count: 3, min: 300, max: 420, trips: 2, split: '上午1 + 下午1', icon: Box, color: '#e6a23c' },
  { type: '小包', count: 9, min: 1, max: 300, trips: 4, split: '上午2 + 下午2', icon: TakeawayBox, color: '#67c23a' },
]

const totalVehicles = computed(() => fleet.reduce((s, f) => s + f.count, 0))
/** 理论日趟次上限：Σ(车辆数 × 每日趟次) */
const maxTrips = computed(() => fleet.reduce((s, f) => s + f.count * f.trips, 0))

/** 核心业务约束（来源：需求文档 一.4） */
const constraints = [
  { label: '发车规则', value: '达到最低装载量才发车' },
  { label: '时段规则', value: '上午门店上午送，下午门店下午送' },
  { label: '地形规则', value: '普通 / 中控 / 严控 × 全能去 / 大小包能去 / 小包能去' },
  { label: '线路规则', value: '门店与线路多对多，部分门店处于多线路交界' },
  { label: '货量不足', value: '优先保障大包、小包日出车次数' },
  { label: '车型优先', value: '多种派车方案优先用四米二' },
  { label: '动态调节', value: '不保障每天 28 / 3 / 9 台满勤' },
]

/** 规划中的看板（来源：需求文档 二.5） */
const plannedBoards = [
  '车辆出勤看板',
  '趟次达成看板',
  '装载率看板',
  '门店配送达成',
  '线路覆盖',
  '车型使用',
  '成本分析',
  '方案对比',
  '大包/小包保障达成',
  '四米二使用率',
  '动态车辆调节分析',
]

/** 智能调度 Agent 工作流（来源：需求文档 四.1） */
const workflow = [
  'load_task 加载任务',
  'data_perception 数据感知',
  'constraint_parse 约束解析',
  'rule_validation 规则校验',
  'plan_generation 生成多方案',
  'plan_scoring 方案评分',
  'plan_explanation 方案解释',
  'human_confirmation 人工确认',
  'dispatch_execution 下发执行',
  'report_generation 生成报告',
]

const quickLinks = [
  { title: '用户管理', path: '/system/users', permission: 'users:read' },
  { title: '角色管理', path: '/system/roles', permission: 'roles:read' },
  { title: '权限管理', path: '/system/permissions', permission: 'permissions:read' },
  { title: '字典管理', path: '/system/dicts', permission: 'dicts:read' },
  { title: '参数管理', path: '/system/params', permission: 'params:read' },
  { title: '日志管理', path: '/system/logs', permission: 'logs:read' },
]
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">调度看板</h2>
        <p class="page-desc">
          欢迎，{{ auth.user?.nickname }}。当前账号角色：
          <el-tag v-for="n in auth.roleNames" :key="n" size="small" effect="plain" class="mr">{{ n }}</el-tag>
        </p>
      </div>
      <div class="head-actions">
        <el-date-picker
          v-model="boardDate"
          type="date"
          value-format="YYYY-MM-DD"
          :clearable="false"
          style="width: 150px"
          @change="loadOverview"
        />
        <el-button :icon="Refresh" :loading="loading" @click="loadOverview">刷新</el-button>
      </div>
    </div>

    <!--
      ★ 趟次明细放最上面（用户要求「一进来就能看到」）：
        一行 = 一趟活（不是一家门店 —— 逐店列会把表格撑到几十行）。
        排序由后端给：正在跑 → 已接单 → 待确认 → 已完成，要盯的在最上面。
    -->
    <el-card shadow="never" class="mb" v-loading="loading">
      <template #header>
        <div class="card-head">
          <span class="card-title">今日趟次明细（{{ briefs.length }} 趟）</span>
          <span class="muted">
            {{ overview?.schedule_date || boardDate }} ·
            按 正在跑 → 已接单 → 待确认 → 已完成 排
          </span>
        </div>
      </template>

      <div v-if="briefSummary.length" class="brief-summary">
        <el-tag
          v-for="s in briefSummary"
          :key="s.state"
          :type="s.type"
          size="small"
          effect="plain"
          class="mr"
        >
          {{ s.text }} {{ s.count }}
        </el-tag>
      </div>

      <el-table :data="briefs" stripe size="small" max-height="420" empty-text="该日期没有已下发的趟次">
        <el-table-column label="车牌" width="110">
          <template #default="{ row }">
            <span class="perm-code">{{ row.plate_no || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="趟次" width="120">
          <template #default="{ row }">
            第 {{ row.trip_no }} 趟
            <el-tag size="small" effect="plain" class="ml-sm">{{ row.time_window }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="driver_name" label="司机" width="100">
          <template #default="{ row }">{{ row.driver_name || '未指派' }}</template>
        </el-table-column>
        <el-table-column label="门店进度" width="130">
          <template #default="{ row }">
            <el-tag :type="briefProgress(row).type" size="small" effect="plain">
              {{ briefProgress(row).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="briefState(row.state).type" size="small">
              {{ briefState(row.state).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="接单" width="80" align="center">
          <template #default="{ row }">
            <span v-if="row.accepted" class="ok-text">已接单</span>
            <span v-else class="muted">未接单</span>
          </template>
        </el-table-column>
        <el-table-column label="任务" min-width="150">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="router.push('/scheduling/tasks')">
              {{ row.task_code }}
            </el-link>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 执行完成情况 / 任务 / 趟次接单 / 在途 / 异常：真实数字 -->
    <el-row :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">今日任务</div>
          <div class="sum-value">{{ overview?.tasks?.total ?? '—' }}<span class="unit">个</span></div>
          <div class="sum-note">
            <template v-if="taskStatusRows.length">
              {{ taskStatusRows.map((r) => `${r.label} ${r.count}`).join(' · ') }}
            </template>
            <template v-else>该日期没有任务</template>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">已下发趟次</div>
          <div class="sum-value">{{ overview?.trips?.total ?? '—' }}<span class="unit">趟</span></div>
          <div class="sum-note">
            已接单 {{ overview?.trips?.accepted ?? 0 }} · 未接单 {{ overview?.trips?.pending ?? 0 }}
            （累计 {{ overview?.trips?.all_time ?? 0 }}）
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">执行完成情况</div>
          <div class="sum-value">
            {{ completion.trips_total || 0 }}<span class="unit">趟</span>
          </div>
          <div class="sum-note">
            已完成 {{ completion.finished || 0 }} · 正在跑 {{ completion.running || 0 }} ·
            未出车 {{ completion.not_started || 0 }}
          </div>
          <el-progress
            :percentage="doneRate"
            :stroke-width="10"
            :color="doneRate === 100 ? '#67c23a' : '#409eff'"
            class="mt-sm"
          />
          <div class="sum-note">
            门店完成度 {{ completion.stores_done || 0 }}/{{ completion.stores_total || 0 }} 家
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">在途车辆 / 异常</div>
          <div class="sum-value">
            {{ overview?.vehicles?.in_transit ?? '—' }}<span class="unit">台在途</span>
          </div>
          <div class="sum-note">
            共 {{ overview?.vehicles?.total ?? 0 }} 台 ·
            <span :class="overview?.exceptions?.pending ? 'warn-text' : ''">
              待处理异常 {{ overview?.exceptions?.pending ?? 0 }}
            </span>
            条
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 车辆规模 -->
    <el-row :gutter="16">
      <el-col v-for="f in fleet" :key="f.type" :xs="24" :sm="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-main">
            <el-icon :size="34" :color="f.color"><component :is="f.icon" /></el-icon>
            <div>
              <div class="stat-label">{{ f.type }}</div>
              <div class="stat-value">
                {{ f.count }}<span class="unit">台</span>
              </div>
            </div>
          </div>
          <div class="stat-meta">
            <div>装载量 {{ f.min }} – {{ f.max }}</div>
            <div>日 {{ f.trips }} 趟（{{ f.split }}）</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 汇总（车型规模来自需求文档，不是实时数据） -->
    <el-row :gutter="16" class="mt">
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">车辆总数</div>
          <div class="sum-value">{{ totalVehicles }}<span class="unit">台</span></div>
          <div class="sum-note">四米二 28 + 大包 3 + 小包 9</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">理论日趟次上限</div>
          <div class="sum-value">{{ maxTrips }}<span class="unit">趟</span></div>
          <div class="sum-note">28×2 + 3×2 + 9×4，实际按动态车辆调节</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">今日已下发趟次</div>
          <div class="sum-value">
            {{ overview?.trips?.total ?? '—' }}<span class="unit">趟</span>
          </div>
          <div class="sum-note">
            相对理论上限的 {{ maxTrips ? Math.round(((overview?.trips?.total || 0) / maxTrips) * 100) : 0 }}%
            —— 不保障每天满勤，按当日货量动态调节
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <!-- 核心业务约束 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">核心业务约束</span>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item v-for="c in constraints" :key="c.label" :label="c.label">
              {{ c.value }}
            </el-descriptions-item>
          </el-descriptions>
          <div class="source-note">来源：需求文档 一.4</div>
        </el-card>
      </el-col>

      <!-- 规划看板 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">报表与看板（规划中）</span>
          </template>
          <div class="board-tags">
            <el-tag v-for="b in plannedBoards" :key="b" size="small" effect="plain" class="mr">
              {{ b }}
            </el-tag>
          </div>
          <el-alert type="info" :closable="false" class="mt">
            <template #title>
              这些看板需要调度任务与执行回传数据，属于后续模块。
              当前可在「智能调度 Agent → 调度任务」查看规划的页面入口。
            </template>
          </el-alert>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <!-- 工作流 -->
      <el-col :xs="24" :lg="14">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">
              <el-icon><MagicStick /></el-icon>
              智能调度 Agent 工作流
            </span>
          </template>
          <div class="flow">
            <div v-for="(step, i) in workflow" :key="step" class="flow-step">
              <span class="flow-index">{{ i + 1 }}</span>
              <span class="flow-text">{{ step }}</span>
            </div>
          </div>
          <div class="source-note">来源：需求文档 四.1（LangGraph 节点）</div>
        </el-card>
      </el-col>

      <!-- 快捷入口 -->
      <el-col :xs="24" :lg="10">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">系统管理快捷入口</span>
          </template>
          <div class="quick-links">
            <el-button
              v-for="l in quickLinks"
              :key="l.path"
              v-permission="l.permission"
              class="quick-btn"
              @click="router.push(l.path)"
            >
              {{ l.title }}
            </el-button>
          </div>
          <el-alert v-if="!auth.has('users:read')" type="warning" :closable="false" class="mt">
            <template #title>
              当前账号没有系统管理权限，所以侧边栏不会出现「系统管理」分组。
              这是权限驱动的菜单裁剪，不是页面出错。
            </template>
          </el-alert>
          <div v-else class="source-note">
            按钮受 <code class="perm-code">v-permission</code> 指令控制，无权限时直接不渲染。
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
/* 页头右侧：日期 + 刷新（看板可以回看历史日期） */
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.muted {
  color: #909399;
  font-size: 12px;
}

.ok-text {
  color: #67c23a;
}

.warn-text {
  color: #e6a23c;
}

.mb {
  margin-bottom: 16px;
}

.mr {
  margin-right: 6px;
}

.ml-sm {
  margin-left: 4px;
}

.mt-sm {
  margin-top: 8px;
}

/* 趟次明细顶部的分布小结 */
.brief-summary {
  margin-bottom: 10px;
}

.stat-card {
  margin-bottom: 16px;
}

.stat-main {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
}

.unit {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
  margin-left: 3px;
}

.stat-meta {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e4e7ed;
  font-size: 12px;
  color: #606266;
  line-height: 1.9;
}

.sum-card {
  margin-bottom: 16px;
  text-align: center;
}

.sum-label {
  font-size: 13px;
  color: #909399;
}

.sum-value {
  font-size: 28px;
  font-weight: 600;
  margin: 4px 0;
}

.sum-value.pending {
  font-size: 18px;
  color: #e6a23c;
}

.sum-note {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.card-title {
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.board-tags {
  display: flex;
  flex-wrap: wrap;
}

.source-note {
  margin-top: 10px;
  font-size: 11px;
  color: #c0c4cc;
}

.flow {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.flow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
}

.flow-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 11px;
  flex-shrink: 0;
}

.flow-text {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-size: 12px;
  color: #303133;
}

.quick-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-btn {
  margin-left: 0;
}
</style>
