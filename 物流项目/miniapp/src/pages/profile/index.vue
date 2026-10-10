<script setup>
/**
 * 我的（司机档案）。
 *
 * 数据来源：GET /api/mobile/profile
 *   —— 姓名 / 电话 / 班次 / 名下车辆全部来自后端，
 *      前端不缓存档案内容（车与司机是后台绑定的，缓存了就会出现
 *      「后台换了车，司机端还显示旧车」）。
 *
 * ★ 非司机账号（管理员/调度员）调用本接口返回 is_driver = false 的空档案，
 *   后端不报错；这里给出明确说明，而不是显示一片空白。
 *
 * ★ 自动刷新：`onShow` 每次页面显示都重拉档案与账号信息 ——
 *   「我的」这一页最容易被后台改动（后台换了车 / 换了班次），
 *   缓存一次就会一直显示旧数据。
 *
 * ★ 退出登录必须断开实时推送（utils/socket.js 的 closeSocket）：
 *   登录态清掉但连接还挂着的话，换账号登录前会把上一个司机的消息推过来。
 *
 * ★ 角色卡片（本次新增）：同一个包里既有司机页也有管理端看板，
 *   「我是谁 / 我能用哪些页面」必须在这里说清楚，否则换个账号登录后
 *   用户只会觉得「底部导航怎么变了」。管理者从这里也能直接进看板。
 */
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import { shiftLabel } from '@/utils/format'
import { clearAuthStorage, getStoredUser } from '@/utils/storage'
import { closeSocket } from '@/utils/socket'
import { accountProfile, requireLogin, setUnread } from '@/utils/ui'

const profile = ref(null)
const loading = ref(false)
const errorMsg = ref('')
/** 登录接口返回的账号信息（档案接口挂了也能显示个大概） */
const account = ref(getStoredUser() || {})

/** 当前账号能做哪些事（与登录后分流用的是同一个判断） */
const accountInfo = computed(() => accountProfile(account.value))

const vehicleStatusLabel = (status) => {
  const map = { idle: '空闲', busy: '执行中', running: '执行中', maintenance: '维修中' }
  return map[status] || status || '—'
}

/**
 * ★ 跳转一律用 redirectTo：pages.json 的 tabBar 已删除，这些页面不再是
 *   tabBar 页面，uni.switchTab 会失效（fail: tabBar page not found）。
 *   redirectTo 关掉当前页再开目标页，栈深度恒为 1。
 */
function goBoard() {
  uni.redirectTo({ url: '/pages/board/index' })
}

function goTrips() {
  uni.redirectTo({ url: '/pages/trips/index' })
}

async function load() {
  if (!requireLogin()) return
  // 账号信息每次进页面都重新读：不再用 computed 缓存（computed 没有响应式依赖
  // 时会永远记住第一次的值，换账号后显示的还是上一个人）
  account.value = getStoredUser() || {}
  loading.value = true
  errorMsg.value = ''
  try {
    profile.value = await api.fetchProfile()
  } catch (err) {
    errorMsg.value = err.message || '加载档案失败'
    profile.value = null
  } finally {
    loading.value = false
  }
}

function logout() {
  uni.showModal({
    title: '退出登录',
    content: '将清除本机登录状态，需要重新输入账号密码。',
    success: (res) => {
      if (!res.confirm) return
      // 先断推送再清登录态：顺序反了会出现「连接还在但没有 token」的窗口期
      closeSocket()
      clearAuthStorage()
      // 未读数存在 utils/ui.js 的模块级状态里，会跨页面存活，退出时清掉
      setUnread(0)
      uni.reLaunch({ url: '/pages/login/login' })
    },
  })
}

// onShow 而不是 onMounted/onLoad：这一页每次切回来都重拉，
// 后台改了车辆/班次立刻能看到
onShow(() => {
  load()
})
</script>

