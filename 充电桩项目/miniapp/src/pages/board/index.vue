<script setup>
/**
 * 掌上看板（管理端首页，底部导航的「看板」）。
 *
 * 数据来源：GET /statistics/dashboard?period=day|week|month
 *   后端**一次聚合**返回工单、故障、巡检、排名、趋势，前端刻意不拆成多次请求：
 *   弱网下多次往返既慢，几个数字还可能来自不同时刻，页面上会出现自相矛盾。
 *   充电桩状态与一线作业任务另有两个轻接口，它们失败只隐藏对应区块，
 *   不会把整张看板打成错误页（见 loadPileSummary / loadSubtasks）。
 *
 * ★★ 口径标注（后端既有行为，前端只是照实展示，不改口径）：
 *   · work_order.*  —— **本周期**口径（period=month 就是本月新建的工单，可能只有几条）；
 *   · fault.*       —— **累计**口径（全量故障总数，不随 period 变）；
 *   · inspection.*  —— **累计**口径。
 *   两者混在一页上最容易被人问「为什么工单 4 条、故障 30 条」，
 *   所以卡片标题直接写「本月工单」「累计故障」，页尾再补一行口径说明。
 *
 * ★ 只读页：没有任何写操作，数字全部原样来自后端（前端不做二次统计，
 *   少算一次就少一次和服务端不一致的机会）。
 */
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import { formatDate, percentText, pileStatusClass, taskStatusClass } from '@/utils/format'
import { accountProfile, errorText, requireLogin } from '@/utils/ui'

/** 周期切换（与后端 resolve_period 支持的取值一致） */
const PERIODS = [
  { key: 'day', label: '今日' },
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' },
]

/** 数据权限 → 一句人话（用表格而不是 if 链，加一种权限只加一行） */
const SCOPE_TEXT = {
  平台数据: '平台数据 → 下面所有数字都是全平台的',
  项目数据: '项目数据 → 只统计你负责的项目',
  站点数据: '站点数据 → 只统计你负责的站点',
  个人数据: '个人数据 → 只统计与你本人相关的数据',
}

const period = ref('month')
const dashboard = ref(null)
const pileSummary = ref(null)
/** 一线最近作业任务（拿不到就整块隐藏，见 loadSubtasks） */
const subtasks = ref([])
const loading = ref(false)
const errorMsg = ref('')

const periodLabel = computed(() => {
  const hit = PERIODS.filter((item) => item.key === period.value)[0]
  return hit ? hit.label : '本月'
})

/* ---------------- 主数字（全部来自后端聚合结果） ---------------- */
const workOrder = computed(() => (dashboard.value && dashboard.value.work_order) || {})
const fault = computed(() => (dashboard.value && dashboard.value.fault) || {})
const inspection = computed(() => (dashboard.value && dashboard.value.inspection) || {})

/** 当前周期的起止日期，用来给人交代「这些数字算的是哪一段」 */
const periodRange = computed(() => {
  const range = (dashboard.value && dashboard.value.period) || null
  if (!range) return ''
  return `${formatDate(range.start)} ~ ${formatDate(range.end)}`
})

/** 数据权限：优先用看板接口返回的（后端做数据过滤的最终依据），没有才退回本地账号画像 */
const scopeTip = computed(() => {
  const scope = (dashboard.value && dashboard.value.data_scope) || accountProfile().dataScope || ''
  return SCOPE_TEXT[scope] || scope || '未标注'
})

/** 本周期完全没有任何数据时给一句空态，而不是让用户对着一排 0 猜 */
const isEmpty = computed(
  () => !workOrder.value.total && !fault.value.total && !inspection.value.total
)

/* ---------------- 分布 / 排名 / 趋势 ---------------- */
const orderTypeDist = computed(() => (dashboard.value && dashboard.value.order_type_dist) || [])
const projectRank = computed(() => (dashboard.value && dashboard.value.project_rank) || [])
const defectRank = computed(() => (dashboard.value && dashboard.value.defect_station_rank) || [])

/**
 * 趋势只画最后 7 天。
 * ★ 后端按当前周期给「按天」序列（month 会给一整月），柱子一多就挤成一片看不出趋势；
 *   看板的用途是「一眼看出最近在涨还是在落」，所以取尾部 7 个点。
 */
