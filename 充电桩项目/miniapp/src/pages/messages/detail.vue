<script setup>
/**
 * 消息详情。
 *
 * 数据来源：GET /messages/{id}
 *   ★ 后端在这个接口里**顺带把消息标记为已读**（见 api/messages_stats.py 的 message_detail），
 *     所以打开详情后未读数会变。这里不能自己「减 1」（重复进入同一条会越减越少，
 *     从推送点进来时还会和 App.vue 的更新打架），而是重新问一次服务端要 unread_count。
 *
 * ★ 关联单据跳转的取舍（写在这里免得后人再试一遍）：
 *   消息里只有 work_order_id，而小程序端**没有「按工单 id 打开工单详情」的页面**：
 *     · /pages/board/orders 是按 order_no / 名称 / 站点做模糊搜索的列表页，
 *       手上只有 id，拼不出可用的 keyword（拿 id 当关键词搜不到任何东西）；
 *     · /pages/tasks/detail 要的是**子任务 id**，不是工单 id，传错会 404。
 *   所以这里用 id 调一次 fetchWorkOrder 把「工单编号 + 名称」取出来展示清楚，
 *   按钮文案是「查看该工单的作业任务」，点击落到工单列表让用户按编号自己搜。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import * as api from '@/api'
import { formatDateTime } from '@/utils/format'
import { errorText, requireLogin, setUnread } from '@/utils/ui'

/**
 * 消息类型 → 标签配色。
 * ★ 与 pages/messages/index.vue 里的表保持一致：同一类消息在两页必须同色。
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

const messageId = ref('')
const message = ref(null)
/** 关联工单的编号/名称（只用于展示，见文件头说明） */
const orderBrief = ref(null)
const loading = ref(false)
const errorMsg = ref('')

function msgTagClass(type) {
  return MSG_TAG_CLASS[type] || 'tag-planned'
}

/** detail 是字符串时直接当正文段落显示 */
const detailText = computed(() => {
  const detail = message.value && message.value.detail
  return typeof detail === 'string' && detail ? detail : ''
})

/** detail 是对象时按 key: value 逐行渲染（字段名由后端给，前端不写死） */
const detailRows = computed(() => {
  const detail = message.value && message.value.detail
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return []
  return Object.keys(detail).map((key) => ({ label: key, value: detailValueText(detail[key]) }))
})

