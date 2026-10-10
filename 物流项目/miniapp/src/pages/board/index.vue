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
  exceptionStatusText,
  exceptionTypeLabel,
  formatDate,
  formatFullDateTime,
  taskStatusText,
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
        <view class="accept-progress">
          <view class="accept-progress-bar">
            <view class="accept-progress-inner" :style="{ width: acceptRate + '%' }" />
          </view>
          <text class="progress-text">接单率 {{ acceptRate }}%（{{ overview.trips.accepted }}/{{ overview.trips.total }}）</text>
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
