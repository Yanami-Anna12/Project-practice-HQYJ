<script setup>
/**
 * 运维工作台（现场作业端首页）。
 *
 * 这是运维人员打开小程序第一眼看到的页面，只为回答三个问题：
 *   ① 今天/最近要跑哪几个站？（我的作业任务，待完成 + 巡检中）
 *   ② 有多少活压着没干完？有没有已经拖过计划日期的？
 *   ③ 我要报修 / 巡检 / 看消息，入口在哪？
 *
 * ★ 为什么首页不直接放「工单列表」：
 *   一张工单可能拆成好几个站点的作业任务，工单粒度对现场人员太粗 ——
 *   他关心的是「今天去哪几个站、每个站做什么」，所以主线是**作业任务（子任务）**。
 *
 * ★ 数据来源全是后端已有接口，没有为小程序新增任何后端 API：
 *   · /work-orders/home                   工单统计（后端按数据权限自动过滤）
 *   · /work-orders/subtasks/mine          我的作业任务
 *   · /faults?mine=true                   我上报的故障
 *   · /messages?page=1&page_size=1        未读数
 */
import { computed, ref } from 'vue'
import { onLoad, onPullDownRefresh, onShow } from '@dcloudio/uni-app'

import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import {
  formatDate,
  fromNow,
  faultLevelClass,
  faultStatusClass,
  isPastDate,
  isToday,
  taskStatusClass,
} from '@/utils/format'
import { accountProfile, errorText, requireLogin, setUnread, unreadFromPayload } from '@/utils/ui'
import { subscribeNotifications } from '@/utils/socket'

const loading = ref(false)
const errorMsg = ref('')

/** 工单统计（个人数据权限下就是「我的」） */
const stats = ref({ total: 0, pending: 0, done: 0, overdue: 0, urgent: 0, completion_rate: 0 })
/** 我的作业任务（待完成 + 巡检中） */
const todoTasks = ref([])
/** 我上报的故障（最近 3 条） */
const myFaults = ref([])
/** 未读消息数 */
const unread = ref(0)

const profile = computed(() => accountProfile())
const displayName = computed(() => profile.value.user.real_name || profile.value.user.username || '同事')
const roleName = computed(() => (profile.value.role && profile.value.role.name) || '未分配角色')
const dataScope = computed(() => profile.value.dataScope || '—')

/** 今天到期的作业任务 */
const todayTasks = computed(() => todoTasks.value.filter((t) => isToday(t.plan_date)))
/** 已经拖过计划日期的作业任务（现场最需要被提醒的一类） */
const overdueTasks = computed(() => todoTasks.value.filter((t) => isPastDate(t.plan_date)))

/** 列表实际渲染的那几条：今天 + 逾期优先，其次按计划日期升序 */
const visibleTasks = computed(() => {
  const priority = (t) => (isToday(t.plan_date) ? 0 : isPastDate(t.plan_date) ? 1 : 2)
  return [...todoTasks.value]
    .sort((a, b) => {
      const d = priority(a) - priority(b)
      if (d !== 0) return d
      return String(a.plan_date || '').localeCompare(String(b.plan_date || ''))
    })
    .slice(0, 6)
})

/**
 * 拉数据。
 * ★ 四个请求互不依赖，用Promise.all 并发；每个请求单独 catch ——
 *   某一项失败（比如消息接口超时）不能让整页变成错误态，
 *   现场人员至少还能看到今天的任务。
 */
