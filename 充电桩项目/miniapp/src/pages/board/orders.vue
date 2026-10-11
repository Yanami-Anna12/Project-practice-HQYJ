<script setup>
/**
 * 工单管理（管理端底部导航的「工单」）。
 *
 * 数据来源：GET /work-orders（关键词 / 状态 / 时效 / 类型 / 分页）
 *   后端按数据权限自动过滤（站点/项目/平台），前端不传任何范围参数 ——
 *   权限口径只有一个地方定义，页面不重复实现一遍。
 *
 * ★ 与现场作业端的区别：这一页**不是只读的**。
 *   站长/项目经理在手机上最常做的两个动作就是「接受工单」和
 *   「退回/取消并写清原因」，所以动作直接放在卡片底部。
 *   · 接受 → 二次确认（接受后执行人就是自己，点错了很麻烦）；
 *   · 退回 / 取消 → 强制填原因（后端也要 reason，空原因退回等于让人猜）。
 *
 * ★ 动作成功后**只重拉列表**，不清空 query：管理端经常是「筛出 overdue 的几张
 *   一张张处理」，整页刷新会把筛选条件一起丢掉，等于每次都要重新筛一遍。
 *
 * ★ 三组 chip 共用一个 query 对象：任何一组变化都要把 page 重置回 1，
 *   否则会带着第 3 页的页码去查一个新条件，结果是一片空白。
 */
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import {
  formatDate,
  orderStatusClass,
  orderTypeClass,
  progressPercent,
  taskStatusClass,
  timeStatusClass,
} from '@/utils/format'
import { accountProfile, errorText, requireLogin } from '@/utils/ui'

/** 与后端枚举一一对应的筛选值；「全部」= 不传该参数 */
const STATUS_CHIPS = ['全部', '待接单', '待完成', '已完成', '已退回']
const TIME_CHIPS = ['全部', '正常', '紧急', '逾期']
const TYPE_CHIPS = ['全部', '巡视', '特巡', '消缺', '设备检查', '其他']

const PAGE_SIZE = 10

/** 权限点：登录时由 /auth/profile 存到本地，这里读一次即可（页面每次进入都会重建） */
const profile = accountProfile()

const query = ref({
  keyword: '',
  status: '全部',
  timeStatus: '全部',
  orderType: '全部',
})
/** 输入框的草稿值：边打字边查会把后端打爆，点「搜索」才写进 query */
const keywordDraft = ref('')

const items = ref([])
const page = ref(1)
const total = ref(0)
const hasNext = ref(false)
const loading = ref(false)
const loadingMore = ref(false)
const errorMsg = ref('')

/** 正在提交的工单 id：防重复点击（连点两次「接受」会发两次请求） */
const submittingId = ref('')

/**
 * 已展开子任务的工单：{ [orderId]: { loading, error, items } }
 * ★ 用对象按需记录，而不是给每张卡一个 expanded 字段 ——
 *   列表一进来每张卡都展开会把页面撑到几屏高，找不到想找的工单。
 */
const expanded = ref({})

/** 列表底部提示：没有下一页时显示总数，比一个点不动的「加载更多」诚实 */
const listHint = computed(() => `共 ${total.value} 条工单`)

