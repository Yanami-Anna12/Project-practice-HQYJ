<script setup>
/**
 * 登录页。
 *
 * ★ 登录成功后有一步很容易漏、漏了整站都会失准：
 *   后端的 /auth/login **只返回 access_token 和 user，不返回权限点**，
 *   而小程序的「按角色分流」和「按钮显隐」全都依赖权限点。
 *   所以这里登录成功后必须紧接着调一次 /auth/profile，把 permissions + role
 *   一起写进本地缓存（utils/storage.js 的 setStoredProfile），再跳首页。
 *   少了这一步的表现是：管理员也被当成现场人员、核查按钮永远不出现。
 *
 * ★ 落地页由 utils/ui.js 的 accountProfile().home 决定，这里不写死：
 *   个人数据权限 → 运维工作台；站点/项目/平台数据 → 掌上看板。
 */
import { computed, reactive, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'

import * as api from '@/api'
import { API_BASE, DEMO_ACCOUNTS, PLATFORM_NAME } from '@/config'
import { connectNotificationSocket } from '@/utils/socket'
import { clearAuthStorage, setStoredProfile, setStoredUser, setToken } from '@/utils/storage'
import { accountProfile, errorText } from '@/utils/ui'

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const errorMsg = ref('')
/** 是否显示密码明文（现场戴手套输密码，看不到很容易输错） */
const showPassword = ref(false)

/** 后端地址：真机调试时最容易错的就是这里，直接显示出来省得排查 */
const serverHint = computed(() => API_BASE || '当前域名（H5 走 Vite 代理）')

/** 是否在小程序里（H5 有浏览器同源策略的问题，提示文案不一样） */
const isH5 = computed(() => PLATFORM_NAME === 'h5')

/** 一键填入演示账号 */
function fill(account) {
  form.username = account.username
  form.password = account.password
  errorMsg.value = ''
}

/**
 * 登录。
 * ★ 用 try/catch 把「网络不通」和「密码错误」分开提示：
 *   现场最常见的问题是后端没起 / 手机连的不是同一网段，
 *   这时候提示「用户名或密码错误」会让人白试很多次。
 */
async function submit() {
  if (loading.value) return
  if (!form.username.trim()) {
    errorMsg.value = '请输入用户名'
    return
  }
  if (!form.password) {
    errorMsg.value = '请输入密码'
    return
  }

  loading.value = true
  errorMsg.value = ''
  try {
    // 换账号前先清干净：否则上一位用户的权限点会残留，分流会错
    clearAuthStorage()

    const data = await api.login({ username: form.username.trim(), password: form.password })
    setToken(data.access_token)
    setStoredUser(data.user)

    // ★ 关键一步：拿权限点（登录响应里没有）
    const profile = await api.loadProfile()
    setStoredProfile(profile)
    setStoredUser(profile.user || data.user)

    // 建立未读推送连接（H5 拿不到 SocketTask 时内部会自动退化为定时刷新）
    connectNotificationSocket()

    const home = accountProfile(profile.user || data.user).home
    uni.showToast({ title: `欢迎，${(profile.user || data.user).real_name || ''}`, icon: 'none' })
    setTimeout(() => {
      uni.reLaunch({ url: home })
    }, 600)
  } catch (err) {
    errorMsg.value = errorText(err, '登录失败')
  } finally {
    loading.value = false
  }
}

onLoad((options) => {
  // 支持从别处带账号跳过来（例如以后从消息链接进来）
  if (options && options.username) form.username = options.username
})
</script>

<template>
  <view class="login-page">
    <view class="login-header">
      <view class="logo">⚡</view>
      <view class="app-name">充电桩运维</view>
      <view class="app-sub">运维管理 AI Agent 平台 · 移动作业端</view>
    </view>

    <view class="login-card">
      <view class="form-item">
        <text class="form-label">账号</text>
        <input
          v-model="form.username"
          class="form-input"
          type="text"
          placeholder="请输入用户名"
          placeholder-class="ph"
          :disabled="loading"
          confirm-type="next"
        />
      </view>

      <view class="form-item">
        <text class="form-label">密码</text>
        <view class="pwd-wrap">
          <input
            v-model="form.password"
            class="form-input pwd-input"
            :password="!showPassword"
            placeholder="请输入密码"
            placeholder-class="ph"
            :disabled="loading"
            confirm-type="done"
            @confirm="submit"
          />
          <text class="pwd-toggle" @click="showPassword = !showPassword">
            {{ showPassword ? '隐藏' : '显示' }}
          </text>
        </view>
      </view>

      <view v-if="errorMsg" class="login-error">{{ errorMsg }}</view>

      <button
        class="btn btn-primary login-btn"
        :class="loading ? 'btn-disabled' : ''"
        :disabled="loading"
        @click="submit"
      >
        {{ loading ? '登录中…' : '登 录' }}
      </button>

      <view class="server-hint">
        <text class="muted">后端地址：{{ serverHint }}</text>
        <text v-if="isH5" class="muted">（浏览器访问时走本地代理，无需配置）</text>
      </view>
    </view>

    <view class="demo-block">
      <view class="demo-title">
        <text class="muted">演示账号（点击自动填入）</text>
      </view>
      <view class="demo-grid">
        <view
          v-for="item in DEMO_ACCOUNTS"
          :key="item.username"
          class="demo-card"
          :class="{ 'demo-card-active': form.username === item.username }"
          @click="fill(item)"
        >
          <view class="demo-role">{{ item.label }}</view>
          <view class="demo-user">{{ item.username }}</view>
          <view class="demo-scope">{{ item.scope }}</view>
        </view>
      </view>
      <view class="demo-note">
        运维人员进「工作台」做巡检与报修；站点/项目/平台管理员进「掌上看板」。
      </view>
    </view>
  </view>
</template>

<style scoped>
/*
 * 登录页用了 navigationStyle: custom（隐藏系统导航栏），
 * 所以顶部要自己留出状态栏高度，否则内容会被刘海/状态栏压住。
 */
.login-page {
  min-height: 100vh;
  background: linear-gradient(180deg, #1677ff 0%, #1677ff 320rpx, #f5f6f8 320rpx, #f5f6f8 100%);
  padding: calc(120rpx + env(safe-area-inset-top)) 40rpx 60rpx;
  padding-top: calc(120rpx + constant(safe-area-inset-top));
  box-sizing: border-box;
}

.login-header {
  text-align: center;
  color: #ffffff;
  margin-bottom: 48rpx;
}

.logo {
  font-size: 72rpx;
  line-height: 1;
}

.app-name {
  font-size: 44rpx;
  font-weight: 700;
  margin-top: 16rpx;
  letter-spacing: 4rpx;
}

.app-sub {
  font-size: 24rpx;
  opacity: 0.85;
  margin-top: 12rpx;
}

.login-card {
  background: #ffffff;
  border-radius: 20rpx;
  padding: 28rpx 32rpx 32rpx;
  box-shadow: 0 8rpx 32rpx rgba(0, 0, 0, 0.08);
}

.ph {
  color: #b8bdc6;
}

.pwd-wrap {
  position: relative;
}

.pwd-input {
  padding-right: 110rpx;
}

.pwd-toggle {
  position: absolute;
  right: 24rpx;
  top: 50%;
  transform: translateY(-50%);
  font-size: 24rpx;
  color: #1677ff;
}

.login-error {
  margin-top: 20rpx;
  background: #fdecec;
  color: #d03050;
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  font-size: 25rpx;
  line-height: 1.6;
}

.login-btn {
  margin-top: 36rpx;
}

.server-hint {
  margin-top: 20rpx;
  font-size: 22rpx;
  line-height: 1.7;
  text-align: center;
}

.demo-block {
  margin-top: 40rpx;
}

.demo-title {
  text-align: center;
  font-size: 24rpx;
  margin-bottom: 20rpx;
}

.demo-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 20rpx;
}

.demo-card {
  width: calc(50% - 10rpx);
  box-sizing: border-box;
  background: #ffffff;
  border-radius: 16rpx;
  padding: 20rpx;
  border: 2rpx solid transparent;
}

.demo-card-active {
  border-color: #1677ff;
  background: #f0f6ff;
}

.demo-role {
  font-size: 28rpx;
  font-weight: 600;
}

.demo-user {
  font-size: 24rpx;
  color: #8a9099;
  margin-top: 8rpx;
}

.demo-scope {
  display: inline-block;
  font-size: 20rpx;
  color: #1677ff;
  background: #e8f2ff;
  border-radius: 16rpx;
  padding: 2rpx 12rpx;
  margin-top: 10rpx;
}

.demo-note {
  margin-top: 24rpx;
  font-size: 23rpx;
  color: #8a9099;
  line-height: 1.7;
  text-align: center;
}
</style>
