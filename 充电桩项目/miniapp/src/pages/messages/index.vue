<script setup>
/**
 * 消息中心（底部导航的「消息」）。
 *
 * 数据来源：GET /messages（类型 / 只看未读 / 分页，响应里带 unread_count）
 *   · 站内信是后端在各业务动作后自动写进来的（工单下发、退回、逾期、故障待核查…），
 *     本项目没有接微信订阅消息，所以这里是唯一的触达通道；
 *   · 未读数**只认服务端**：每次列表回来都用响应里的 unread_count 覆盖本地值，
 *     并同步到 utils/ui 的模块级状态（底部导航红点与这里必须同源）。
 *
 * ★ 实时推送：订阅后端的 /ws/notifications（报文 { type:'unread', unread_count, latest }）。
 *   页面可见时静默重拉列表（不显示「加载中」，用户正看着列表，整页闪一下很突兀）；
 *   不可见时只更新未读数，等 onShow 再拉，不给看不见的页面做无用功。
 *
 * ★ 点消息先**乐观**把本页这条标为已读再跳详情：
 *   详情接口本身会标已读，但如果等详情返回再改，用户返回列表时会看到
 *   「刚点过的消息还是未读」，观感像没生效。
 */
import { computed, ref } from 'vue'
import { onHide, onLoad, onShow, onUnload, onPullDownRefresh } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import { subscribeNotifications } from '@/utils/socket'
import { fromNow } from '@/utils/format'
import { errorText, requireLogin, setUnread, unreadFromPayload } from '@/utils/ui'

/**
 * 消息类型 → 标签配色。
 * ★ 写成一张表而不是 if 链：加一种消息类型只加一行，
 *   而且「哪几类算危险」一眼能看全（退回/取消/逾期都是要立刻处理的）。
 *   与 messages/detail.vue 里的表必须保持一致。
 */
const MSG_TAG_CLASS = {
  工单退回提醒: 'tag-danger',
  工单取消提醒: 'tag-danger',
  逾期工单提醒: 'tag-danger',
  紧急工单提醒: 'tag-warn',
  工单下发提醒: 'tag-running',
  故障待核查提醒: 'tag-pending',
  报告生成提醒: 'tag-planned',
  系统消息: 'tag-planned',
}

const PAGE_SIZE = 15

const items = ref([])
const types = ref([])
const unreadCount = ref(0)
const page = ref(1)
const total = ref(0)
const hasNext = ref(false)
const loading = ref(false)
const loadingMore = ref(false)
const errorMsg = ref('')
const readingAll = ref(false)

/** 当前选中的消息类型（「全部」= 不传 msg_type） */
const msgType = ref('全部')
/** 只看未读（对应后端的 is_read=false） */
const onlyUnread = ref(false)

/** 当前页面是否可见（onShow ~ onHide）：决定收到推送时要不要立刻重拉列表 */
const visible = ref(false)
/** 取消实时推送订阅（onUnload 时调用） */
let unsubscribe = null

/** 空态文案要能区分「筛掉了」和「本来就没有」 */
const emptyText = computed(() => {
  if (onlyUnread.value) return '全部已读，没有未读消息'
  if (msgType.value !== '全部') return `暂无「${msgType.value}」消息`
  return '暂无消息，有工单/故障变化时会收到站内信'
})

/** 类型标签配色（查表，缺省按「系统消息」的灰色处理） */
function msgTagClass(type) {
  return MSG_TAG_CLASS[type] || 'tag-planned'
}

/* ---------------- 加载 ---------------- */
/** 类型统计：失败不影响列表，chip 退化成只有「全部」 */
async function refreshTypes() {
  try {
    const list = await api.fetchMessageTypes()
    types.value = Array.isArray(list) ? list : []
  } catch (err) {
    console.warn('[messages] 消息类型统计获取失败', err)
  }
}

/**
 * @param {boolean} [reset]  true = 重新从第 1 页拉（默认）；false = 追加下一页
 * @param {boolean} [silent] true = 不显示「加载中」（推送触发的静默刷新）
 */
