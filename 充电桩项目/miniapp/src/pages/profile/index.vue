<script setup>
/**
 * 我的（个人中心）。
 *
 * 现场人员在这里确认三件事：
 *   ① 我是谁、有什么权限（数据权限决定他能看到哪些站点的数据）；
 *   ② 我干得怎么样（我的工单 / 我上报的故障）；
 *   ③ 换密码、退出登录。
 *
 * ★ 「数据权限」这一行是刻意放大的：现场最常见的一类问题是
 *   「为什么我看不到某个站的工单」—— 答案几乎总是账号的数据权限范围不对，
 *   显示出来就不用每次都去后台查。
 */
import { computed, reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'

import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import { API_BASE } from '@/config'
import { closeNotificationSocket } from '@/utils/socket'
import { clearAuthStorage, getStoredUser, setStoredUser } from '@/utils/storage'
import { accountProfile, errorText, requireLogin, setUnread } from '@/utils/ui'

const loading = ref(false)
const errorMsg = ref('')
const orderStats = ref({ total: 0, pending: 0, done: 0, completion_rate: 0 })
const faultCount = ref(0)

/** 当前缓存的账号信息（进页面先渲染，随后被 /auth/profile 的结果覆盖） */
const user = ref(getStoredUser() || {})
const profile = computed(() => accountProfile(user.value))
const roleName = computed(() => (profile.value.role && profile.value.role.name) || '未分配角色')
/** 头像用姓名首字（现场没有上传头像的需求，也不引第三方头像服务） */
const initial = computed(() => {
  const name = user.value.real_name || user.value.username || '?'
  return String(name).slice(0, 1)
})

/* ------------------------------------------------------------------ *
 * 修改密码
 * ------------------------------------------------------------------ */
const pwdOpen = ref(false)
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirm: '' })
const pwdSubmitting = ref(false)

/**
 * 改密码。
 * ★ 前端只做「两次输入一致 + 长度」的校验，不复刻后端的强度规则 ——
 *   两套规则迟早会不一致，真正的校验以后端返回的 message 为准。
 */
