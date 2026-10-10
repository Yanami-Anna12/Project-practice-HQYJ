<script setup>
/**
 * 我的趟次（首页）。
 *
 * 数据来源：GET /api/mobile/my-trips?schedule_date=YYYY-MM-DD
 * 一行 = 某（任务, 方案, 车辆, 趟次），门店数与总货量由后端聚合好，
 * 前端不做二次统计（弱网下少算一次就少一次出错的机会）。
 *
 * ★ 日期留空的语义：后端返回**全部已下发趟次**（演示数据常常是前两天生成的），
 *   所以页面默认查今天，但提供「全部」按钮 —— 演示时日期对不上也能看到数据。
 *
 * ★ 自动刷新（本次修复的体验缺陷）：
 *   · `onShow` 每次页面显示都重拉（从消息 tab / 详情页切回来就是最新的）；
 *   · `onPullDownRefresh` 支持下拉刷新；
 *   · 订阅 WebSocket：收到「新任务下发」类消息时弹一条轻提示并刷新本列表，
 *     管理员刚点完下发，司机这边当场就能看到新增的趟次。
 *
 * ★ 确认接单（本次新增）：
 *   · 未确认的趟次卡片左侧是**橙色色条** + 醒目的「确认收到」按钮，
 *     已确认的是绿色色条 + 绿色「已确认接单 时间」标签，扫一眼就能分出来；
 *   · 后端 accept 接口是幂等的（重复调用不报错、不覆盖首次确认时间），
 *     所以这里点两次也只是多一次无害请求，不会产生两套状态。
 */
import { computed, ref } from 'vue'
import { onHide, onLoad, onPullDownRefresh, onShow, onUnload } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import { subscribeNotifications } from '@/utils/socket'
import {
  acceptStatusClass,
  acceptStatusText,
  applyAcceptance,
  formatDate,
  shiftDate,
  timeWindowLabel,
  today,
  tripCardClass,
  tripState,
  tripStatusClass,
  tripStatusText,
} from '@/utils/format'
import { accountProfile, requireLogin, setUnread, unreadFromPayload } from '@/utils/ui'

const scheduleDate = ref(today())
const trips = ref([])
const loading = ref(false)
const errorMsg = ref('')
const unread = ref(0)
/** 正在确认接单的 trip_key：避免连点（后端幂等，这里只是防重复请求） */
const acceptingKey = ref('')
/** 当前页面是否可见（onShow ~ onHide） */
const visible = ref(false)
/** 取消 WebSocket 订阅（onUnload 时调用） */
let unsubscribe = null

/**
 * 是否司机账号。管理端账号（调度/管理员）也能打开本页（例如从消息里的链接进来），
 * 给一句说明并给一个去「看板」的入口；正常情况下他们的底部导航里没有「趟次」。
 */
const isDriver = computed(() => accountProfile().isDriver)

/** 待确认的趟次数（列表顶部提示用） */
const pendingCount = computed(() => trips.value.filter((t) => !t.accepted).length)

/** 已完成 / 还要跑的趟次数（列表顶部小结用：完成的趟次会沉到列表最底下） */
const doneCount = computed(() => trips.value.filter((t) => t.trip_status === 'done').length)
const todoCount = computed(() => trips.value.length - doneCount.value)

const dateLabel = computed(() => {
  if (!scheduleDate.value) return '全部日期'
  if (scheduleDate.value === today()) return `今天 ${scheduleDate.value}`
  return scheduleDate.value
})

/** 加载趟次列表 */
async function load() {
  if (!requireLogin()) return
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await api.fetchMyTrips(scheduleDate.value || undefined)
    trips.value = Array.isArray(data) ? data : []
  } catch (err) {
    // 离线容错：失败时保留错误文案，模板渲染错误态 + 重试按钮，绝不白屏
    errorMsg.value = err.message || '加载失败'
    trips.value = []
  } finally {
    loading.value = false
  }
}

/** 刷新未读红点（失败不影响主流程） */
async function loadUnread() {
  try {
    const res = await api.fetchUnreadCount()
    unread.value = res?.unread || 0
    setUnread(unread.value)
  } catch (err) {
    console.warn('[trips] 未读数获取失败', err)
  }
}

/** 切日期 */
function changeDate(days) {
  scheduleDate.value = shiftDate(scheduleDate.value || today(), days)
  load()
}

function onDateChange(e) {
  scheduleDate.value = e.detail.value
  load()
}

function showAll() {
  scheduleDate.value = ''
  load()
}

function backToday() {
  scheduleDate.value = today()
  load()
}

function openTrip(trip) {
  uni.navigateTo({ url: `/pages/trips/detail?tripKey=${encodeURIComponent(trip.trip_key)}` })
}