/* ---------------- 列表 ---------------- */
async function load(reset = true) {
  if (!requireLogin()) return
  if (reset) {
    page.value = 1
    loading.value = true
  } else {
    loadingMore.value = true
  }
  errorMsg.value = ''
  try {
    const data = await api.fetchWorkOrders({
      keyword: query.value.keyword || undefined,
      status: query.value.status === '全部' ? undefined : query.value.status,
      timeStatus: query.value.timeStatus === '全部' ? undefined : query.value.timeStatus,
      orderType: query.value.orderType === '全部' ? undefined : query.value.orderType,
      page: page.value,
      pageSize: PAGE_SIZE,
    })
    const list = (data && data.items) || []
    items.value = reset ? list : items.value.concat(list)
    total.value = Number((data && data.meta && data.meta.total) || 0)
    hasNext.value = !!(data && data.meta && data.meta.has_next)
  } catch (err) {
    if (reset) {
      items.value = []
      total.value = 0
      hasNext.value = false
      errorMsg.value = errorText(err, '加载工单失败')
    } else {
      // 加载更多失败只 toast：已经看到的列表不能因为翻页失败而消失
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

/** 三组 chip 通用：值没变就不重查，变了必须回到第 1 页 */
function setFilter(field, value) {
  if (query.value[field] === value) return
  query.value[field] = value
  load(true)
}

function applyKeyword() {
  query.value.keyword = keywordDraft.value.trim()
  load(true)
}

function resetFilters() {
  keywordDraft.value = ''
  query.value = { keyword: '', status: '全部', timeStatus: '全部', orderType: '全部' }
  load(true)
}

/* ---------------- 管理动作 ---------------- */
/** 二次确认（封装成 Promise 比嵌套回调好读，也让 fail 分支有兜底） */
function confirmModal({ title, content }) {
  return new Promise((resolve) => {
    uni.showModal({
      title,
      content,
      showCancel: true,
      confirmText: '确定',
      cancelText: '取消',
      success: (res) => resolve(!!res.confirm),
      // 弹窗被系统/H5 拦截时按「没确认」处理，绝不能当成已确认去改数据
      fail: () => resolve(false),
    })
  })
}

/**
 * 弹出可输入的原因框。
 * @returns {Promise<string|null>} null = 用户取消；'' = 确认了但没填内容
 */
function askReason(title) {
  return new Promise((resolve) => {
    uni.showModal({
      title,
      editable: true,
      placeholderText: '请填写原因',
      success: (res) => {
        if (!res.confirm) {
          resolve(null)
          return
        }
        resolve(String(res.content || '').trim())
      },
      fail: () => resolve(null),
    })
  })
}

async function acceptOrder(order) {
  if (submittingId.value) return
  const confirmed = await confirmModal({
    title: '接受工单',
    content: `确认接受 ${order.order_no}？接受后该工单的执行人就是你。`,
  })
  if (!confirmed) return
  submittingId.value = order.id
  try {
    // acceptWorkOrder 走 requestFull：后端提示语（如「工单已接受」）直接用 res.message
    const res = await api.acceptWorkOrder(order.id)
    uni.showToast({ title: res.message || '已接受工单', icon: 'none' })
    await load(true)
  } catch (err) {
    uni.showToast({ title: errorText(err, '接受工单失败'), icon: 'none' })
  } finally {
    submittingId.value = ''
  }
}

async function rejectOrder(order) {
  if (submittingId.value) return
  const reason = await askReason(`退回 ${order.order_no}`)
  if (reason === null) return
  // ★ 部分平台/旧版 H5 拿不到 editable 输入内容，这时必须明确提示，
  //   不能让用户以为「已经填过原因并且退回去了」
  if (!reason) {
    uni.showToast({ title: '请填写退回原因', icon: 'none' })
    return
  }
  submittingId.value = order.id
  try {
    const res = await api.rejectWorkOrder(order.id, reason)
    uni.showToast({ title: res.message || '已退回工单', icon: 'none' })
    await load(true)
  } catch (err) {
    uni.showToast({ title: errorText(err, '退回工单失败'), icon: 'none' })
  } finally {
    submittingId.value = ''
  }
}

async function cancelOrder(order) {
  if (submittingId.value) return
  const reason = await askReason(`取消 ${order.order_no}`)
  if (reason === null) return
  if (!reason) {
    uni.showToast({ title: '请填写取消原因', icon: 'none' })
    return
  }
  submittingId.value = order.id
  try {
    const res = await api.cancelWorkOrder(order.id, reason)
    uni.showToast({ title: res.message || '已取消工单', icon: 'none' })
    await load(true)
  } catch (err) {
    uni.showToast({ title: errorText(err, '取消工单失败'), icon: 'none' })
  } finally {
    submittingId.value = ''
  }
}

/* ---------------- 展开子任务 ---------------- */
function toggleSubtasks(order) {
  if (expanded.value[order.id]) {
    delete expanded.value[order.id]
    return
  }
  expanded.value[order.id] = { loading: true, error: '', items: [] }
  loadSubtasks(order.id)
}

async function loadSubtasks(orderId) {
  try {
    // 工单详情接口一次给回 work_order + subtasks，比分两次查省一个来回
    const data = await api.fetchWorkOrder(orderId)
    expanded.value[orderId] = { loading: false, error: '', items: (data && data.subtasks) || [] }
  } catch (err) {
    expanded.value[orderId] = {
      loading: false,
      error: errorText(err, '作业任务加载失败'),
      items: [],
    }
  }
}

function goSubtask(id) {
  uni.navigateTo({ url: `/pages/tasks/detail?id=${id}` })
}

// onShow：从作业任务详情返回、从别的页面切回来都要看到最新状态
onShow(() => {
  load(true)
})

onPullDownRefresh(async () => {
  await load(true)
  // ★ 必须调用，否则转圈会一直停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!-- 关键词搜索 -->
    <view class="card search-card">
      <input
        v-model="keywordDraft"
        class="form-input"
        type="text"
        placeholder="工单编号 / 名称 / 站点"
        confirm-type="search"
        @confirm="applyKeyword"
      />
      <view class="search-actions">
        <view class="btn btn-primary search-btn" @click="applyKeyword">搜 索</view>
        <view class="btn btn-plain search-btn" @click="resetFilters">重 置</view>
      </view>
    </view>

    <!-- 三组 chip 可叠加，共用一个 query -->
    <view class="filter-group">
      <view class="filter-label">状态</view>
      <view class="chip-row">
        <view
          v-for="item in STATUS_CHIPS"
          :key="item"
          class="chip"
          :class="query.status === item ? 'chip-active' : ''"
          @click="setFilter('status', item)"
        >
          {{ item }}
        </view>
      </view>
    </view>
    <view class="filter-group">
      <view class="filter-label">时效</view>
      <view class="chip-row">
        <view
          v-for="item in TIME_CHIPS"
          :key="item"
          class="chip"
          :class="query.timeStatus === item ? 'chip-active' : ''"
          @click="setFilter('timeStatus', item)"
        >
          {{ item }}
        </view>
      </view>
    </view>
    <view class="filter-group">
      <view class="filter-label">类型</view>
      <view class="chip-row">
        <view
          v-for="item in TYPE_CHIPS"
          :key="item"
          class="chip"
          :class="query.orderType === item ? 'chip-active' : ''"
          @click="setFilter('orderType', item)"
        >
          {{ item }}
        </view>
      </view>
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <view class="btn btn-primary retry-btn" @click="load(true)">重 试</view>
    </view>

    <view v-else-if="!items.length" class="empty">
      没有符合条件的工单，可放宽筛选条件或点「重置」
    </view>

    <template v-else>
      <view v-for="order in items" :key="order.id" class="card order-card">
        <view class="order-head">
          <text class="order-no">{{ order.order_no }}</text>
          <text class="tag" :class="orderTypeClass(order.order_type)">{{ order.order_type }}</text>
          <text class="tag" :class="orderStatusClass(order.status)">{{ order.status }}</text>
          <text class="tag" :class="timeStatusClass(order.time_status)">{{ order.time_status }}</text>
        </view>

        <view class="order-name">
          {{ order.order_name }}
          <!-- priority 是人工标的优先级，与 time_status（时效）不是一回事，单独标红 -->
          <text v-if="order.priority === '紧急'" class="tag tag-danger">优先级紧急</text>
        </view>

        <view class="row">
          <text class="row-label">站点</text>
          <text class="row-value">{{ order.station_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">执行人</text>
          <text class="row-value">{{ order.inspector_name || '未指派' }}</text>
        </view>
        <view class="row">
          <text class="row-label">计划日期</text>
          <text class="row-value">
            {{ formatDate(order.inspect_start_date) }} ~ {{ formatDate(order.inspect_end_date) }}
          </text>
        </view>

        <view class="progress-line">
          <view class="progress-bar">
            <view
              class="progress-inner"
              :style="{ width: progressPercent(order.subtask_done, order.subtask_total) + '%' }"
            />
          </view>
          <text class="progress-text">
            作业任务 {{ order.subtask_done || 0 }}/{{ order.subtask_total || 0 }}
            （{{ progressPercent(order.subtask_done, order.subtask_total) }}%）
          </text>
        </view>

        <!-- 退回/取消原因：管理端复查这张单时最需要看到的就是这两个原因 -->
        <view v-if="order.reject_reason" class="warn-bar reason-bar">
          退回原因：{{ order.reject_reason }}
        </view>
        <view v-if="order.cancel_reason" class="warn-bar reason-bar">
          取消原因：{{ order.cancel_reason }}
        </view>

        <view class="action-row">
          <view class="mini-btn" @click="toggleSubtasks(order)">
            {{ expanded[order.id] ? '收起作业任务' : '查看作业任务' }}
          </view>
          <template v-if="order.status === '待接单' && profile.canAccept">
            <view
              class="mini-btn mini-btn-primary"
              :class="submittingId === order.id ? 'mini-btn-disabled' : ''"
              @click="acceptOrder(order)"
            >
              {{ submittingId === order.id ? '提交中…' : '接受工单' }}
            </view>
            <view class="mini-btn mini-btn-danger" @click="rejectOrder(order)">退 回</view>
          </template>
          <view
            v-else-if="order.status === '待完成' && profile.canCancel"
            class="mini-btn mini-btn-danger"
            @click="cancelOrder(order)"
          >
            {{ submittingId === order.id ? '提交中…' : '取消工单' }}
          </view>
        </view>

        <!-- 展开的作业任务：一行 = 一个站点的巡检动作 -->
        <view v-if="expanded[order.id]" class="subtask-box">
          <view v-if="expanded[order.id].loading" class="muted small">作业任务加载中…</view>
          <view v-else-if="expanded[order.id].error" class="muted small">
            {{ expanded[order.id].error }}
          </view>
          <view v-else-if="!expanded[order.id].items.length" class="muted small">
            该工单还没有作业任务
          </view>
          <view
            v-for="sub in expanded[order.id].items"
            :key="sub.id"
            class="subtask-row"
            @click="goSubtask(sub.id)"
          >
            <view class="subtask-head">
              <text class="subtask-station">{{ sub.station_name || '未知站点' }}</text>
              <text class="tag" :class="taskStatusClass(sub.status)">{{ sub.status }}</text>
            </view>
            <view class="muted small">
              计划 {{ formatDate(sub.plan_date) }} · {{ sub.assignee_name || '未指派' }} ›
            </view>
          </view>
        </view>
      </view>

      <view v-if="hasNext" class="load-more" @click="loadMore">
        {{ loadingMore ? '加载中…' : '加载更多' }}
      </view>
      <view v-else class="list-hint muted">{{ listHint }}</view>
    </template>

    <BottomNav />
  </view>
</template>

<style scoped>
.search-card {
  padding: 20rpx 24rpx;
}

.search-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 16rpx;
}

.search-btn {
  flex: 1;
}

.filter-group {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 16rpx 20rpx 4rpx;
  margin-bottom: 16rpx;
}

.filter-label {
  font-size: 23rpx;
  color: #8a9099;
  margin-bottom: 12rpx;
}

.order-card {
  border-left: 8rpx solid #1677ff;
}

.order-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.order-no {
  font-size: 26rpx;
  font-weight: 600;
  font-family: Consolas, Menlo, monospace;
  margin-right: 12rpx;
}

.order-name {
  font-size: 29rpx;
  font-weight: 600;
  margin: 12rpx 0 8rpx;
  line-height: 1.5;
}

.progress-line {
  margin: 16rpx 0 4rpx;
}

.progress-text {
  display: block;
  font-size: 22rpx;
  color: #8a9099;
  margin-top: 8rpx;
}

/* 卡片内的原因块：比页面级 warn-bar 更轻，不抢整页的视觉重心 */
.reason-bar {
  margin: 12rpx 0 0;
  font-size: 24rpx;
  padding: 12rpx 18rpx;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  margin-top: 20rpx;
}

.mini-btn {
  flex: 1;
  min-width: 180rpx;
  text-align: center;
  font-size: 25rpx;
  padding: 16rpx 20rpx;
  border-radius: 12rpx;
  background: #f0f1f3;
  color: #4b5563;
}

.mini-btn-primary {
  background: #1677ff;
  color: #ffffff;
}

.mini-btn-danger {
  background: #ffffff;
  color: #d03050;
  border: 1rpx solid #d03050;
}

.mini-btn-disabled {
  background: #e6e8eb;
  color: #a3a8b0;
}

.subtask-box {
  margin-top: 20rpx;
  padding-top: 16rpx;
  border-top: 1rpx dashed #e6e8eb;
}

.subtask-row {
  background: #fafbfc;
  border-radius: 12rpx;
  padding: 16rpx 18rpx;
  margin-bottom: 12rpx;
}

.subtask-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.subtask-station {
  font-size: 27rpx;
  font-weight: 600;
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