const trend = computed(() => ((dashboard.value && dashboard.value.trend) || []).slice(-7))

/** 取一组数的最大值（空数组返回 0，给条形宽度做分母用） */
function maxOf(list) {
  return (list || []).reduce((acc, item) => {
    const n = Number(item) || 0
    return n > acc ? n : acc
  }, 0)
}

const typeMax = computed(() => maxOf(orderTypeDist.value.map((row) => row.value)))
const trendMax = computed(() => maxOf(trend.value.map((row) => row.value)))

/**
 * 条形宽度百分比。
 * ★ 必须防除零：某一类全是 0 时（例如本周期没有消缺工单）max 会是 0，
 *   直接除会得到 NaN，:style 里会渲染成非法宽度。
 */
function barWidth(value, max) {
  const m = Number(max) || 0
  if (m <= 0) return 0
  const v = Number(value) || 0
  return Math.max(0, Math.min(100, Math.round((v / m) * 100)))
}

/** 前三名给不同名次色（这是排名不是业务状态，所以不进 format.js 的状态配色表） */
const RANK_CLASS = ['rank-1', 'rank-2', 'rank-3']

function rankClass(index) {
  return RANK_CLASS[index] || 'rank-plain'
}

/* ---------------- 充电桩状态 ---------------- */
const PILE_STATUS_ORDER = ['运行', '故障', '停用']

/**
 * 固定按 运行/故障/停用 三档展示。
 * ★ 不直接渲染 status_dist：后端只返回有数据的档位（某档为 0 时整行消失），
 *   而「停用 0 台」本身就是管理者想确认的信息。
 */
const pileRows = computed(() => {
  const dist = (pileSummary.value && pileSummary.value.status_dist) || []
  const map = {}
  dist.forEach((row) => {
    map[row.name] = row.value
  })
  return PILE_STATUS_ORDER.map((name) => ({ name, value: Number(map[name]) || 0 }))
})

const pileMax = computed(() => maxOf(pileRows.value.map((row) => row.value)))
const gunTotal = computed(() => Number((pileSummary.value && pileSummary.value.gun_total) || 0))

/* ---------------- 加载 ---------------- */
async function loadPileSummary() {
  try {
    pileSummary.value = await api.fetchPileStatusSummary()
  } catch (err) {
    // 台账权限与看板权限是两码事：没有台账权限就只是不显示这一块
    pileSummary.value = null
    console.warn('[board] 充电桩状态汇总获取失败', err)
  }
}

/**
 * 一线最近作业任务。
 * ★ 个人数据权限的账号传 scope_all 也拿不到别人的任务，后端会返回空列表；
 *   这种情况下整块**隐藏**而不是显示一个空列表 —— 管理看板上挂一块空列表
 *   反而让人以为「今天没人干活」。
 */
async function loadSubtasks() {
  try {
    const data = await api.fetchMySubtasks({ pageSize: 5, scopeAll: true })
    subtasks.value = (data && data.items) || []
  } catch (err) {
    subtasks.value = []
    console.warn('[board] 一线作业任务不可见', err)
  }
}

/** 主看板走错误态 + 重试；两个附属接口各自兜底，不把整页拖垮 */
async function load() {
  if (!requireLogin()) return
  loading.value = true
  errorMsg.value = ''
  try {
    dashboard.value = await api.fetchDashboard({ period: period.value })
    await Promise.all([loadPileSummary(), loadSubtasks()])
  } catch (err) {
    dashboard.value = null
    pileSummary.value = null
    subtasks.value = []
    errorMsg.value = errorText(err, '加载看板失败')
  } finally {
    loading.value = false
  }
}

/** 切周期：同一个周期重复点不重发请求 */
function switchPeriod(key) {
  if (period.value === key) return
  period.value = key
  load()
}

/* ---------------- 跳转 ----------------
 * ★ 「工单管理」「故障管理」都是底部导航的一级页面，用 redirectTo 换页
 *   （保持栈深度 1，与点底部导航的效果一致）；
 *   「充电桩状态」是看板下的二级页，用 navigateTo 压栈，返回键能回到看板。
 */
function goOrders() {
  uni.redirectTo({ url: '/pages/board/orders' })
}