async function load(reset = true, silent = false) {
  if (!requireLogin()) return
  if (reset) {
    page.value = 1
    if (!silent) loading.value = true
  } else {
    loadingMore.value = true
  }
  if (!silent) errorMsg.value = ''
  try {
    // 列表与类型统计并行发：两个请求互不依赖，串行只是白等一个来回
    const [data] = await Promise.all([
      api.fetchMessageList({
        msgType: msgType.value === '全部' ? undefined : msgType.value,
        isRead: onlyUnread.value ? false : undefined,
        page: page.value,
        pageSize: PAGE_SIZE,
      }),
      refreshTypes(),
    ])
    const list = (data && data.items) || []
    items.value = reset ? list : items.value.concat(list)
    total.value = Number((data && data.meta && data.meta.total) || 0)
    hasNext.value = !!(data && data.meta && data.meta.has_next)
    // 未读数以服务端为准，同时刷新底部导航的红点
    const unread = Number((data && data.unread_count) || 0)
    unreadCount.value = unread
    setUnread(unread)
    // 成功即清掉旧的错误提示（静默刷新成功时也要清，否则错误框会一直挂在列表上面）
    errorMsg.value = ''
  } catch (err) {
    if (reset) {
      if (silent) {
        // 静默刷新（推送触发）失败时**保留用户正在看的列表**：整页换成错误框比旧数据更糟，
        // 下一次 onShow / 下拉刷新会再试
        console.warn('[messages] 静默刷新失败', err)
      } else {
        items.value = []
        total.value = 0
        hasNext.value = false
        errorMsg.value = errorText(err, '加载消息失败')
      }
    } else {
      // 翻页失败只 toast：已看到的列表不能因为翻页失败而清空
      uni.showToast({ title: errorText(err, '加载更多失败'), icon: 'none' })
    }
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function loadMore() {
  if (!hasNext.value || loadingMore.value) return
  page.value += 1
  load(false)
}

/** 切类型：重复点不重查，切了必须回到第 1 页 */
function pickType(type) {
  if (msgType.value === type) return
  msgType.value = type
  load(true)
}

function onOnlyUnreadChange(event) {
  onlyUnread.value = !!event.detail.value
  load(true)
}

/* ---------------- 已读 ---------------- */
/** 全部标记已读：成功后本地未读直接归零并重拉（类型 chip 的未读数也要跟着归零） */
async function readAll() {
  if (readingAll.value) return
  if (!unreadCount.value) {
    uni.showToast({ title: '没有未读消息', icon: 'none' })
    return
  }
  readingAll.value = true
  try {
    const res = await api.markAllMessagesRead()
    unreadCount.value = 0
    setUnread(0)
    uni.showToast({ title: `已标记 ${(res && res.updated) || 0} 条已读`, icon: 'none' })
    await load(true)
  } catch (err) {
    uni.showToast({ title: errorText(err, '标记已读失败'), icon: 'none' })
  } finally {
    readingAll.value = false
  }
}

/** 点消息：先乐观标已读，再进详情（详情接口也会标，双保险且不影响未读数最终一致） */
function openMessage(item) {
  if (!item.is_read) {
    item.is_read = true
    const next = Math.max(0, unreadCount.value - 1)
    unreadCount.value = next
    setUnread(next)
  }
  uni.navigateTo({ url: `/pages/messages/detail?id=${item.id}` })
}

onLoad(() => {
  // 实时未读推送：detail 页也会订阅同一份报文，各自只管自己的页面
  unsubscribe = subscribeNotifications((payload) => {
    if (!payload || payload.type !== 'unread') return
    const unread = unreadFromPayload(payload)
    if (unread !== null) {
      unreadCount.value = unread
      setUnread(unread)
    }
    if (visible.value) {
      // 正在看列表 → 静默重拉，新消息当场出现
      load(true, true)
    }
  })
})

onShow(() => {
  visible.value = true
  load(true)
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
  await load(true)
  // ★ 必须调用，否则转圈会一直停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!-- 顶部：未读总数 + 全部标记已读 -->
    <view class="toolbar">
      <view>
        <text class="title">消息中心</text>
        <text class="desc"> 未读 {{ unreadCount }} 条</text>
      </view>
      <view
        class="mini-btn"
        :class="unreadCount ? '' : 'mini-btn-disabled'"
        @click="readAll"
      >
        {{ readingAll ? '处理中…' : '全部标记已读' }}
      </view>
    </view>

    <!-- 消息类型：横向可滚动，类型多也不会把页面撑高 -->
    <scroll-view class="type-scroll" scroll-x>
      <view class="type-row">
        <view
          class="chip"
          :class="msgType === '全部' ? 'chip-active' : ''"
          @click="pickType('全部')"
        >
          全部
        </view>
        <view
          v-for="item in types"
          :key="item.type"
          class="chip"
          :class="msgType === item.type ? 'chip-active' : ''"
          @click="pickType(item.type)"
        >
          {{ item.type }}<text v-if="item.unread > 0" class="chip-unread">（{{ item.unread }}）</text>
        </view>
      </view>
    </scroll-view>

    <view class="switch-row">
      <text class="switch-label">只看未读</text>
      <switch :checked="onlyUnread" color="#1677ff" @change="onOnlyUnreadChange" />
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <view class="btn btn-primary retry-btn" @click="load(true)">重 试</view>
    </view>

    <view v-else-if="!items.length" class="empty">{{ emptyText }}</view>

    <template v-else>
      <view
        v-for="item in items"
        :key="item.id"
        class="card msg-card"
        :class="item.is_read ? '' : 'msg-unread'"
        @click="openMessage(item)"
      >
        <view class="msg-head">
          <text class="tag" :class="msgTagClass(item.msg_type)">{{ item.msg_type }}</text>
          <text class="muted small">{{ fromNow(item.created_at) }}</text>
        </view>
        <view class="msg-title-row">
          <view v-if="!item.is_read" class="red-dot" />
          <text class="msg-title" :class="item.is_read ? '' : 'msg-title-unread'">
            {{ item.title }}
          </text>
        </view>
        <view class="msg-content">{{ item.content || '（无消息正文，点开看详情）' }}</view>
      </view>

      <view v-if="hasNext" class="load-more" @click="loadMore">
        {{ loadingMore ? '加载中…' : '加载更多' }}
      </view>
      <view v-else class="list-hint muted">共 {{ total }} 条消息</view>
    </template>

    <BottomNav />
  </view>
</template>

<style scoped>
.mini-btn {
  background: #e8f2ff;
  color: #1677ff;
  font-size: 24rpx;
  padding: 12rpx 20rpx;
  border-radius: 10rpx;
}

.mini-btn-disabled {
  background: #f0f1f3;
  color: #a3a8b0;
}

/* 类型 chip 横滑：一行放不下就用手指滑，不换行、不压缩 */
.type-scroll {
  width: 100%;
  white-space: nowrap;
  margin-bottom: 12rpx;
}

.type-row {
  /*
   * inline-flex：让这一行按内容撑宽（超出 scroll-view 才滑得动）。
   * 用 flex 的话容器宽度被限制成 scroll-view 的宽度，横向滚动会失效。
   */
  display: inline-flex;
  flex-wrap: nowrap;
  gap: 16rpx;
  padding-bottom: 8rpx;
}

.type-row .chip {
  flex-shrink: 0;
}

.chip-unread {
  color: #d03050;
  font-weight: 600;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border-radius: 16rpx;
  padding: 10rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 26rpx;
}

.switch-label {
  color: #4b5563;
}

.msg-card {
  border-left: 8rpx solid #eef0f3;
}

.msg-unread {
  border-left-color: #1677ff;
}

.msg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.msg-title-row {
  display: flex;
  align-items: center;
  margin-top: 12rpx;
}

.msg-title {
  font-size: 29rpx;
  color: #1f2329;
  flex: 1;
}

/* 未读标题加粗，配合左侧红点，扫一眼就知道哪几条没看 */
.msg-title-unread {
  font-weight: 700;
}

/* 红点只做「未读」指示，缩成小圆点（全局 .red-dot 是给带数字的角标用的） */
.msg-title-row .red-dot {
  min-width: 16rpx;
  width: 16rpx;
  height: 16rpx;
  padding: 0;
  border-radius: 8rpx;
  margin-right: 12rpx;
  flex-shrink: 0;
}

/* 正文摘要最多两行：列表要的是「够判断要不要点进去」 */
.msg-content {
  color: #4b5563;
  font-size: 25rpx;
  line-height: 1.6;
  margin-top: 10rpx;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.small {
  font-size: 22rpx;
}

.load-more {
  text-align: center;
  color: #1677ff;
  font-size: 26rpx;
  padding: 20rpx 0 32rpx;
}

.list-hint {
  text-align: center;
  font-size: 22rpx;
  padding: 16rpx 0 32rpx;
}

.retry-btn {
  width: 320rpx;
  margin: 0 auto;
}
</style>
