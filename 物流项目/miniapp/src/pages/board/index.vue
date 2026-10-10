<script setup>
/**
 * 今日看板（管理端只读首页）。
 *
 * 数据来源：GET /api/mobile/manager/overview
 *   —— 后端**一次聚合**：今日任务数与状态、趟次总数、已接单/未接单、
 *      在途车辆数、待处理异常数、最近异常摘要。
 *      前端刻意不打 4 个接口：弱网下 4 次往返既慢，几个数字还可能来自不同时刻，
 *      页面上会出现「已接单数比趟次总数还大」这种自相矛盾。
 *
 * ★ 本页**只读**：没有任何写操作，所有数字直接来自后端聚合结果，
 *   前端不做二次统计（少算一次就少一次和服务端不一致的机会）。
 * ★ 权限：后端要求 scheduling:read（admin / dispatcher / viewer / multi 可用，
 *   司机账号 403）。这里对 403 单独给一句人话，而不是甩一个英文串。
 * ★ 下拉刷新 = 重新取一次快照；页头显示快照生成时间，
 *   让人知道「这些数字是什么时候的」。
 */
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import {
  briefStateClass,
  briefStateLabel,
  exceptionStatusText,
  exceptionTypeLabel,
  formatDate,
  formatFullDateTime,
  taskStatusText,
  timeWindowLabel,
} from '@/utils/format'
import { requireLogin } from '@/utils/ui'

const overview = ref(null)
const loading = ref(false)
const errorMsg = ref('')
/** 403（账号没有看板权限）与普通错误分开提示 */
const forbidden = ref(false)