/**
 * ★ 跳转一律用 redirectTo：pages.json 的 tabBar 已删除，这些页面不再是
 *   tabBar 页面，uni.switchTab 会失效。redirectTo 关掉当前页再开目标页。
 */
/** 跳到消息页 */
function goMessages() {
  uni.redirectTo({ url: '/pages/messages/index' })
}

/** 跳到看板（管理端首页） */
function goBoard() {
  uni.redirectTo({ url: '/pages/board/index' })
}

/**
 * 确认收到任务。
 *
 * ★ 不弹二次确认框：这个动作本身是幂等的、无副作用的（只是记一个时间戳），
 *   多一次弹窗在装货现场反而碍事；按钮有 loading 且防连点。
 * ★ 成功后就地更新本地状态（不再重拉列表），并 toast 出首次确认时间。
 */
async function confirmTrip(trip) {
  if (trip.accepted || acceptingKey.value) return
  acceptingKey.value = trip.trip_key
  uni.showLoading({ title: '确认中…', mask: true })
  try {
    const res = await api.acceptTrip(trip.trip_key)
    uni.hideLoading()
    applyAcceptance(trip, res)
    uni.showToast({
      title: res?.already_accepted ? '该趟次此前已确认' : '已确认接单',
      icon: 'success',
      duration: 2000,
    })
  } catch (err) {
    uni.hideLoading()
    let tip = err.message || '确认失败'
    if (err.code === 403) {
      tip = '该趟次不属于你名下的车辆，无法确认'
    } else if (err.code === 0) {
      tip = '网络不通，确认未提交成功，请重试'
    }
    uni.showModal({ title: '确认未成功', content: tip, showCancel: false, confirmText: '知道了' })
  } finally {
    acceptingKey.value = ''
  }
}

// onShow 而不是 onMounted：从详情页打卡返回、从消息 tab 切回来都要看到最新进度
onShow(() => {
  visible.value = true
  load()
  loadUnread()
})

onHide(() => {
  visible.value = false
})

onLoad(() => {
  // ★ 实时推送：「新任务下发」类消息 → 轻提示 + 刷新趟次列表。
  //   提示不区分页面是否可见：司机可能正在消息 tab 上，
  //   这时候更要让他知道「有活来了」（红点已由 App.vue 全局更新）。
  // ★ biz_type=revoked（管理员撤销下发）同理：趟次可能已经不在列表里了，
  //   必须重拉，否则司机会盯着一趟已经被收回的任务去打卡。
  unsubscribe = subscribeNotifications((payload) => {
    if (payload.type !== 'notification') return
    const bizType = payload.notification && payload.notification.biz_type
    // 这行日志是刻意留下的：实时推送「没反应」时，靠它区分
    // 「报文没到」与「到了但条件不匹配」，比翻代码快得多。
    console.log('[trips] 收到推送：', bizType, '页面可见=', visible.value)
    if (bizType === 'revoked') {
      const unreadNow = unreadFromPayload(payload)
      if (unreadNow !== null) {
        unread.value = unreadNow
        setUnread(unreadNow)
      }
      uni.showToast({ title: '有任务被撤回', icon: 'none', duration: 2500 })
      if (visible.value) {
        load()
        loadUnread()
      }
      return
    }
    if (bizType !== 'dispatch') return
    uni.showToast({ title: '收到新任务下发', icon: 'none', duration: 2500 })
    if (visible.value) {
      load()
      loadUnread()
    }
  })
})

onUnload(() => {
  visible.value = false
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }
})