<template>
  <view class="page">
    <!-- 顶部账号卡 -->
    <view class="card user-card">
      <view class="avatar">{{ (profile?.driver_name || account.nickname || account.username || '司').slice(0, 1) }}</view>
      <view class="user-info">
        <view class="user-name">
          {{ profile?.driver_name || profile?.nickname || account.nickname || account.username || '未登录' }}
        </view>
        <view class="user-sub muted">
          {{ profile?.driver_code ? `工号 ${profile.driver_code} · ` : '' }}{{ account.username || '' }}
        </view>
      </view>
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试 -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load">重 试</button>
    </view>

    <!-- 角色卡片：说明这个账号能用哪些页面 -->
    <view class="card">
      <view class="card-title">当前账号</view>
      <view class="row">
        <text class="row-label">用户名</text>
        <text class="row-value">{{ account.username || '—' }}</text>
      </view>
      <view class="row">
        <text class="row-label">角色</text>
        <text class="row-value">{{ (account.role_names || []).join('、') || (account.roles || []).join('、') || '—' }}</text>
      </view>
      <view class="row">
        <text class="row-label">可用界面</text>
        <text class="row-value">
          <text class="tag" :class="accountInfo.isDriver ? 'tag-done' : 'tag-planned'">
            {{ accountInfo.isDriver ? '司机（趟次/打卡）' : '非司机' }}
          </text>
          <text class="tag" :class="accountInfo.canViewBoard ? 'tag-done' : 'tag-planned'">
            {{ accountInfo.canViewBoard ? '管理看板（只读）' : '无看板权限' }}
          </text>
        </text>
      </view>
      <view class="quick-actions">
        <view v-if="accountInfo.isDriver" class="quick-btn" @click="goTrips">去我的趟次 ›</view>
        <view v-if="accountInfo.canViewBoard" class="quick-btn" @click="goBoard">去今日看板 ›</view>
      </view>
    </view>

    <template v-if="profile">
      <!-- 非司机账号明确提示 -->
      <view v-if="!profile.is_driver" class="card notice">
        当前账号「{{ profile.username }}」没有绑定司机档案，
        因此看不到趟次与车辆信息。请在后台「基础数据 → 司机」里把该账号绑定到司机档案。
      </view>

      <!-- 档案 -->
      <view class="card">
        <view class="card-title">司机档案</view>
        <view class="row">
          <text class="row-label">姓名</text>
          <text class="row-value">{{ profile.driver_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">工号</text>
          <text class="row-value">{{ profile.driver_code || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">电话</text>
          <text class="row-value">{{ profile.driver_phone || profile.phone || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">班次</text>
          <text class="row-value">{{ shiftLabel(profile.shift) }}</text>
        </view>
        <view class="row">
          <text class="row-label">在岗状态</text>
          <text class="row-value">
            <text class="tag" :class="profile.driver_status === 'active' ? 'tag-done' : 'tag-planned'">
              {{ profile.driver_status || '—' }}
            </text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">名下车辆</text>
          <text class="row-value">{{ profile.vehicle_count }} 台</text>
        </view>
      </view>

      <!-- 名下车辆 -->
      <view class="card">
        <view class="card-title">名下车辆</view>
        <view v-if="!profile.vehicles || !profile.vehicles.length" class="muted no-vehicle">
          暂无绑定车辆，请联系调度员在后台把车辆指派到你的司机档案。
        </view>
        <view v-for="vehicle in profile.vehicles" :key="vehicle.id" class="vehicle-item">
          <view class="vehicle-head">
            <text class="vehicle-plate">{{ vehicle.plate_no }}</text>
            <text class="tag" :class="vehicle.status === 'idle' ? 'tag-done' : 'tag-running'">
              {{ vehicleStatusLabel(vehicle.status) }}
            </text>
          </view>
          <view class="row">
            <text class="row-label">车型</text>
            <text class="row-value">
              {{ vehicle.vehicle_type_name || vehicle.vehicle_type_code || '—' }}
            </text>
          </view>
          <view class="row">
            <text class="row-label">地形能力</text>
            <text class="row-value">{{ vehicle.terrain_capability || '—' }}</text>
          </view>
        </view>
      </view>
    </template>

    <button class="btn btn-plain logout-btn" @click="logout">退出登录</button>
    <view class="foot-tip muted">司机端 v1.0 · 数据来自车辆智能调度系统</view>

    <BottomNav />
  </view>
</template>

<style scoped>
.user-card {
  display: flex;
  align-items: center;
}

.avatar {
  width: 100rpx;
  height: 100rpx;
  line-height: 100rpx;
  text-align: center;
  border-radius: 50%;
  background: #1668dc;
  color: #ffffff;
  font-size: 44rpx;
  margin-right: 24rpx;
}

.user-name {
  font-size: 34rpx;
  font-weight: 600;
}

.user-sub {
  font-size: 24rpx;
  margin-top: 8rpx;
}

.card-title {
  font-size: 28rpx;
  font-weight: 600;
  margin-bottom: 16rpx;
}

.notice {
  background: #fff4e6;
  color: #d97706;
  font-size: 26rpx;
  line-height: 1.6;
}

.quick-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 16rpx;
}

.quick-btn {
  flex: 1;
  text-align: center;
  background: #e8f2ff;
  color: #1668dc;
  border-radius: 12rpx;
  padding: 18rpx 0;
  font-size: 26rpx;
}

.vehicle-item {
  border-top: 1rpx solid #f0f1f3;
  padding-top: 16rpx;
  margin-top: 16rpx;
}

.vehicle-item:first-of-type {
  border-top: none;
  margin-top: 0;
  padding-top: 0;
}

.vehicle-head {
  display: flex;
  align-items: center;
  margin-bottom: 8rpx;
}

.vehicle-plate {
  font-size: 32rpx;
  font-weight: 700;
  letter-spacing: 2rpx;
}

.no-vehicle {
  font-size: 26rpx;
  line-height: 1.6;
}

.logout-btn {
  margin-top: 20rpx;
  color: #d03050;
  background: #ffffff;
  border: 1rpx solid #f0c0c8;
}

.foot-tip {
  text-align: center;
  font-size: 22rpx;
  padding: 24rpx 0 40rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