async function load() {
  if (!requireLogin()) return
  loading.value = true
  errorMsg.value = ''

  const [homeRes, todoRes, doingRes, faultRes, msgRes] = await Promise.allSettled([
    api.fetchWorkOrderHome(),
    api.fetchMySubtasks({ status: '待完成', pageSize: 50 }),
    api.fetchMySubtasks({ status: '巡检中', pageSize: 50 }),
    api.fetchFaults({ mine: true, pageSize: 3 }),
    api.fetchMessageList({ page: 1, pageSize: 1 }),
  ])

  if (homeRes.status === 'fulfilled') {
    stats.value = { ...stats.value, ...(homeRes.value || {}) }
  } else {
    errorMsg.value = errorText(homeRes.reason, '工单统计加载失败')
  }

  // 待完成 + 巡检中合并成「待办」：现场不需要区分这两个 tab，他只要知道哪些还没干完
  const merged = []
  if (todoRes.status === 'fulfilled') merged.push(...((todoRes.value && todoRes.value.items) || []))
  if (doingRes.status === 'fulfilled') merged.push(...((doingRes.value && doingRes.value.items) || []))
  todoTasks.value = merged

  if (faultRes.status === 'fulfilled') {
    myFaults.value = (faultRes.value && faultRes.value.items) || []
  }

  if (msgRes.status === 'fulfilled') {
    unread.value = (msgRes.value && msgRes.value.unread_count) || 0
    setUnread(unread.value)
  }

  loading.value = false
}

/* ------------------------------------------------------------------ *
 * 跳转
 * ------------------------------------------------------------------ */

/** tab 之间用 redirectTo（这些页面已不是 tabBar 页面，switchTab 会失效） */
function goTab(path) {
  uni.redirectTo({ url: path, fail: () => uni.reLaunch({ url: path }) })
}

function goTask(id) {
  uni.navigateTo({ url: `/pages/tasks/detail?id=${id}` })
}

function goFault(id) {
  uni.navigateTo({ url: `/pages/fault/detail?id=${id}` })
}

function goReport() {
  uni.navigateTo({ url: '/pages/fault/report' })
}

function goScan() {
  uni.navigateTo({ url: '/pages/scan/scan' })
}

/** 直接对某条作业任务开工：跳到它的详情页，由详情页去改状态并进巡检录入 */
function startTask(task) {
  uni.navigateTo({ url: `/pages/tasks/detail?id=${task.id}&action=inspect` })
}

onShow(() => {
  load()
})

onLoad(() => {
  // 收到未读推送时只更新红点与顶部提示条；列表等用户下拉或切页面时再拉，避免频繁请求
  subscribeNotifications((payload) => {
    const value = unreadFromPayload(payload)
    if (value !== null) {
      unread.value = value
      setUnread(value)
    }
  })
})

