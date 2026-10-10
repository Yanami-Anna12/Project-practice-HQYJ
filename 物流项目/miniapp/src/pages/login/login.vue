<script setup>
/**
 * 登录页。
 *
 * ★ 登录复用管理端的 POST /api/auth/login（账号密码），不做微信登录：
 *   后端没有 openid 体系（见 backend/app/routers/mobile.py 的模块注释），
 *   司机账号本身就是后台建好的，与调度员/管理员同一套 RBAC。
 *
 * ★ 登录后**按角色分流**（本次新增）：
 *   调 /api/me 拿角色与权限（登录响应里的 user 已经是同一份内容，
 *   但这里再确认一次，避免 token 与本地缓存不一致）：
 *     · 含「司机」身份（mobile:use 权限或 driver 角色）→ 我的趟次；
 *     · 含调度/管理员权限（scheduling:read）→ 今日看板（只读）。
 *   多角色账号（如 multi = 调度员 + 只读观察者）司机优先：能干活的身份优先。
 *   两者都不是（没配权限的账号）→ 留在登录页并说明原因，不把人扔进空白页。
 *
 * 演示账号一键填入：现场演示时手打账号太慢，也容易打错。
 */
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import * as api from '@/api'
import { API_BASE, DEMO_ACCOUNTS } from '@/config'
import { accountProfile } from '@/utils/ui'
import { getToken, setStoredUser, setToken } from '@/utils/storage'
import { connectSocket, resetSocket } from '@/utils/socket'

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

// 后端地址显示在页面上：现场「连不上」时第一眼就能看出是不是地址配错了
const apiBase = API_BASE || '（H5 代理 /api → 后端）'

onLoad(() => {
  // 已登录直接进自己的首页，避免重复登录
  if (getToken()) {
    const profile = accountProfile()
    uni.reLaunch({ url: profile.home || '/pages/trips/index' })
  }
})

/** 一键填入演示账号 */
function useDemo(account) {
  username.value = account.username
  password.value = account.password
  errorMsg.value = ''
}

// ★ 用 :value + @input 而不是 v-model：
//   uni-app 的 <input> 是原生组件，v-model 在部分小程序基础库上不生效
function onUsernameInput(e) {
  username.value = e.detail.value
}

function onPasswordInput(e) {
  password.value = e.detail.value
}

async function handleLogin() {
  if (!username.value.trim()) {
    errorMsg.value = '请输入用户名'
    return
  }
  if (!password.value) {
    errorMsg.value = '请输入密码'
    return
  }

  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api.login({
      username: username.value.trim(),
      password: password.value,
    })
    setToken(res.token)
    setStoredUser(res.user)

    // ★ 登录后再取一次 /api/me：以服务端此刻的角色/权限为准做分流。
    //   登录取到的 user 与它是同一份数据，但多这一次调用能避免
    //   「本地缓存的旧角色把人带进没有权限的页面」。
    let user = res.user
    try {
      user = await api.fetchMe()
      setStoredUser(user)
    } catch (err) {
      console.warn('[login] /api/me 获取失败，改用登录响应里的用户信息', err)
    }

    // 按角色分流（底部导航由 BottomNav 组件自己按账号渲染，这里不用再改文字）
    const profile = accountProfile(user)
    // ★ 登录成功立刻建立实时推送连接（可能刚退出过别的账号，先 reset 清掉旧连接）
    resetSocket()
    connectSocket()

    if (!profile.home) {
      errorMsg.value =
        '该账号既没有司机身份，也没有调度查看权限，无法进入小程序。' +
        '请在后台为账号绑定司机档案或分配角色。'
      return
    }

    uni.showToast({
      title: profile.isDriver ? '登录成功' : '登录成功（只读看板）',
      icon: 'success',
    })
    uni.reLaunch({ url: profile.home })
  } catch (err) {
    // 401 是账号密码错误，0 是网络不通 —— 两种都要说清楚，不要只说「失败」
    if (err.code === 401) {
      errorMsg.value = '用户名或密码错误'
    } else if (err.code === 0) {
      errorMsg.value = err.message || '无法连接后端服务，请确认后端已启动'
    } else {
      errorMsg.value = err.message || '登录失败，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <view class="login-page">
    <view class="login-head">
      <view class="logo">调</view>
      <view class="login-title">车辆智能调度</view>
      <view class="login-sub">司机登录后看趟次并确认接单；调度/管理员登录后看今日看板（只读）</view>
    </view>

    <view class="card">
      <view class="field">
        <text class="field-label">用户名</text>
        <input
          class="field-input"
          type="text"
          placeholder="请输入用户名"
          :value="username"
          @input="onUsernameInput"
        />
      </view>
      <view class="field">
        <text class="field-label">密码</text>
        <input
          class="field-input"
          password
          placeholder="请输入密码"
          :value="password"
          @input="onPasswordInput"
        />
      </view>

      <view v-if="errorMsg" class="login-error">{{ errorMsg }}</view>

      <button class="btn btn-primary login-btn" :disabled="loading" @click="handleLogin">
        {{ loading ? '登录中…' : '登 录' }}
      </button>
    </view>

    <view class="card">
      <view class="desc">演示账号（点击一键填入）</view>
      <view class="demo-list">
        <view
          v-for="item in DEMO_ACCOUNTS"
          :key="item.username"
          class="demo-item"
          @click="useDemo(item)"
        >
          <text class="demo-name">{{ item.username }}</text>
          <text class="muted">/ {{ item.password }}</text>
          <text class="demo-tag">{{ item.label }}</text>
        </view>
      </view>
    </view>

    <view class="login-foot muted">后端地址：{{ apiBase }}</view>
  </view>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  padding: 120rpx 40rpx 40rpx;
  box-sizing: border-box;
  background: linear-gradient(180deg, #1668dc 0%, #f5f6f8 42%);
}

.login-head {
  text-align: center;
  margin-bottom: 48rpx;
}

.logo {
  width: 112rpx;
  height: 112rpx;
  line-height: 112rpx;
  margin: 0 auto 20rpx;
  border-radius: 28rpx;
  background: #ffffff;
  color: #1668dc;
  font-size: 52rpx;
  font-weight: 700;
}

.login-title {
  color: #ffffff;
  font-size: 38rpx;
  font-weight: 600;
}

.login-sub {
  color: rgba(255, 255, 255, 0.85);
  font-size: 24rpx;
  margin-top: 12rpx;
}

.field {
  margin-bottom: 28rpx;
}

.field-label {
  display: block;
  color: #4b5563;
  font-size: 26rpx;
  margin-bottom: 12rpx;
}

.field-input {
  height: 84rpx;
  background: #f5f6f8;
  border-radius: 12rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
}

.login-error {
  color: #d03050;
  font-size: 26rpx;
  margin-bottom: 16rpx;
}

.login-btn {
  margin-top: 8rpx;
}

.demo-list {
  margin-top: 16rpx;
}

.demo-item {
  display: flex;
  align-items: center;
  padding: 18rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}

.demo-item:last-child {
  border-bottom: none;
}

.demo-name {
  font-size: 28rpx;
  color: #1668dc;
}

.demo-tag {
  margin-left: auto;
  font-size: 22rpx;
  color: #8a9099;
}

.login-foot {
  text-align: center;
  font-size: 22rpx;
  margin-top: 16rpx;
  word-break: break-all;
}
</style>