/** 明细值可能是数字/数组/嵌套对象，统一转成一句能读的话 */
function detailValueText(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const hasWorkOrder = computed(() => !!(message.value && message.value.work_order_id))
const hasFault = computed(() => !!(message.value && message.value.fault_id))
/**
 * link：后端可能给的是网页端路径或外部地址，小程序里打不开。
 * 只认 /pages/ 开头的站内页面，其余一律不显示按钮（比点了报错体面）。
 */
const hasLink = computed(() => {
  const link = message.value && message.value.link
  return !!link && String(link).indexOf('/pages/') === 0
})

/* ---------------- 加载 ---------------- */
async function load() {
  if (!requireLogin()) return
  if (!messageId.value) {
    message.value = null
    errorMsg.value = '缺少消息 ID，无法打开详情'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    message.value = await api.fetchMessage(messageId.value)
    orderBrief.value = null
    // 详情接口已把这条标记为已读 → 未读数以服务端为准
    syncUnread()
    if (message.value && message.value.work_order_id) {
      loadOrderBrief(message.value.work_order_id)
    }
  } catch (err) {
    message.value = null
    errorMsg.value = errorText(err, '加载消息详情失败')
  } finally {
    loading.value = false
  }
}

/** 未读数同步：只更新底部导航/列表的红点，失败不影响正文展示 */
async function syncUnread() {
  try {
    const data = await api.fetchMessageList({ page: 1, pageSize: 1 })
    setUnread((data && data.unread_count) || 0)
  } catch (err) {
    console.warn('[message-detail] 未读数同步失败', err)
  }
}

/** 关联工单信息：取不到（已删除 / 超出数据权限）只是少一段信息，不阻塞正文 */
async function loadOrderBrief(orderId) {
  try {
    const data = await api.fetchWorkOrder(orderId)
    orderBrief.value = (data && data.work_order) || null
  } catch (err) {
    orderBrief.value = null
    console.warn('[message-detail] 关联工单获取失败', err)
  }
}

/* ---------------- 跳转 ---------------- */
/** 落到工单列表：小程序端没有按工单 id 打开详情的页面，只能让用户按编号搜 */
function goOrders() {
  uni.redirectTo({ url: '/pages/board/orders' })
}

function goFault() {
  uni.navigateTo({ url: `/pages/fault/detail?id=${message.value.fault_id}` })
}

function openLink() {
  uni.navigateTo({
    url: String(message.value.link),
    fail: () => uni.showToast({ title: '该链接暂无法打开', icon: 'none' }),
  })
}

/** 返回消息列表：正常走返回栈；H5 直接刷新本页时没有上一页，退回列表兜底 */
function goBack() {
  if (getCurrentPages().length > 1) {
    uni.navigateBack()
    return
  }
  uni.redirectTo({ url: '/pages/messages/index' })
}

onLoad((options) => {
  messageId.value = String((options && options.id) || '')
  load()
})
</script>

<template>
  <view class="page page-plain">
    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <view class="btn btn-primary retry-btn" @click="load">重 试</view>
    </view>

    <template v-else-if="message">
      <!-- 正文：类型标签 + 标题 + 时间 + 内容 -->
      <view class="card">
        <view class="msg-head">
          <text class="tag" :class="msgTagClass(message.msg_type)">{{ message.msg_type }}</text>
          <text class="muted small">{{ formatDateTime(message.created_at) }}</text>
        </view>
        <view class="msg-title">{{ message.title }}</view>
        <view class="msg-content">{{ message.content || '（无正文）' }}</view>
      </view>

      <!-- 消息明细（后端给的结构化字段，例如工单编号/项目/站点/巡检人员） -->
      <view v-if="detailText || detailRows.length" class="card">
        <view class="section-title">消息明细</view>
        <view v-if="detailText" class="detail-text">{{ detailText }}</view>
        <view v-for="row in detailRows" :key="row.label" class="row">
          <text class="row-label">{{ row.label }}</text>
          <text class="row-value">{{ row.value }}</text>
        </view>
      </view>

      <!-- 投递与阅读状态：后端会多通道投递，这里如实展示渠道 -->
      <view class="card">
        <view class="row">
          <text class="row-label">投递渠道</text>
          <text class="row-value">{{ message.channel || '站内信' }}</text>
        </view>
        <view class="row">
          <text class="row-label">阅读状态</text>
          <text class="row-value">{{ message.is_read ? '已读' : '未读' }}</text>
        </view>
        <view class="row">
          <text class="row-label">阅读时间</text>
          <text class="row-value">
            {{ message.read_at ? formatDateTime(message.read_at) : '—' }}
          </text>
        </view>
        <view class="desc">打开本页时后端已把这条消息标记为已读</view>
      </view>

      <!-- 关联单据 -->
      <view v-if="hasWorkOrder || hasFault || hasLink" class="card">
        <view class="section-title">关联单据</view>

        <view v-if="hasWorkOrder" class="link-block">
          <view v-if="orderBrief" class="link-info">
            <text class="link-no">{{ orderBrief.order_no }}</text>
            <text class="link-sub">{{ orderBrief.order_name }}</text>
            <text class="link-sub muted">
              {{ orderBrief.status || '—' }} · {{ orderBrief.station_name || '—' }}
            </text>
          </view>
          <view v-else class="link-sub muted">
            关联工单信息暂不可见（可能已删除或超出当前账号的数据权限）
          </view>
          <view class="btn btn-default link-btn" @click="goOrders">查看该工单的作业任务</view>
        </view>

        <view v-if="hasFault" class="link-block">
          <view class="btn btn-default link-btn" @click="goFault">查看故障详情</view>
        </view>

        <view v-if="hasLink" class="link-block">
          <view class="btn btn-default link-btn" @click="openLink">打开关联页面</view>
        </view>
      </view>
    </template>

    <view class="back-row">
      <view class="btn btn-default back-btn" @click="goBack">返回消息列表</view>
    </view>
  </view>
</template>

<style scoped>
.msg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.msg-title {
  font-size: 32rpx;
  font-weight: 700;
  line-height: 1.5;
  margin-top: 16rpx;
}

.msg-content {
  font-size: 27rpx;
  color: #4b5563;
  line-height: 1.8;
  margin-top: 16rpx;
}

.detail-text {
  font-size: 26rpx;
  color: #4b5563;
  line-height: 1.8;
}

.small {
  font-size: 22rpx;
}

.link-block {
  margin-top: 8rpx;
}

.link-info {
  display: flex;
  flex-direction: column;
  margin-bottom: 16rpx;
}

.link-no {
  font-family: Consolas, Menlo, monospace;
  font-size: 28rpx;
  font-weight: 600;
}

.link-sub {
  font-size: 25rpx;
  color: #4b5563;
  margin-top: 6rpx;
  line-height: 1.6;
}

.link-btn {
  width: 100%;
}

.back-row {
  padding: 16rpx 0 40rpx;
}

.back-btn {
  width: 360rpx;
  margin: 0 auto;
}

.retry-btn {
  width: 320rpx;
  margin: 0 auto;
}
</style>