onPullDownRefresh(async () => {
  await load()
  // ★ 必须调用 stopPullDownRefresh：否则下拉的转圈会一直停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!-- 身份条：现场人员一眼确认「我是谁、看到的是谁的数据」 -->
    <view class="hero">
      <view class="hero-main">
        <view class="hero-name">{{ displayName }}</view>
        <view class="hero-role">{{ roleName }} · {{ dataScope }}</view>
      </view>
      <view class="hero-badge">在岗</view>
    </view>

    <!-- 管理端账号误入：给一句解释 + 一个去自己首页的入口 -->
    <view v-if="!profile.isField" class="hint-bar">
      当前账号是管理角色（{{ dataScope }}），本页只显示与你本人相关的任务。
      <text class="link" @click="goTab('/pages/board/index')">去看掌上看板 ›</text>
    </view>

    <!-- 未读消息 -->
    <view v-if="unread > 0" class="unread-bar" @click="goTab('/pages/messages/index')">
      <text>你有 {{ unread }} 条未读消息</text>
      <text class="unread-more">去查看 ›</text>
    </view>

    <!-- 逾期提醒：现场管理里最该被顶到眼前的一件事 -->
    <view v-if="overdueTasks.length" class="danger-bar">
      有 {{ overdueTasks.length }} 个作业任务已过计划日期，请优先处理（列表已置顶）
    </view>

    <!-- 工单统计 -->
    <view class="stat-grid">
      <view class="stat-card">
        <view class="stat-value stat-primary">{{ stats.total || 0 }}</view>
        <view class="stat-label">我的工单</view>
      </view>
      <view class="stat-card">
        <view class="stat-value stat-warn">{{ stats.pending || 0 }}</view>
        <view class="stat-label">待办</view>
      </view>
      <view class="stat-card">
        <view class="stat-value stat-done">{{ stats.done || 0 }}</view>
        <view class="stat-label">已完成</view>
      </view>
      <view class="stat-card">
        <view class="stat-value">{{ stats.completion_rate || 0 }}%</view>
        <view class="stat-label">完成率</view>
      </view>
    </view>

    <!-- 快捷入口：现场四个最高频动作 -->
    <view class="quick-grid">
      <view class="quick-card" @click="goScan">
        <view class="quick-icon">◎</view>
        <view class="quick-text">扫码查桩</view>
        <view class="quick-sub">扫资产码直接报修</view>
      </view>
      <view class="quick-card" @click="goReport">
        <view class="quick-icon">!</view>
        <view class="quick-text">故障上报</view>
        <view class="quick-sub">拍照 + 定位 + AI 辅助</view>
      </view>
      <view class="quick-card" @click="goTab('/pages/tasks/index')">
        <view class="quick-icon">☰</view>
        <view class="quick-text">我的任务</view>
        <view class="quick-sub">全部作业任务</view>
      </view>
      <view class="quick-card" @click="goTab('/pages/messages/index')">
        <view class="quick-icon">✉</view>
        <view class="quick-text">消息</view>
        <view class="quick-sub">
          {{ unread > 0 ? `${unread} 条未读` : '暂无未读' }}
        </view>
      </view>
    </view>

    <!-- 加载中 -->
    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试 -->
    <view v-else-if="errorMsg && !todoTasks.length" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load">重 试</button>
    </view>

    <template v-else>
      <!-- 待办作业任务 -->
      <view class="section-title">
        <text>待办作业任务</text>
        <text class="section-more" @click="goTab('/pages/tasks/index')">查看全部 ›</text>
      </view>

      <view v-if="!visibleTasks.length" class="card empty-card">
        <text class="muted">当前没有待办的作业任务，可以下拉刷新看看。</text>
      </view>

      <view
        v-for="task in visibleTasks"
        :key="task.id"
        class="card task-card"
        :class="isPastDate(task.plan_date) ? 'task-card-overdue' : isToday(task.plan_date) ? 'task-card-today' : ''"
        @click="goTask(task.id)"
      >
        <view class="task-head">
          <text class="task-station">{{ task.station_name || '未指定站点' }}</text>
          <text class="tag" :class="taskStatusClass(task.status)">{{ task.status }}</text>
        </view>

        <view class="task-tags">
          <text v-if="isToday(task.plan_date)" class="mini-tag mini-today">今天</text>
          <text v-else-if="isPastDate(task.plan_date)" class="mini-tag mini-overdue">
            已过计划日期
          </text>
          <text class="mini-tag mini-plain">{{ task.order_type || '作业' }}</text>
          <text v-if="task.pile_asset_code" class="mini-tag mini-plain">
            {{ task.pile_asset_code }}
          </text>
        </view>

        <view class="row">
          <text class="row-label">工单</text>
          <text class="row-value">
            {{ task.order_no }}
            <text class="muted"> · 第 {{ task.sequence }} 项</text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">计划</text>
          <text class="row-value">
            {{ formatDate(task.plan_date) }}
            <text v-if="task.plan_time_window" class="muted"> · {{ task.plan_time_window }}</text>
          </text>
        </view>

        <view class="task-foot">
          <text class="muted task-name">{{ task.order_name }}</text>
          <button class="btn btn-primary task-btn" @click.stop="startTask(task)">
            {{ task.status === '巡检中' ? '继续巡检' : '开始巡检' }}
          </button>
        </view>
      </view>

      <!-- 我上报的故障：让现场人员知道「我报的东西有没有人管」 -->
      <view class="section-title">
        <text>我上报的故障</text>
        <text class="section-more" @click="goTab('/pages/fault/index')">全部故障 ›</text>
      </view>

      <view v-if="!myFaults.length" class="card empty-card">
        <text class="muted">还没有上报过故障。发现异常就点上面的「故障上报」或「扫码查桩」。</text>
      </view>

      <view v-for="fault in myFaults" :key="fault.id" class="card fault-card" @click="goFault(fault.id)">
        <view class="task-head">
          <text class="task-station">{{ fault.fault_type || '未分类故障' }}</text>
          <text class="tag" :class="faultLevelClass(fault.fault_level)">{{ fault.fault_level }}</text>
        </view>
        <view class="row">
          <text class="row-label">故障编号</text>
          <text class="row-value">{{ fault.fault_no }}</text>
        </view>
        <view class="row">
          <text class="row-label">站点 / 桩</text>
          <text class="row-value">
            {{ fault.station_name || '—' }}
            <text v-if="fault.pile_asset_code" class="muted"> · {{ fault.pile_asset_code }}</text>
          </text>
        </view>
        <view class="fault-foot">
          <text class="tag" :class="faultStatusClass(fault.status)">{{ fault.status }}</text>
          <text class="muted">{{ fromNow(fault.created_at) }}</text>
        </view>
      </view>
    </template>

    <BottomNav />
  </view>
</template>

<style scoped>
/* 身份条 */
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  border-radius: 20rpx;
  padding: 32rpx 28rpx;
  margin-bottom: 20rpx;
  color: #ffffff;
}

.hero-name {
  font-size: 40rpx;
  font-weight: 700;
}

.hero-role {
  font-size: 24rpx;
  opacity: 0.9;
  margin-top: 10rpx;
}

.hero-badge {
  font-size: 22rpx;
  background: rgba(255, 255, 255, 0.22);
  border-radius: 20rpx;
  padding: 6rpx 20rpx;
}

.link {
  color: #1677ff;
}

.unread-bar {
  display: flex;
  justify-content: space-between;
  background: #fff4e6;
  color: #d97706;
  border-radius: 12rpx;
  padding: 18rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 26rpx;
}

.unread-more {
  color: #d97706;
}

/* 快捷入口 */
.quick-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  margin-bottom: 8rpx;
}

