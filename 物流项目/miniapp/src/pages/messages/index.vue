<script setup>
/**
 * 消息中心。
 *
 * 数据来源：GET /api/mobile/notifications
 *   · 消息是「任务下发」时后端自动写给司机的（见 services/mobile.py 的 notify_dispatch），
 *     本项目不做微信订阅消息（没有 openid），所以这里是唯一的触达通道。
 *   · 点未读消息会自动调 POST /notifications/{id}/read，
 *     后端返回 { id, is_read, unread } —— 未读数直接用它，不用再查一次。
 *
 * ★ 错误态 + 重试：弱网下消息列表经常一次拉不到，不能让司机看到白屏。
 *
 * ★ 自动刷新（本次修复的体验缺陷）：
 *   · `onShow` 每次页面显示都重拉 —— 从别的 tab 切回来就是最新的；
 *   · `onPullDownRefresh` 支持下拉刷新；
 *   · 订阅 WebSocket：后台刚下发的新消息会**当场**推到这一页，
 *     正在看就直接重拉列表（静默刷新，不闪「加载中」），
 *     没在看就只更新未读数，等 onShow 再拉。
 */
import { computed, ref } from 'vue'
import { onHide, onLoad, onShow, onUnload, onPullDownRefresh } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import { subscribeNotifications } from '@/utils/socket'
import { formatDateTime } from '@/utils/format'
import { accountProfile, requireLogin, setUnread, unreadFromPayload } from '@/utils/ui'

const messages = ref([])
const loading = ref(false)
const errorMsg = ref('')
const unread = ref(0)
const onlyUnread = ref(false)
const readingAll = ref(false)
/** 正在标记已读的消息 id：避免重复点击发多次请求 */
const readingId = ref(0)
/** 当前页面是否可见（onShow ~ onHide）：决定收到推送时要不要立刻重拉列表 */
const visible = ref(false)
/** 取消 WebSocket 订阅（onUnload 时调用） */
let unsubscribe = null

/**
 * 管理端账号（非司机）也能打开本页：站内消息接口只要求登录，
 * 「司机已确认接单」这类通知正是发给调度角色的，他们的底部导航里也有「消息」。
 * 这里仍给一句说明，让点进来的人知道这一页同时收两类消息。
 * ★ 不做强制跳转：强制 reLaunch 会和底部导航的选中态打架（闪一下又跳走）。
 */
const managerTip = computed(() => !accountProfile().isDriver)

const unreadCount = computed(() => messages.value.filter((m) => !m.is_read).length)

/**
 * 拉取消息列表。
 * @param {boolean} [silent] 静默刷新：不显示「加载中」，用于推送触发的刷新
 *                           （用户正看着列表，整页变成「加载中…」很突兀）
 */
async function load(silent = false) {
  if (!requireLogin()) return
  if (!silent) loading.value = true
  errorMsg.value = ''
  try {
    const data = await api.fetchNotifications({ onlyUnread: onlyUnread.value, limit: 50 })
    messages.value = Array.isArray(data) ? data : []
    await refreshUnread()
  } catch (err) {
    errorMsg.value = err.message || '加载消息失败'
    messages.value = []
  } finally {
    loading.value = false
  }
}

/** 未读数以服务端为准，并同步底部导航的红点 */
async function refreshUnread() {
  try {
    const res = await api.fetchUnreadCount()
    unread.value = res?.unread || 0
    setUnread(unread.value)
  } catch (err) {
    console.warn('[messages] 未读数获取失败', err)
  }
}

function toggleOnlyUnread() {
  onlyUnread.value = !onlyUnread.value
  load()
}

/** 点击消息：未读则先标记已读，再展示全文 */
async function openMessage(item) {
  if (!item.is_read && readingId.value !== item.id) {
    readingId.value = item.id
    try {
      const res = await api.markNotificationRead(item.id)
      item.is_read = true
      if (typeof res?.unread === 'number') {
        unread.value = res.unread
        setUnread(unread.value)
      }
    } catch (err) {
      // 标记失败不影响看内容，下次进页面会再试
      console.warn('[messages] 标记已读失败', err)
    } finally {
      readingId.value = 0
    }
  }

  uni.showModal({
    title: item.title,
    content: item.content || '（无内容）',
    showCancel: false,
    confirmText: '知道了',
  })
}

