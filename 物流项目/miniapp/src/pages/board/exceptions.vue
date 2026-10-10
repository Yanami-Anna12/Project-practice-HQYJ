<script setup>
/**
 * 异常列表（管理端只读）。
 *
 * 数据来源：GET /api/scheduling/exceptions（网页端「异常重排」页读的是同一张表）
 *   · 显示类型、来源、状态、时间、payload 摘要；
 *   · payload 是后端存的 JSON 文本：司机端上报的（source = driver:<工号>）
 *     里面有门店/趟次/备注，调度员上报的则多为空对象。这里解析失败一律
 *     退化为原文 —— 一条脏记录不能让整页崩掉。
 *   · 点卡片可展开查看完整 payload。
 *
 * ★ 只读：处理异常（重排）需要 scheduling:replan 权限，仍在网页端做。
 */
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import {
  exceptionSourceText,
  exceptionStatusClass,
  exceptionStatusText,
  exceptionTypeLabel,
  formatFullDateTime,
} from '@/utils/format'
import { requireLogin } from '@/utils/ui'

const events = ref([])
const loading = ref(false)
const errorMsg = ref('')
const forbidden = ref(false)
/** 只看待处理 */
const onlyPending = ref(false)
/** 展开的异常 id */
const expandedId = ref(0)

const shown = computed(() =>
  onlyPending.value ? events.value.filter((e) => e.status === 'pending') : events.value,
)
const pendingCount = computed(() => events.value.filter((e) => e.status === 'pending').length)

/**
 * payload 摘要：JSON 文本 → 一行可读文本。
 * 优先挑调度最关心的键（与后端看板摘要的口径一致）。
 */
function payloadSummary(raw) {
  const text = String(raw || '').trim()
  if (!text || text === '{}') return ''
  let value = null
  try {
    value = JSON.parse(text)
  } catch (err) {
    return text.slice(0, 80)
  }
  if (!value || typeof value !== 'object') return String(value).slice(0, 80)
  const preferred = ['备注', '上报人', '司机姓名', '趟次', '门店ID', '计划明细ID', '原因', '说明']
  const parts = []
  preferred.forEach((key) => {
    const item = value[key]
    if (item !== undefined && item !== null && item !== '' && !(Array.isArray(item) && !item.length)) {
      parts.push(`${key}=${item}`)
    }
  })
  if (!parts.length) {
    Object.keys(value)
      .slice(0, 4)
      .forEach((key) => {
        const item = value[key]
        if (item === undefined || item === null || item === '' || item === '{}') return
        parts.push(`${key}=${item}`)
      })
  }
  return parts.join('；').slice(0, 100)
}

/** payload 美化（展开时显示） */
function payloadPretty(raw) {
  const text = String(raw || '').trim()
  if (!text || text === '{}') return '（无附加信息）'
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch (err) {
    return text
  }
}

function toggle(item) {
  expandedId.value = expandedId.value === item.id ? 0 : item.id
}

function toggleOnlyPending() {
  onlyPending.value = !onlyPending.value
}

async function load() {
  if (!requireLogin()) return
  loading.value = true
  errorMsg.value = ''
  forbidden.value = false
  try {
    const data = await api.fetchExceptions()
    events.value = Array.isArray(data) ? data : []
  } catch (err) {
    if (err.code === 403) {
      forbidden.value = true
      errorMsg.value = '当前账号没有查看异常的权限（需要 scheduling:read）'
    } else {
      errorMsg.value = err.message || '加载异常列表失败'
    }
    events.value = []
  } finally {
    loading.value = false
  }
}

onShow(load)

onPullDownRefresh(async () => {
  await load()
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <view class="toolbar">
      <view>
        <text class="title">异常事件</text>
        <text class="desc"> 待处理 {{ pendingCount }} / 共 {{ events.length }}</text>
      </view>
      <view class="mini-btn" @click="toggleOnlyPending">
        {{ onlyPending ? '看全部' : '只看待处理' }}
      </view>
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button v-if="!forbidden" class="btn btn-primary retry-btn" @click="load">重 试</button>
      <view v-else class="muted forbidden-tip">司机账号请用「趟次」tab 上报异常。</view>
    </view>

    <view v-else-if="!shown.length" class="empty">
      {{ onlyPending ? '没有待处理的异常' : '暂无异常事件' }}
    </view>

    <view v-else>
      <view
        v-for="item in shown"
        :key="item.id"
        class="card exc-card"
        :class="item.status === 'pending' ? 'exc-pending' : ''"
        @click="toggle(item)"
      >
        <view class="exc-head">
          <text class="exc-type">{{ exceptionTypeLabel(item.event_type) }}</text>
          <text class="tag" :class="exceptionStatusClass(item.status)">
            {{ exceptionStatusText(item.status) }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">来源</text>
          <text class="row-value">{{ exceptionSourceText(item.source) }}</text>
        </view>
        <view class="row">
          <text class="row-label">关联任务</text>
          <text class="row-value">#{{ item.task_id }}</text>
        </view>
        <view class="row">
          <text class="row-label">发生时间</text>
          <text class="row-value">{{ formatFullDateTime(item.occurred_at) }}</text>
        </view>
        <view v-if="payloadSummary(item.payload)" class="exc-summary">
          {{ payloadSummary(item.payload) }}
        </view>

        <!-- 展开看原始 payload -->
        <view v-if="expandedId === item.id" class="exc-payload">
          <view class="payload-title muted">原始 payload</view>
          <text class="payload-body">{{ payloadPretty(item.payload) }}</text>
        </view>
        <view class="exc-foot muted">
          {{ expandedId === item.id ? '收起详情 ⌃' : '展开查看详情 ⌄' }}
        </view>
      </view>
    </view>
  </view>
</template>

<style scoped>
.mini-btn {
  background: #e8f2ff;
  color: #1668dc;
  font-size: 24rpx;
  padding: 10rpx 18rpx;
  border-radius: 10rpx;
}

.exc-card {
  border-left: 8rpx solid #d9dee5;
}

.exc-pending {
  border-left-color: #d97706;
}

.exc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8rpx;
}

.exc-type {
  font-size: 30rpx;
  font-weight: 600;
}

.exc-summary {
  font-size: 24rpx;
  color: #4b5563;
  margin-top: 12rpx;
  line-height: 1.5;
}

.exc-payload {
  background: #f5f6f8;
  border-radius: 12rpx;
  padding: 16rpx;
  margin-top: 12rpx;
}

.payload-title {
  font-size: 22rpx;
  margin-bottom: 8rpx;
}

.payload-body {
  font-size: 22rpx;
  color: #4b5563;
  white-space: pre-wrap;
  word-break: break-all;
}

.exc-foot {
  margin-top: 12rpx;
  font-size: 22rpx;
}

.forbidden-tip {
  font-size: 24rpx;
  line-height: 1.6;
}

.retry-btn {
  width: 320rpx;
}
</style>