.quick-card {
  width: calc(50% - 8rpx);
  box-sizing: border-box;
  background: #ffffff;
  border-radius: 16rpx;
  padding: 24rpx 20rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.quick-icon {
  width: 56rpx;
  height: 56rpx;
  line-height: 56rpx;
  text-align: center;
  border-radius: 28rpx;
  background: #e8f2ff;
  color: #1677ff;
  font-size: 30rpx;
  font-weight: 700;
  margin-bottom: 14rpx;
}

.quick-text {
  font-size: 29rpx;
  font-weight: 600;
}

.quick-sub {
  font-size: 22rpx;
  color: #8a9099;
  margin-top: 6rpx;
}

/* 作业任务卡 */
.task-card {
  border-left: 8rpx solid #c9ced6;
}

/* 左侧色条与状态同义：红=已过计划日期（要动手） 蓝=今天 灰=以后 */
.task-card-today {
  border-left-color: #1677ff;
}

.task-card-overdue {
  border-left-color: #d03050;
}

.task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.task-station {
  font-size: 32rpx;
  font-weight: 600;
  flex: 1;
  margin-right: 12rpx;
}

.task-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin: 14rpx 0 6rpx;
}

.mini-tag {
  font-size: 21rpx;
  padding: 3rpx 14rpx;
  border-radius: 16rpx;
}

.mini-today {
  background: #e8f2ff;
  color: #1677ff;
}

.mini-overdue {
  background: #fdecec;
  color: #d03050;
}

.mini-plain {
  background: #f0f1f3;
  color: #6b7280;
}

.task-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx solid #f0f1f3;
}

.task-name {
  flex: 1;
  font-size: 22rpx;
  margin-right: 16rpx;
}

.task-btn {
  font-size: 26rpx;
  line-height: 2.2;
  padding: 0 28rpx;
  margin: 0;
}

/* 故障卡 */
.fault-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14rpx;
  padding-top: 14rpx;
  border-top: 1rpx solid #f0f1f3;
  font-size: 22rpx;
}

.fault-foot .tag {
  margin-left: 0;
}

.empty-card {
  text-align: center;
  font-size: 25rpx;
  line-height: 1.7;
}

.retry-btn {
  width: 320rpx;
}
</style>