onPullDownRefresh(async () => {
  await load()
  await loadUnread()
  // ★ 必须调用 stopPullDownRefresh：否则下拉的转圈会一直停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!-- 日期筛选 -->
    <view class="toolbar">
      <view class="date-nav" @click="changeDate(-1)">前一天</view>
      <picker mode="date" :value="scheduleDate || today()" @change="onDateChange">
        <view class="date-value">
          {{ dateLabel }}
          <text class="muted"> ▾</text>
        </view>
      </picker>
      <view class="date-nav" @click="changeDate(1)">后一天</view>
    </view>

    <view class="quick-row">
      <view class="quick-btn" @click="backToday">今天</view>
      <view class="quick-btn" @click="showAll">全部已下发趟次</view>
      <view class="quick-btn" @click="load">刷新</view>
    </view>

    <!-- 未读提示 -->
    <view v-if="unread > 0" class="unread-bar" @click="goMessages">
      <text>你有 {{ unread }} 条未读消息</text>
      <text class="unread-more">去查看 ›</text>
    </view>

    <!-- 管理端账号说明（看板入口） -->
    <view v-if="!isDriver" class="card notice">
      当前账号是调度/管理角色，「我的趟次」是司机页面（本账号名下没有车辆）。
      <text class="notice-link" @click="goBoard">去看今日看板 ›</text>
    </view>

    <!-- 待确认提醒：让「还要确认几趟」一眼可见 -->
    <view v-if="isDriver && pendingCount > 0" class="pending-bar">
      <text>有 {{ pendingCount }} 趟还没确认收到，请点「确认收到」</text>
    </view>

    <!--
      「一趟」是什么，第一次用的人真的看不懂（开发同事都问过）。
      一句话说清：装一次货、跑一条线路，送完回仓再装下一趟。
      另外提醒「第几趟」是按车牌算的，司机名下多台车时会有多个「第 1 趟」。
    -->
    <view v-if="isDriver && trips.length" class="hint-bar">
      <text>
        「一趟」＝ 装一次货、跑一趟线路，送完回仓库再装下一趟。
        「第几趟」是<text class="strong">按车牌</text>算的 —— 你名下有多台车时，
        每台车都会有自己的「第 1 趟」，看车牌区分。
      </text>
    </view>

    <!--
      本日小结：跑完的趟次**不会被删掉**，只是沉到列表最底下（可以回看送去哪几家）。
      这里明写出来，司机才不会以为「完成就不见了」。
    -->
    <view v-if="isDriver && doneCount > 0" class="summary-bar">
      <text>
        今天 {{ trips.length }} 趟：待跑 {{ todoCount }} 趟 · 已完成 {{ doneCount }} 趟
      </text>
      <text class="summary-note">已完成的排在列表最下面，可点开回看</text>
    </view>

    <!-- 加载中 -->
    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试 -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load">重 试</button>
    </view>

    <!-- 空态 -->
    <view v-else-if="!trips.length" class="empty">
      该日期没有你的趟次{{
        scheduleDate ? '，可试试「全部已下发趟次」' : ''
      }}
    </view>

    <!-- 趟次卡片 -->
    <view v-else>
      <!--
        ★ 卡片颜色按「三色状态」走（tripCardClass）：
          红 = 未确认接单   黄 = 已接单但没跑完   绿 = 已完成
          排序也由后端按同一口径给（红 → 黄 → 绿），前端不再自己排。
      -->
      <view
        v-for="trip in trips"
        :key="trip.trip_key"
        class="card trip-card"
        :class="tripCardClass(trip)"
        @click="openTrip(trip)"
      >
        <view class="trip-head">
          <view class="plate">{{ trip.plate_no || '未知车牌' }}</view>
          <view class="tag" :class="tripStatusClass(trip.trip_status)">
            {{ tripStatusText(trip) }}
          </view>
        </view>

        <!-- 确认接单状态条 -->
        <view class="accept-line">
          <text class="tag" :class="acceptStatusClass(trip)">
            {{ acceptStatusText(trip) }}
          </text>
          <!--
            ★ 已经跑完的趟次不再给「确认收到」按钮：
              那时点确认没有任何意义（货都送完了），留着只会让人以为还有动作没做。
              正常流程下司机是先确认再跑，跑完还没确认属于异常路径，这里只做展示。
          -->
          <button
            v-if="tripState(trip) === 'pending'"
            class="btn btn-primary accept-btn"
            :disabled="acceptingKey === trip.trip_key"
            @click.stop="confirmTrip(trip)"
          >
            {{ acceptingKey === trip.trip_key ? '确认中…' : '确认收到' }}
          </button>
          <text v-else-if="tripState(trip) === 'accepted'" class="accept-tip">已接单，待出车</text>
          <text v-else class="accept-skip">已跑完，无需确认</text>
        </view>

        <view class="row">
          <text class="row-label">车型</text>
          <text class="row-value">
            {{ trip.vehicle_type_name || trip.vehicle_type || '—' }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">出车顺序</text>
          <text class="row-value">
            <!-- ★ 必须带上车牌：司机名下多台车时，会有多个「第 1 趟」，
                 只写「第 1 趟」根本分不清是哪台车的第 1 趟。 -->
            <text class="strong">{{ trip.plate_no }}</text>
            <text class="strong"> 今天第 {{ trip.trip_no }} 趟</text>
            <text v-if="trip.vehicle_trip_count > 1">（本车共 {{ trip.vehicle_trip_count }} 趟）</text>
            <text> · {{ timeWindowLabel(trip.time_window) }}送</text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">门店 / 货量</text>
          <text class="row-value">
            {{ trip.store_count }} 家 · {{ trip.total_load }} 件
          </text>
        </view>
        <view class="row">
          <text class="row-label">日期 / 任务</text>
          <text class="row-value">{{ formatDate(trip.schedule_date) }} · {{ trip.task_code }}</text>
        </view>

        <view class="progress-row">
          <view class="progress-bar">
            <view
              class="progress-inner"
              :style="{ width: trip.store_count ? (trip.done_stores / trip.store_count) * 100 + '%' : '0%' }"
            />
          </view>
          <text class="progress-text">
            已完成 {{ trip.done_stores }}/{{ trip.store_count }}
            <text v-if="trip.arrived_stores">（{{ trip.arrived_stores }} 家已到店）</text>
          </text>
        </view>

        <view class="trip-foot muted">点击查看门店顺序并打卡 ›</view>
      </view>
    </view>

    <BottomNav />
  </view>
</template>
<style scoped>
.date-nav {
  color: #1668dc;
  font-size: 26rpx;
  padding: 8rpx 12rpx;
}

.date-value {
  font-size: 30rpx;
  font-weight: 600;
}

.quick-row {
  display: flex;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.quick-btn {
  flex: 1;
  text-align: center;
  background: #ffffff;
  border-radius: 12rpx;
  padding: 16rpx 0;
  color: #1668dc;
  font-size: 24rpx;
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

/* 管理端账号说明 */
.notice {
  background: #fff4e6;
  color: #d97706;
  font-size: 24rpx;
  line-height: 1.6;
}

.notice-link {
  color: #1668dc;
}

/* 待确认提醒条 */
.pending-bar {
  background: #fff4e6;
  border-left: 8rpx solid #d97706;
  color: #b45309;
  border-radius: 12rpx;
  padding: 18rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 26rpx;
}

/* 「一趟是什么」的说明条：灰底、不抢眼，但第一次看的人能读懂 */
.hint-bar {
  background: #eef3fb;
  border-left: 8rpx solid #1668dc;
  color: #3d5a80;
  border-radius: 12rpx;
  padding: 16rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 24rpx;
  line-height: 1.7;
}

/* 本日小结条：让「已完成」的趟次有存在感（它们沉在列表最底下） */
.summary-bar {
  display: flex;
  flex-direction: column;
  background: #e8f7ee;
  border-left: 8rpx solid #18a058;
  color: #14724a;
  border-radius: 12rpx;
  padding: 16rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 25rpx;
  line-height: 1.6;
}

.summary-note {
  color: #4b8b6e;
  font-size: 22rpx;
  margin-top: 4rpx;
}

/* 关键信息加重（如「本车今天第 1 趟」「按车牌」） */
.strong {
  font-weight: 600;
  color: #1f2329;
}

/*
 * 左侧色条 = 趟次的「三色状态」（用户口径，与右上角标签、列表排序完全一致）：
 *   红 pending  未确认接单 —— 需要司机动手，排最上面
 *   黄 accepted 已接单但没跑完 —— 在手上，排中间
 *   绿 done     已完成 —— 可以回看，沉到最下面
 * ★ 颜色别在页面里另写一套：class 由 utils/format.js 的 tripCardClass() 给，
 *   那边的 tripState() 是三色的唯一定义处。
 */
.trip-card {
  border-left: 8rpx solid #8a9099;
}

.trip-card-pending {
  border-left-color: #d03050;
}

.trip-card-accepted {
  border-left-color: #d9a406;
}

.trip-card-done {
  border-left-color: #18a058;
}

/* 已接单待出车的小提示（黄色系，与色条一致） */
.accept-tip {
  font-size: 22rpx;
  color: #b7791f;
}

/* 确认接单状态条：左侧状态标签 + 右侧按钮 */
.accept-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8rpx;
}

.accept-btn {
  font-size: 26rpx;
  line-height: 2.2;
  padding: 0 28rpx;
  margin: 0;
}

/* 已跑完但没确认过的趟次：不给按钮，只给一句灰字说明 */
.accept-skip {
  font-size: 22rpx;
  color: #8a9099;
}

.trip-head {
  display: flex;
  align-items: center;
  margin-bottom: 12rpx;
}

.plate {
  font-size: 34rpx;
  font-weight: 700;
  letter-spacing: 2rpx;
}

.tag {
  margin-left: auto;
}

.progress-row {
  margin-top: 16rpx;
}

.progress-bar {
  height: 12rpx;
  background: #eef0f3;
  border-radius: 6rpx;
  overflow: hidden;
}

.progress-inner {
  height: 100%;
  background: #18a058;
}

.progress-text {
  display: block;
  color: #8a9099;
  font-size: 22rpx;
  margin-top: 8rpx;
}

.trip-foot {
  margin-top: 16rpx;
  font-size: 22rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