/** 全部标记已读（后端只有单条接口，这里逐条调用；失败即停并提示） */
async function readAll() {
  const targets = messages.value.filter((m) => !m.is_read)
  if (!targets.length) {
    uni.showToast({ title: '没有未读消息', icon: 'none' })
    return
  }
  readingAll.value = true
  let done = 0
  try {
    for (const item of targets) {
      const res = await api.markNotificationRead(item.id)
      item.is_read = true
      done += 1
      if (typeof res?.unread === 'number') {
        unread.value = res.unread
      }
    }
    setUnread(unread.value)
    uni.showToast({ title: `已标记 ${done} 条已读`, icon: 'none' })
    if (onlyUnread.value) await load()
  } catch (err) {
    uni.showToast({ title: `标记到第 ${done + 1} 条失败：${err.message || ''}`, icon: 'none' })
  } finally {
    readingAll.value = false
  }
}

onLoad(() => {
  // ★ 实时推送：收到新消息时（后端在「下发执行」后立即推）
  //   · 正在看这一页 → 静默重拉列表，司机当场看到新消息；
  //   · 没在看（在别的 tab / 页面）→ 只同步未读数，
  //     列表等 onShow 时再拉，避免给看不见的页面做无用功。
  // ★ 管理员撤销下发时后端会删掉对应的下发消息，并推一条
  //   biz_type=revoked 的报文（未读数走 unread_by_user）：这时**必须重拉**，
  //   否则那几条已经被删掉的消息还挂在列表上，点开是空的。
  unsubscribe = subscribeNotifications((payload) => {
    if (payload.type !== 'notification') return
    const bizType = payload.notification && payload.notification.biz_type
    const unreadNow = unreadFromPayload(payload)
    if (unreadNow !== null) {
      unread.value = unreadNow
      setUnread(unreadNow)
    }
    if (visible.value) {
      load(true)
      return
    }
    if (bizType === 'revoked' && unreadNow === null) {
      // 报文没带未读数（老后端）时兜底查一次
      refreshUnread()
    }
  })
})

onShow(() => {
  visible.value = true
  load()
})

onHide(() => {
  visible.value = false
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
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!-- 管理端账号：给一句说明，不强制跳转（会与底部导航的选中态打架） -->
    <view v-if="managerTip" class="card notice">
      当前账号是调度/管理角色，这里同时收「任务下发」与「司机已确认接单」两类通知。
      你可以在<b>「看板」</b>看到今日数字，在<b>「任务」</b>看到调度任务。
    </view>

    <view class="toolbar">
      <view>
        <text class="title">消息中心</text>
        <text class="desc"> 未读 {{ unread }} 条</text>
      </view>
      <view class="tool-actions">
        <view class="mini-btn" @click="toggleOnlyUnread">
          {{ onlyUnread ? '看全部' : '只看未读' }}
        </view>
        <view class="mini-btn" @click="readAll">
          {{ readingAll ? '处理中…' : '全部已读' }}
        </view>
      </view>
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试 -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load">重 试</button>
    </view>

    <view v-else-if="!messages.length" class="empty">
      {{ onlyUnread ? '没有未读消息' : '暂无消息，调度下发任务后会收到通知' }}
    </view>

    <view v-else>
      <view
        v-for="item in messages"
        :key="item.id"
        class="card msg-card"
        :class="item.is_read ? '' : 'msg-unread'"
        @click="openMessage(item)"
      >
        <view class="msg-head">
          <view class="msg-title">{{ item.title }}</view>
          <view v-if="!item.is_read" class="red-dot">未读</view>
        </view>
        <view class="msg-content">{{ item.content || '（无内容）' }}</view>
        <view class="msg-foot muted">
          <text>{{ formatDateTime(item.created_at) }}</text>
          <text class="msg-biz">{{ item.biz_type }}</text>
        </view>
      </view>
      <view class="list-hint muted">共 {{ messages.length }} 条（最多显示 50 条）</view>
    </view>

    <BottomNav />
  </view>
</template>

<style scoped>
.notice {
  background: #fff4e6;
  color: #d97706;
  font-size: 24rpx;
  line-height: 1.6;
}

.tool-actions {
  display: flex;
  gap: 12rpx;
}

.mini-btn {
  background: #e8f2ff;
  color: #1668dc;
  font-size: 24rpx;
  padding: 10rpx 18rpx;
  border-radius: 10rpx;
}

.msg-card {
  border-left: 8rpx solid #eef0f3;
}

.msg-unread {
  border-left-color: #1668dc;
}

.msg-head {
  display: flex;
  align-items: center;
}

.msg-title {
  font-size: 29rpx;
  font-weight: 600;
  flex: 1;
}

.msg-content {
  color: #4b5563;
  font-size: 26rpx;
  margin-top: 12rpx;
  line-height: 1.6;
}

.msg-foot {
  display: flex;
  justify-content: space-between;
  font-size: 22rpx;
  margin-top: 16rpx;
}

.msg-biz {
  color: #a3a8b0;
}

.list-hint {
  text-align: center;
  font-size: 22rpx;
  padding: 16rpx 0 32rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