/** 各状态计数 → 可渲染的数组（按数量倒序，0 的不显示） */
const statusRows = computed(() => {
  const byStatus = (overview.value && overview.value.tasks && overview.value.tasks.by_status) || {}
  return Object.keys(byStatus)
    .map((key) => ({ key, label: taskStatusText(key), count: byStatus[key] }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count)
})

/** 接单进度百分比（未接单占比用来给个视觉提示） */
const acceptRate = computed(() => {
  const trips = (overview.value && overview.value.trips) || {}
  if (!trips.total) return 0
  return Math.round(((trips.accepted || 0) / trips.total) * 100)
})

/** 门店完成度百分比（按门店算，比趟次粒度更能看出「跑了一半」） */
const doneRate = computed(() => {
  const c = (overview.value && overview.value.completion) || {}
  if (!c.stores_total) return 0
  return Math.round(((c.stores_done || 0) / c.stores_total) * 100)
})

/* ---------------- 趟次明细（看板最上面那块） ---------------- */
/** 每档（正在跑/已接单/待确认/已完成）首屏各给几条 */
const PER_STATE_LIMIT = 3
const showAllBriefs = ref(false)

const briefs = computed(() => (overview.value && overview.value.trip_briefs) || [])

/**
 * 各类各有多少（不依赖后端另给字段，直接按 state 数一遍）。
 * 顺序固定为「要盯的在前」，与明细排序一致。
 */
const briefSummary = computed(() => {
  const order = ['running', 'accepted', 'pending', 'done']
  return order
    .map((state) => ({
      state,
      label: briefStateLabel(state),
      count: briefs.value.filter((t) => t.state === state).length,
    }))
    .filter((s) => s.count > 0)
})

/** 首屏每档取前 N 条；展开后给全部（后端已按状态排好，这里只需按档截断） */
const visibleBriefs = computed(() => {
  if (showAllBriefs.value) return briefs.value
  const seen = {}
  const out = []
  for (const t of briefs.value) {
    const n = seen[t.state] || 0
    if (n >= PER_STATE_LIMIT) continue
    seen[t.state] = n + 1
    out.push(t)
  }
  return out
})

function toggleBriefs() {
  showAllBriefs.value = !showAllBriefs.value
}

async function load() {
  if (!requireLogin()) return
  loading.value = true
  errorMsg.value = ''
  forbidden.value = false
  try {
    overview.value = await api.fetchManagerOverview()
  } catch (err) {
    overview.value = null
    if (err.code === 403) {
      forbidden.value = true
      errorMsg.value = '当前账号没有看板权限（需要调度查看权限 scheduling:read）'
    } else {
      errorMsg.value = err.message || '加载看板失败'
    }
  } finally {
    loading.value = false
  }
}

/**
 * 「任务列表」是底部导航的一级页面，用 redirectTo 换页（保持栈深度 1，
 * 与底部导航里的「任务」表现一致）；下面的异常列表/任务详情才是二级页，
 * 走 navigateTo 压栈，返回键正常。
 */
function goTasks() {
  uni.redirectTo({ url: '/pages/board/tasks' })
}

function goExceptions() {
  uni.navigateTo({ url: '/pages/board/exceptions' })
}

// onShow：从任务/异常列表返回时会重新取一次快照，数字永远是最新的
onShow(load)

onPullDownRefresh(async () => {
  await load()
  // ★ 必须调用 stopPullDownRefresh，否则转圈会一直停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <view v-if="loading" class="empty">加载中…</view>

    <!-- 权限不足 / 加载失败 -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button v-if="!forbidden" class="btn btn-primary retry-btn" @click="load">重 试</button>
      <view v-else class="muted forbidden-tip">
        司机账号请用「趟次」tab；调度/管理员账号才有今日看板。
      </view>
    </view>

    <template v-else-if="overview">
      <!--
        ★ 趟次明细放在最上面（用户要求：「一进来就能看到」）：
          一行 = 一趟活（不是一家门店 —— 逐店列会把看板撑爆）。
          排序由后端给：正在跑 → 已接单 → 待确认 → 已完成，
          即「要盯的在最上面、跑完的沉底」，与司机端三色语义一致。
      -->
      <view class="card">
        <view class="card-title">
          <text>趟次明细（{{ briefs.length }} 趟）</text>
          <text class="muted small">按 正在跑 → 已接单 → 待确认 → 已完成 排</text>
        </view>

        <view v-if="!briefs.length" class="muted">今天还没有已下发的趟次</view>

        <!-- 分布小结：不用往下翻就知道各类各有多少 -->
        <view v-if="briefs.length" class="brief-summary">
          <text
            v-for="s in briefSummary"
            :key="s.state"
            class="tag"
            :class="briefStateClass(s.state)"
          >
            {{ briefStateLabel(s.state) }} {{ s.count }}
          </text>
        </view>

        <!--
          ★ 首屏每档只给 3 条：49 趟全铺开有 4800px 高，
            「今日任务 / 完成情况」这些数字要滑半天才看得到，反而失去「一进来就看到」的意义。
            每档给前几条 + 分布数字，点「展开」再看全部。
        -->
        <view
          v-for="t in visibleBriefs"
          :key="t.trip_key"
          class="brief-row"
          :class="`brief-${t.state}`"
        >
          <view class="brief-main">
            <text class="brief-plate">{{ t.plate_no || '未知车牌' }}</text>
            <text class="brief-trip">第 {{ t.trip_no }} 趟·{{ timeWindowLabel(t.time_window) }}</text>
            <text class="tag" :class="briefStateClass(t.state)">{{ briefStateLabel(t.state) }}</text>
          </view>
          <view class="brief-sub">
            <text>{{ t.driver_name || '未指派' }}</text>
            <text>门店 {{ t.done_stores }}/{{ t.store_count }}</text>
            <text class="muted">{{ t.task_code }}</text>
          </view>
        </view>

        <view v-if="briefs.length > visibleBriefs.length || showAllBriefs" class="brief-more" @click="toggleBriefs">
          <text v-if="!showAllBriefs">展开全部 {{ briefs.length }} 趟 ›</text>
          <text v-else>收起，每档只看前 {{ PER_STATE_LIMIT }} 趟 ‹</text>
        </view>
      </view>

      <!-- 页头：日期 + 快照时间 -->
      <view class="card head-card">
        <view class="head-title">今日看板（只读）</view>
        <view class="desc">
          {{ formatDate(overview.schedule_date) }} ·
          快照时间 {{ formatFullDateTime(overview.generated_at) }}
        </view>
      </view>

      <!-- 任务 -->
      <view class="card">
        <view class="card-title">
          <text>今日任务</text>
          <text class="big-num">{{ overview.tasks.total }}</text>
        </view>
        <view v-if="!statusRows.length" class="muted">今天还没有调度任务</view>
        <view v-for="row in statusRows" :key="row.key" class="row">
          <text class="row-label">{{ row.label }}</text>
          <text class="row-value">{{ row.count }} 个</text>
        </view>
      </view>

      <!-- 趟次与接单 -->
      <view class="card">
        <view class="card-title">
          <text>趟次 / 司机确认接单</text>
          <text class="big-num">{{ overview.trips.total }}</text>
        </view>
        <view class="row">
          <text class="row-label">已接单</text>
          <text class="row-value ok-text">{{ overview.trips.accepted }} 趟</text>
        </view>
        <view class="row">
          <text class="row-label">未接单</text>
          <text class="row-value" :class="overview.trips.pending ? 'warn-text' : ''">
            {{ overview.trips.pending }} 趟
          </text>
        </view>
        <view class="desc">以上均为当日数值（累计下发 {{ overview.trips.all_time }} 趟）</view>
        <view class="accept-progress">
          <view class="accept-progress-bar">
            <view class="accept-progress-inner" :style="{ width: acceptRate + '%' }" />
          </view>
          <text class="progress-text">接单率 {{ acceptRate }}%（{{ overview.trips.accepted }}/{{ overview.trips.total }}）</text>
        </view>
      </view>

      <!-- 执行完成情况：调度最关心的「今天跑完了多少」 -->
      <view v-if="overview.completion" class="card">
        <view class="card-title">
          <text>执行完成情况</text>
          <text class="big-num">{{ overview.completion.trips_total }}</text>
        </view>
        <view class="row">
          <text class="row-label">已完成</text>
          <text class="row-value ok-text">{{ overview.completion.finished }} 趟</text>
        </view>
        <view class="row">
          <text class="row-label">正在跑</text>
          <text class="row-value" :class="overview.completion.running ? 'info-text' : ''">
            {{ overview.completion.running }} 趟
          </text>
        </view>
        <view class="row">
          <text class="row-label">未出车</text>
          <text class="row-value" :class="overview.completion.not_started ? 'warn-text' : ''">
            {{ overview.completion.not_started }} 趟
          </text>
        </view>
        <view class="accept-progress">
          <view class="accept-progress-bar">
            <view
              class="accept-progress-inner done-inner"
              :style="{ width: doneRate + '%' }"
            />
          </view>
          <text class="progress-text">
            门店完成度 {{ doneRate }}%（{{ overview.completion.stores_done }}/{{
              overview.completion.stores_total
            }} 家）
          </text>
        </view>
        <view class="desc">
          口径：「已完成」= 该趟所有门店都打完卡；「正在跑」= 有门店到了店但没跑完。
        </view>
      </view>

      <!-- 车辆与异常 -->
      <view class="grid-row">
        <view class="card grid-card">
          <view class="grid-num">{{ overview.vehicles.in_transit }}</view>
          <view class="grid-label">在途车辆</view>
          <view class="grid-sub muted">共 {{ overview.vehicles.total }} 台</view>
        </view>
        <view class="card grid-card">
          <view class="grid-num" :class="overview.exceptions.pending ? 'warn-text' : ''">
            {{ overview.exceptions.pending }}
          </view>
          <view class="grid-label">待处理异常</view>
          <view class="grid-sub muted">累计 {{ overview.exceptions.total }} 条</view>
        </view>
      </view>

      <!-- 两个入口 -->
      <view class="entry-row">
        <view class="entry-btn" @click="goTasks">任务列表 ›</view>
        <view class="entry-btn" @click="goExceptions">异常列表 ›</view>
      </view>

      <!-- 最近异常 -->
      <view class="section-title">最近异常</view>
      <view v-if="!overview.recent_exceptions.length" class="card muted">暂无异常记录</view>
      <view
        v-for="item in overview.recent_exceptions"
        :key="item.id"
        class="card exc-card"
        @click="goExceptions"
      >
        <view class="exc-head">
          <text class="exc-type">{{ exceptionTypeLabel(item.event_type) }}</text>
          <text class="tag" :class="item.status === 'pending' ? 'tag-warn' : 'tag-done'">
            {{ exceptionStatusText(item.status) }}
          </text>
        </view>
        <view class="exc-line muted">
          {{ item.task_code || ('任务#' + item.task_id) }} · {{ item.source || '—' }} ·
          {{ formatFullDateTime(item.occurred_at) }}
        </view>
        <view v-if="item.summary" class="exc-summary">{{ item.summary }}</view>
      </view>

      <view class="foot-tip muted">
        看板只读，不会修改任何数据；数字来自后端一次聚合的结果
      </view>
    </template>

    <BottomNav />
  </view>
</template>

<style scoped>
.head-card {
  background: linear-gradient(135deg, #1668dc 0%, #2f80ed 100%);
  color: #ffffff;
}

.head-title {
  font-size: 34rpx;
  font-weight: 600;
}

.head-card .desc {
  color: rgba(255, 255, 255, 0.85);
}

.card-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 28rpx;
  font-weight: 600;
  margin-bottom: 16rpx;
}

.big-num {
  font-size: 44rpx;
  font-weight: 700;
  color: #1668dc;
}

.ok-text {
  color: #18a058;
}

.warn-text {
  color: #d97706;
}

.info-text {
  color: #1668dc;
}

/* ---------------- 趟次明细（看板最上面那块） ---------------- */
/* 一行 = 一趟活；左侧色条与司机端三色同源，扫一眼就知道哪几趟要盯 */
.brief-row {
  padding: 14rpx 16rpx;
  border-left: 8rpx solid #8a9099;
  background: #fafbfc;
  border-radius: 8rpx;
  margin-bottom: 10rpx;
}

.brief-running {
  border-left-color: #1668dc;
}

.brief-accepted {
  border-left-color: #d9a406;
}

.brief-pending {
  border-left-color: #d03050;
}

.brief-done {
  border-left-color: #18a058;
}

.brief-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.brief-plate {
  font-weight: 700;
  font-size: 28rpx;
  margin-right: 12rpx;
}

.brief-trip {
  color: #4b5563;
  font-size: 24rpx;
  margin-right: 12rpx;
}

.brief-sub {
  display: flex;
  gap: 18rpx;
  flex-wrap: wrap;
  color: #8a9099;
  font-size: 22rpx;
  margin-top: 6rpx;
}

.brief-more {
  text-align: center;
  color: #1668dc;
  font-size: 24rpx;
  padding: 12rpx 0 4rpx;
}

/* 分布小结：一行标签，不用往下翻就知道各类各有多少 */
.brief-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-bottom: 14rpx;
}

.small {
  font-size: 22rpx;
}

.accept-progress {
  margin-top: 16rpx;
}

.accept-progress-bar {
  height: 12rpx;
  background: #eef0f3;
  border-radius: 6rpx;
  overflow: hidden;
}

.accept-progress-inner {
  height: 100%;
  background: #18a058;
}

/* 门店完成度用绿色（与「已完成」同一套语义），接单率保持绿色不动 */
.done-inner {
  background: #18a058;
}

.progress-text {
  display: block;
  color: #8a9099;
  font-size: 22rpx;
  margin-top: 8rpx;
}

.grid-row {
  display: flex;
  gap: 20rpx;
}

.grid-card {
  flex: 1;
  text-align: center;
  margin-bottom: 20rpx;
}

.grid-num {
  font-size: 52rpx;
  font-weight: 700;
  color: #1668dc;
}

.grid-label {
  font-size: 26rpx;
  margin-top: 4rpx;
}

.grid-sub {
  font-size: 22rpx;
  margin-top: 4rpx;
}

.entry-row {
  display: flex;
  gap: 20rpx;
  margin-bottom: 24rpx;
}

.entry-btn {
  flex: 1;
  background: #ffffff;
  color: #1668dc;
  border: 1rpx solid #1668dc;
  border-radius: 12rpx;
  text-align: center;
  padding: 24rpx 0;
  font-size: 28rpx;
}

.section-title {
  font-size: 28rpx;
  font-weight: 600;
  margin: 8rpx 0 16rpx;
}

.exc-card {
  border-left: 8rpx solid #d97706;
}

.exc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.exc-type {
  font-size: 30rpx;
  font-weight: 600;
}

.exc-line {
  font-size: 22rpx;
  margin-top: 8rpx;
}

.exc-summary {
  font-size: 24rpx;
  color: #4b5563;
  margin-top: 8rpx;
  line-height: 1.5;
}

.foot-tip {
  text-align: center;
  font-size: 22rpx;
  padding: 16rpx 0 40rpx;
}

.forbidden-tip {
  font-size: 24rpx;
  line-height: 1.6;
}

.retry-btn {
  width: 320rpx;
}
</style>