function goPiles() {
  uni.navigateTo({ url: '/pages/board/piles' })
}

function goFaults() {
  uni.redirectTo({ url: '/pages/fault/index' })
}

function goTaskDetail(id) {
  uni.navigateTo({ url: `/pages/tasks/detail?id=${id}` })
}

// onShow 而不是 onLoad：从工单/充电桩页返回时数字要是最新的
onShow(load)

onPullDownRefresh(async () => {
  await load()
  // ★ 必须调用，否则下拉的转圈会一直停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!-- 周期切换 -->
    <view class="chip-row">
      <view
        v-for="item in PERIODS"
        :key="item.key"
        class="chip"
        :class="period === item.key ? 'chip-active' : ''"
        @click="switchPeriod(item.key)"
      >
        {{ item.label }}
      </view>
    </view>

    <!-- 数据权限范围：看板最怕的是「以为看的是全平台其实只看得到自己站」 -->
    <view class="hint-bar">当前账号数据权限：{{ scopeTip }}</view>

    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <view class="btn btn-primary retry-btn" @click="load">重 试</view>
    </view>

    <template v-else-if="dashboard">
      <view v-if="isEmpty" class="empty">当前周期没有任何工单、故障与巡检记录</view>

      <!-- 待办提醒条：只在确实有事时才出现，天天挂着的告警等于没有告警 -->
      <view v-if="workOrder.overdue > 0" class="danger-bar">
        有 {{ workOrder.overdue }} 张工单已逾期，请尽快安排处理
      </view>
      <view v-if="workOrder.urgent > 0" class="warn-bar">
        有 {{ workOrder.urgent }} 张紧急工单待处理
      </view>
      <view v-if="fault.pending > 0" class="warn-bar">
        有 {{ fault.pending }} 条故障待核查
      </view>

      <!-- 工单四张主卡：标题写明是本周期口径 -->
      <view class="stat-grid">
        <view class="stat-card">
          <view class="stat-value stat-primary">{{ workOrder.total || 0 }}</view>
          <view class="stat-label">{{ periodLabel }}工单</view>
        </view>
        <view class="stat-card">
          <view class="stat-value" :class="workOrder.pending ? 'stat-warn' : ''">
            {{ workOrder.pending || 0 }}
          </view>
          <view class="stat-label">待办工单</view>
        </view>
      </view>
      <view class="stat-grid">
        <view class="stat-card">
          <view class="stat-value stat-done">{{ workOrder.done || 0 }}</view>
          <view class="stat-label">已完成</view>
        </view>
        <view class="stat-card">
          <view class="stat-value stat-primary">{{ percentText(workOrder.completion_rate) }}</view>
          <view class="stat-label">完成率</view>
        </view>
      </view>

      <!-- 故障与巡检：累计口径，标题里写清楚 -->
      <view class="stat-grid">
        <view class="stat-card">
          <view class="stat-value">{{ fault.total || 0 }}</view>
          <view class="stat-label">累计故障</view>
        </view>
        <view class="stat-card">
          <view class="stat-value" :class="fault.pending ? 'stat-warn' : ''">
            {{ fault.pending || 0 }}
          </view>
          <view class="stat-label">待核查故障</view>
        </view>
      </view>
      <view class="stat-grid">
        <view class="stat-card">
          <view class="stat-value stat-done">{{ percentText(fault.verify_rate) }}</view>
          <view class="stat-label">故障核查率</view>
        </view>
        <view class="stat-card">
          <view class="stat-value" :class="inspection.abnormal_records ? 'stat-danger' : ''">
            {{ percentText(inspection.abnormal_rate) }}
          </view>
          <view class="stat-label">巡检异常率</view>
        </view>
      </view>

      <view class="scope-note">
        口径：工单类数字按当前周期统计（{{ periodRange }}，逾期率
        {{ percentText(workOrder.overdue_rate) }}）；故障与巡检为累计口径
        （巡检共 {{ inspection.total || 0 }} 条，异常 {{ inspection.abnormal_records || 0 }} 条）。
      </view>

      <!-- 快捷入口 -->
      <view class="entry-grid">
        <view class="entry-item" @click="goOrders">
          <view class="entry-name">工单管理</view>
          <view class="entry-desc">{{ periodLabel }} {{ workOrder.total || 0 }} 张</view>
        </view>
        <view class="entry-item" @click="goPiles">
          <view class="entry-name">充电桩状态</view>
          <!-- 汇总没拉到时不要写「运行 0 台」——那是假数字，宁可只写「查看台账」 -->
          <view class="entry-desc">
            {{ pileSummary ? '运行 ' + pileRows[0].value + ' 台' : '查看台账' }}
          </view>
        </view>
        <view class="entry-item" @click="goFaults">
          <view class="entry-name">待核查故障</view>
          <view class="entry-desc">{{ fault.pending || 0 }} 条待核查</view>
        </view>
      </view>

      <!-- 工单类型分布（不引任何图表库，用全局的 dist-row 那套条形自己画） -->
      <view class="card">
        <view class="section-title">
          <text>工单类型分布</text>
          <text class="muted small">{{ periodLabel }}</text>
        </view>
        <view v-for="row in orderTypeDist" :key="row.name" class="dist-row">
          <text class="dist-name">{{ row.name }}</text>
          <view class="dist-bar-wrap">
            <view class="dist-bar" :style="{ width: barWidth(row.value, typeMax) + '%' }" />
          </view>
          <text class="dist-value">{{ row.value }}</text>
        </view>
        <view v-if="!typeMax" class="muted small">当前周期没有工单</view>
      </view>

      <!-- 近 7 天趋势：一排竖直柱子，手画不用图表库 -->
      <view class="card">
        <view class="section-title">
          <text>工单创建趋势</text>
          <text class="muted small">最近 {{ trend.length }} 天</text>
        </view>
        <view v-if="trend.length" class="trend-row">
          <view v-for="point in trend" :key="point.date" class="trend-col">
            <text class="trend-value">{{ point.value }}</text>
            <view class="trend-track">
              <view
                class="trend-bar"
                :style="{ height: barWidth(point.value, trendMax) + '%' }"
              />
            </view>
            <text class="trend-date">{{ formatDate(point.date).slice(5) }}</text>
          </view>
        </view>
        <view v-else class="muted small">当前周期没有工单创建记录</view>
      </view>

      <!-- 项目工单排名 -->
      <view class="card">
        <view class="section-title">
          <text>项目工单排名</text>
          <text class="muted small">前 {{ projectRank.length }} 名</text>
        </view>
        <view v-if="projectRank.length">
          <view v-for="(row, index) in projectRank" :key="row.project_id || index" class="rank-row">
            <text class="rank-badge" :class="rankClass(index)">{{ index + 1 }}</text>
            <text class="rank-name">{{ row.name }}</text>
            <text class="rank-value">{{ row.value }} 张</text>
          </view>
        </view>
        <view v-else class="muted small">当前周期没有工单</view>
      </view>

      <!-- 缺陷站点排名（消缺工单） -->
      <view class="card">
        <view class="section-title">
          <text>缺陷站点排名</text>
          <text class="muted small">按消缺工单</text>
        </view>
        <view v-if="defectRank.length">
          <view v-for="(row, index) in defectRank" :key="row.name || index" class="rank-row">
            <text class="rank-badge" :class="rankClass(index)">{{ index + 1 }}</text>
            <text class="rank-name">{{ row.name }}</text>
            <text class="rank-value">{{ row.value }} 张</text>
          </view>
        </view>
        <view v-else class="muted small">当前周期没有消缺工单</view>
      </view>

      <!-- 充电桩状态 -->
      <view v-if="pileSummary" class="card">
        <view class="section-title">
          <text>充电桩状态</text>
          <text class="section-more" @click="goPiles">查看全部 ›</text>
        </view>
        <view v-for="row in pileRows" :key="row.name" class="dist-row">
          <text class="dist-name">
            <text class="tag" :class="pileStatusClass(row.name)">{{ row.name }}</text>
          </text>
          <view class="dist-bar-wrap">
            <view class="dist-bar" :style="{ width: barWidth(row.value, pileMax) + '%' }" />
          </view>
          <text class="dist-value">{{ row.value }}</text>
        </view>
        <view class="muted small">以上三档合计覆盖 {{ gunTotal }} 把充电枪（桩上所有枪位）</view>
      </view>

      <!--
        一线在跑什么（管理动作）。
        ★ 拿不到数据（个人数据权限 / 无工单权限）时整块隐藏，不显示空列表。
        ★「更多」落到工单列表而不是作业任务列表：管理端没有独立的作业任务页面，
          子任务都挂在工单下，点进工单才看得到全貌。
      -->
      <template v-if="subtasks.length">
        <view class="section-title">
          <text>一线作业任务</text>
          <text class="section-more" @click="goOrders">按工单查看 ›</text>
        </view>
        <view
          v-for="item in subtasks"
          :key="item.id"
          class="card task-card"
          @click="goTaskDetail(item.id)"
        >
          <view class="task-head">
            <text class="task-station">{{ item.station_name || '未知站点' }}</text>
            <text class="tag" :class="taskStatusClass(item.status)">{{ item.status }}</text>
          </view>
          <view class="task-line muted">
            计划 {{ formatDate(item.plan_date) }} ·
            {{ item.assignee_name || '未指派' }} ·
            第 {{ item.sequence }} 项
          </view>
        </view>
      </template>

      <view class="foot-tip muted">
        看板只读，不会修改任何数据；数字来自后端一次聚合的结果
      </view>
    </template>

    <BottomNav />
  </view>
</template>

<style scoped>
/* 口径说明：比 .desc 更醒目一点，因为它承担「别把两种口径比大小」的说明责任 */
.scope-note {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 18rpx 24rpx;
  margin-bottom: 20rpx;
  color: #8a9099;
  font-size: 22rpx;
  line-height: 1.7;
}

.small {
  font-size: 22rpx;
}

/* 快捷入口：三个等宽可点区块（不用第三方组件） */
.entry-grid {
  display: flex;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.entry-item {
  flex: 1;
  background: #ffffff;
  border-radius: 16rpx;
  padding: 24rpx 12rpx;
  text-align: center;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.entry-name {
  font-size: 27rpx;
  font-weight: 600;
  color: #1677ff;
}

.entry-desc {
  font-size: 21rpx;
  color: #8a9099;
  margin-top: 8rpx;
}

/* 趋势柱：track 固定高、柱子从底部往上长 */
.trend-row {
  display: flex;
  align-items: flex-end;
  gap: 8rpx;
}

.trend-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.trend-value {
  font-size: 20rpx;
  color: #4b5563;
  margin-bottom: 6rpx;
}

.trend-track {
  width: 100%;
  height: 160rpx;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: #f7f8fa;
  border-radius: 8rpx;
  overflow: hidden;
}

.trend-bar {
  width: 60%;
  min-height: 4rpx;
  background: #1677ff;
  border-radius: 8rpx 8rpx 0 0;
}

.trend-date {
  font-size: 20rpx;
  color: #8a9099;
  margin-top: 8rpx;
}

/* 排名行 */
.rank-row {
  display: flex;
  align-items: center;
  padding: 12rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
  font-size: 26rpx;
}

.rank-row:last-child {
  border-bottom: none;
}

.rank-badge {
  width: 40rpx;
  height: 40rpx;
  line-height: 40rpx;
  border-radius: 20rpx;
  text-align: center;
  font-size: 22rpx;
  margin-right: 16rpx;
  flex-shrink: 0;
  background: #f0f1f3;
  color: #8a9099;
}

/* 前三名：金 / 银 / 铜 */
.rank-1 {
  background: #d9a406;
  color: #ffffff;
}

.rank-2 {
  background: #8a9099;
  color: #ffffff;
}

.rank-3 {
  background: #b45309;
  color: #ffffff;
}

.rank-plain {
  background: #f0f1f3;
  color: #8a9099;
}

.rank-name {
  flex: 1;
  color: #1f2329;
}

.rank-value {
  color: #8a9099;
  font-size: 24rpx;
}

/* 一线作业任务卡 */
.task-card {
  border-left: 8rpx solid #1677ff;
}

.task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.task-station {
  font-size: 29rpx;
  font-weight: 600;
}

.task-line {
  font-size: 23rpx;
  margin-top: 10rpx;
}

.foot-tip {
  text-align: center;
  font-size: 22rpx;
  padding: 16rpx 0 40rpx;
}

.retry-btn {
  width: 320rpx;
  margin: 0 auto;
}
</style>