async function submitPassword() {
  if (pwdSubmitting.value) return
  if (!pwdForm.oldPassword || !pwdForm.newPassword) {
    uni.showToast({ title: '请填写原密码与新密码', icon: 'none' })
    return
  }
  if (pwdForm.newPassword !== pwdForm.confirm) {
    uni.showToast({ title: '两次输入的新密码不一致', icon: 'none' })
    return
  }
  if (pwdForm.newPassword.length < 6) {
    uni.showToast({ title: '新密码至少 6 位', icon: 'none' })
    return
  }

  pwdSubmitting.value = true
  try {
    await api.changePassword({
      oldPassword: pwdForm.oldPassword,
      newPassword: pwdForm.newPassword,
    })
    pwdOpen.value = false
    pwdForm.oldPassword = ''
    pwdForm.newPassword = ''
    pwdForm.confirm = ''
    uni.showModal({
      title: '密码已修改',
      content: '下次登录请使用新密码。',
      showCancel: false,
      confirmText: '知道了',
    })
  } catch (err) {
    uni.showToast({ title: errorText(err, '修改失败'), icon: 'none', duration: 2800 })
  } finally {
    pwdSubmitting.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 编辑联系方式
 * ------------------------------------------------------------------ */
const contactOpen = ref(false)
const contactForm = reactive({ realName: '', phone: '', email: '' })
const contactSubmitting = ref(false)

function openContact() {
  contactForm.realName = user.value.real_name || ''
  contactForm.phone = user.value.phone || ''
  contactForm.email = user.value.email || ''
  contactOpen.value = true
}

async function submitContact() {
  if (contactSubmitting.value) return
  contactSubmitting.value = true
  try {
    const data = await api.updateProfile({
      real_name: contactForm.realName || null,
      phone: contactForm.phone || null,
      email: contactForm.email || null,
    })
    user.value = data || user.value
    setStoredUser(user.value)
    contactOpen.value = false
    uni.showToast({ title: '资料已更新', icon: 'success' })
  } catch (err) {
    uni.showToast({ title: errorText(err, '保存失败'), icon: 'none', duration: 2800 })
  } finally {
    contactSubmitting.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 数据加载
 * ------------------------------------------------------------------ */
async function load() {
  if (!requireLogin()) return
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await api.loadProfile()
    if (data && data.user) {
      user.value = data.user
      setStoredUser(data.user)
    }
  } catch (err) {
    errorMsg.value = errorText(err, '资料加载失败')
  }

  // 统计项失败不影响资料展示，各自兜底
  try {
    orderStats.value = (await api.fetchWorkOrderHome()) || orderStats.value
  } catch (err) {
    console.warn('[profile] 工单统计加载失败', err)
  }
  try {
    const faults = await api.fetchFaults({ mine: true, page: 1, pageSize: 1 })
    faultCount.value = (faults && faults.meta && faults.meta.total) || 0
  } catch (err) {
    console.warn('[profile] 故障统计加载失败', err)
  }
  loading.value = false
}

/* ------------------------------------------------------------------ *
 * 退出登录
 * ------------------------------------------------------------------ */
function doLogout() {
  uni.showModal({
    title: '退出登录',
    content: '退出后需要重新输入账号密码。',
    confirmText: '退出',
    confirmColor: '#d03050',
    success: async (res) => {
      if (!res.confirm) return
      try {
        await api.logout()
      } catch (err) {
        // 后端不可达也要能退出：本地登录态必须清掉，否则会卡在一个用不了的会话里
        console.warn('[profile] 退出接口调用失败，仍清本地登录态', err)
      }
      closeNotificationSocket()
      clearAuthStorage()
      setUnread(0)
      uni.reLaunch({ url: '/pages/login/login' })
    },
  })
}

onShow(() => {
  load()
})
</script>

<template>
  <view class="page">
    <!-- 身份卡 -->
    <view class="card profile-card">
      <view class="avatar">{{ initial }}</view>
      <view class="profile-main">
        <view class="profile-name">{{ user.real_name || user.username || '—' }}</view>
        <view class="profile-sub">{{ user.username }} · {{ roleName }}</view>
        <view class="profile-tags">
          <text class="tag tag-running">{{ profile.dataScope || '未知权限' }}</text>
          <text v-if="user.on_duty" class="tag tag-done">在岗</text>
          <text v-else class="tag tag-planned">离岗</text>
        </view>
      </view>
    </view>

    <view v-if="errorMsg" class="warn-bar">{{ errorMsg }}（下面显示的是本地缓存的信息）</view>

    <!-- 我的统计 -->
    <view class="stat-grid">
      <view class="stat-card">
        <view class="stat-value stat-primary">{{ orderStats.total || 0 }}</view>
        <view class="stat-label">我的工单</view>
      </view>
      <view class="stat-card">
        <view class="stat-value stat-warn">{{ orderStats.pending || 0 }}</view>
        <view class="stat-label">待办</view>
      </view>
      <view class="stat-card">
        <view class="stat-value stat-done">{{ orderStats.done || 0 }}</view>
        <view class="stat-label">已完成</view>
      </view>
      <view class="stat-card">
        <view class="stat-value">{{ faultCount }}</view>
        <view class="stat-label">我报的故障</view>
      </view>
    </view>

    <!-- 账号信息 -->
    <view class="section-title"><text>账号信息</text></view>
    <view class="card">
      <view class="row">
        <text class="row-label">所属项目</text>
        <text class="row-value">{{ user.project_name || '—' }}</text>
      </view>
      <view class="row">
        <text class="row-label">所属站点</text>
        <text class="row-value">{{ user.station_name || '不限（按权限范围）' }}</text>
      </view>
      <view class="row">
        <text class="row-label">手机号</text>
        <text class="row-value">{{ user.phone || '—' }}</text>
      </view>
      <view class="row">
        <text class="row-label">邮箱</text>
        <text class="row-value">{{ user.email || '—' }}</text>
      </view>
      <view class="row">
        <text class="row-label">技能标签</text>
        <text class="row-value">{{ user.skills || '—' }}</text>
      </view>
      <view class="row">
        <text class="row-label">上次登录</text>
        <text class="row-value">{{ user.last_login_at ? String(user.last_login_at).replace('T', ' ').slice(0, 16) : '—' }}</text>
      </view>
    </view>

    <!-- 权限说明：解释「为什么我看不到某些数据」 -->
    <view class="hint-bar">
      数据权限「{{ profile.dataScope || '—' }}」决定你能看到哪些工单、故障与充电桩：
      个人数据只看自己的，站点数据看本站点的，项目/平台数据看更大范围。
      任务列表为空时先确认这里。
    </view>

    <!-- 编辑联系方式（就地展开，不引第三方弹窗组件） -->
    <view class="section-title">
      <text>资料维护</text>
      <text class="section-more" @click="contactOpen ? (contactOpen = false) : openContact()">
        {{ contactOpen ? '收起' : '编辑' }}
      </text>
    </view>
    <view v-if="contactOpen" class="card">
      <view class="form-item">
        <text class="form-label">姓名</text>
        <input v-model="contactForm.realName" class="form-input" placeholder="请输入姓名" />
      </view>
      <view class="form-item">
        <text class="form-label">手机号</text>
        <input v-model="contactForm.phone" class="form-input" type="number" placeholder="请输入手机号" />
      </view>
      <view class="form-item">
        <text class="form-label">邮箱</text>
        <input v-model="contactForm.email" class="form-input" placeholder="请输入邮箱" />
      </view>
      <button
        class="btn btn-primary save-btn"
        :class="contactSubmitting ? 'btn-disabled' : ''"
        :disabled="contactSubmitting"
        @click="submitContact"
      >
        {{ contactSubmitting ? '保存中…' : '保存资料' }}
      </button>
    </view>

    <!-- 修改密码 -->
    <view class="section-title">
      <text>安全设置</text>
      <text class="section-more" @click="pwdOpen = !pwdOpen">
        {{ pwdOpen ? '收起' : '修改密码' }}
      </text>
    </view>
    <view v-if="pwdOpen" class="card">
      <view class="form-item">
        <text class="form-label form-label-required">原密码</text>
        <input v-model="pwdForm.oldPassword" class="form-input" password placeholder="请输入原密码" />
      </view>
      <view class="form-item">
        <text class="form-label form-label-required">新密码</text>
        <input v-model="pwdForm.newPassword" class="form-input" password placeholder="至少 6 位" />
      </view>
      <view class="form-item">
        <text class="form-label form-label-required">确认新密码</text>
        <input v-model="pwdForm.confirm" class="form-input" password placeholder="再输入一次新密码" />
      </view>
      <button
        class="btn btn-primary save-btn"
        :class="pwdSubmitting ? 'btn-disabled' : ''"
        :disabled="pwdSubmitting"
        @click="submitPassword"
      >
        {{ pwdSubmitting ? '提交中…' : '确认修改' }}
      </button>
    </view>

    <!-- 运行环境：真机连不上后端时，先看这一行 -->
    <view class="section-title"><text>运行环境</text></view>
    <view class="card">
      <view class="row">
        <text class="row-label">接口地址</text>
        <text class="row-value">{{ API_BASE || '当前域名（H5 走本地代理）' }}</text>
      </view>
      <view class="row">
        <text class="row-label">版本</text>
        <text class="row-value">运维移动作业端 1.0.0</text>
      </view>
    </view>

    <button class="btn btn-danger logout-btn" @click="doLogout">退出登录</button>

    <BottomNav />
  </view>
</template>

<style scoped>
.profile-card {
  display: flex;
  align-items: center;
}

.avatar {
  width: 120rpx;
  height: 120rpx;
  border-radius: 60rpx;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  color: #ffffff;
  font-size: 52rpx;
  font-weight: 700;
  text-align: center;
  line-height: 120rpx;
  flex-shrink: 0;
  margin-right: 24rpx;
}

.profile-main {
  flex: 1;
}

.profile-name {
  font-size: 38rpx;
  font-weight: 700;
}

.profile-sub {
  font-size: 24rpx;
  color: #8a9099;
  margin-top: 8rpx;
}

.profile-tags {
  margin-top: 12rpx;
}

.profile-tags .tag {
  margin-left: 0;
  margin-right: 12rpx;
}

.save-btn {
  margin-top: 28rpx;
}

.logout-btn {
  margin-top: 20rpx;
}
</style>
