<script setup>
/**
 * 任务详情（管理端只读）。
 *
 * 数据来源：
 *   GET /api/scheduling/tasks/{id}              任务 + 多套方案（用于方案对比）
 *   GET /api/scheduling/plans/{plan_id}/details 方案明细（每行含 accepted / accepted_at）
 *
 * ★ 每一趟能看到「该司机是否已确认接单」：
 *   明细行上的 accepted / accepted_at 由后端按 trip_key
 *   （task:plan:vehicle:trip）去 dispatch_record 匹配——确认就记在那张表上。
 *   本页把明细按「车辆 + 趟次」归并成趟次后逐趟展示确认状态
 *   （归并函数见 utils/format.js 的 groupPlanTrips，规则在后端注释里有说明）。
 *
 * ★ 只读页：可以切换方案查看，但不能确认/下发/重排。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import * as api from '@/api'
import {
  acceptStatusClass,
  acceptStatusText,
  formatDate,
  groupPlanTrips,
  stopStatusLabel,
  taskStatusClass,
  taskStatusText,
  timeWindowLabel,
} from '@/utils/format'
import { requireLogin } from '@/utils/ui'

const taskId = ref(0)
const detail = ref(null)
const loading = ref(false)
const errorMsg = ref('')
/** 当前查看的方案 id */
const planId = ref(0)
/** 方案明细：{ [planId]: { loading, error, trips } } */
const planCache = ref({})

const plans = computed(() => (detail.value && detail.value.plans) || [])
const currentPlan = computed(() => plans.value.find((p) => p.id === planId.value) || null)
const current = computed(() => planCache.value[planId.value] || { loading: false, error: '', trips: [] })

/** 当前方案的趟次汇总（未确认趟次单独提示） */
const tripSummary = computed(() => {
  const trips = current.value.trips || []
  return {
    total: trips.length,
    accepted: trips.filter((t) => t.accepted).length,
    pending: trips.filter((t) => !t.accepted).length,
  }
})

async function loadPlan(id, force = false) {
  if (!id) return
  if (!force && planCache.value[id] && !planCache.value[id].error) return
  planCache.value = { ...planCache.value, [id]: { loading: true, error: '', trips: [] } }
  try {
    const rows = await api.fetchPlanDetails(id)
    planCache.value = {
      ...planCache.value,
      [id]: { loading: false, error: '', trips: groupPlanTrips(rows) },
    }
  } catch (err) {
    planCache.value = {
      ...planCache.value,
      [id]: { loading: false, error: err.message || '加载方案明细失败', trips: [] },
    }
  }
}

function selectPlan(id) {
  planId.value = id
  loadPlan(id)
}

async function load() {
  if (!requireLogin()) return
  if (!taskId.value) {
    errorMsg.value = '缺少任务编号'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await api.fetchSchedulingTask(taskId.value)
    detail.value = data
    const list = (data && data.plans) || []
    // 默认看推荐方案（与网页端的默认口径一致），没有推荐就看第一个
    const preferred = list.find((p) => p.is_recommended) || list[0]
    if (preferred) selectPlan(preferred.id)
  } catch (err) {
    errorMsg.value = err.code === 403 ? '当前账号没有查看调度任务的权限' : err.message || '加载任务详情失败'
    detail.value = null
  } finally {
    loading.value = false
  }
}

onLoad((options) => {
  taskId.value = Number(options?.id || 0)
  load()
})
</script>

<template>
  <view class="page">
    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load">重 试</button>
    </view>

    <template v-else-if="detail">
      <!-- 任务概览 -->
      <view class="card">
        <view class="task-head">
          <text class="task-code">{{ detail.task.code }}</text>
          <text class="tag" :class="taskStatusClass(detail.task.status)">
            {{ taskStatusText(detail.task.status) }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">日期 / 时段</text>
          <text class="row-value">
            {{ formatDate(detail.task.schedule_date) }} · {{ timeWindowLabel(detail.task.time_window) }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">规则版本</text>
          <text class="row-value">{{ detail.task.rule_version }}</text>
        </view>
        <view class="row">
          <text class="row-label">求解耗时 / 重排</text>
          <text class="row-value">{{ detail.task.duration_ms }} ms · {{ detail.task.replan_count }} 次</text>
        </view>
      </view>

      <!-- 方案对比 -->
      <view class="section-title">方案对比（{{ plans.length }} 套）</view>
      <view v-if="!plans.length" class="card muted">该任务没有生成方案</view>
      <view
        v-for="plan in plans"
        :key="plan.id"
        class="card plan-card"
        :class="plan.id === planId ? 'plan-active' : ''"
        @click="selectPlan(plan.id)"
      >
        <view class="plan-head">
          <text class="plan-code">方案 {{ plan.plan_code }}</text>
          <text v-if="plan.is_recommended" class="tag tag-done">推荐</text>
          <text v-else-if="plan.id === planId" class="tag tag-running">查看中</text>
        </view>
        <view class="plan-strategy muted">{{ plan.strategy }}</view>
        <view class="plan-metrics">
          <view class="metric">
            <view class="metric-num">{{ plan.trip_count }}</view>
            <view class="metric-label">趟次</view>
          </view>
          <view class="metric">
            <view class="metric-num">{{ plan.vehicle_count }}</view>
            <view class="metric-label">车辆</view>
          </view>
          <view class="metric">
            <view class="metric-num">{{ plan.avg_load_rate }}%</view>
            <view class="metric-label">装载率</view>
          </view>
          <view class="metric">
            <view class="metric-num">{{ plan.four_two_usage }}%</view>
            <view class="metric-label">四米二占比</view>
          </view>
        </view>
        <view class="row">
          <text class="row-label">总分 / 成本</text>
          <text class="row-value">{{ plan.score }} · ¥{{ plan.total_cost }}</text>
        </view>
        <view class="row">
          <text class="row-label">总货量 / 软约束</text>
          <text class="row-value">{{ plan.total_load }} 件 · {{ plan.soft_violation }}</text>
        </view>
        <view v-if="plan.uncovered_stores" class="row">
          <text class="row-label">未覆盖门店</text>
          <text class="row-value warn-text">{{ plan.uncovered_stores }}</text>
        </view>
      </view>

      <!-- 当前方案的趟次明细 -->
      <view class="section-title">
        趟次明细<text v-if="currentPlan"> · 方案 {{ currentPlan.plan_code }}</text>
      </view>

      <view v-if="current.loading" class="empty">加载趟次明细…</view>
      <view v-else-if="current.error" class="error-box">
        <view class="error-text">{{ current.error }}</view>
        <button class="btn btn-primary retry-btn" @click="loadPlan(planId, true)">重 试</button>
      </view>

      <template v-else>
        <view class="card trip-summary">
          <text>共 {{ tripSummary.total }} 趟 ·</text>
          <text class="ok-text"> 已确认 {{ tripSummary.accepted }} 趟</text>
          <text :class="tripSummary.pending ? 'warn-text' : ''"> · 待确认 {{ tripSummary.pending }} 趟</text>
        </view>

        <view v-if="!current.trips.length" class="card muted">该方案没有趟次明细</view>

        <view v-for="trip in current.trips" :key="trip.trip_key" class="card trip-card">
          <view class="trip-head">
            <text class="plate">{{ trip.plate_no || '未知车牌' }}</text>
            <text class="tag tag-planned">第 {{ trip.trip_no }} 趟</text>
          </view>
          <view class="row">
            <text class="row-label">司机</text>
            <text class="row-value">{{ trip.driver_name || '未指派' }}</text>
          </view>
          <view class="row">
            <text class="row-label">时段</text>
            <text class="row-value">{{ timeWindowLabel(trip.time_window) }}</text>
          </view>
          <view class="row">
            <text class="row-label">门店 / 货量</text>
            <text class="row-value">{{ trip.store_count }} 家 · {{ trip.total_load }} 件</text>
          </view>
          <view class="row">
            <text class="row-label">已确认接单</text>
            <text class="row-value">
              <text class="tag" :class="acceptStatusClass(trip)">{{ acceptStatusText(trip) }}</text>
            </text>
          </view>

          <!-- 门店顺序（折叠展示，只读） -->
          <view class="store-list">
            <view v-for="store in trip.stores" :key="store.id" class="store-item">
              <text class="store-seq">{{ store.sequence }}</text>
              <text class="store-name">{{ store.store_name }}</text>
              <text class="store-load muted">{{ store.load_amount }} 件</text>
              <text class="store-status muted">{{ stopStatusLabel(store.status) }}</text>
            </view>
          </view>
        </view>
      </template>

      <view class="foot-tip muted">只读视图：方案确认与下发请在网页端操作</view>
    </template>
  </view>
</template>

<style scoped>
.task-head,
.plan-head,
.trip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.task-code {
  font-size: 34rpx;
  font-weight: 700;
}

.section-title {
  font-size: 28rpx;
  font-weight: 600;
  margin: 8rpx 0 16rpx;
}

.plan-card {
  border-left: 8rpx solid #d9dee5;
}

.plan-active {
  border-left-color: #1668dc;
}

.plan-code {
  font-size: 32rpx;
  font-weight: 700;
}

.plan-strategy {
  font-size: 24rpx;
  margin-bottom: 12rpx;
}

.plan-metrics {
  display: flex;
  margin-bottom: 12rpx;
}

.metric {
  flex: 1;
  text-align: center;
}

.metric-num {
  font-size: 34rpx;
  font-weight: 700;
  color: #1668dc;
}

.metric-label {
  font-size: 22rpx;
  color: #8a9099;
}

.trip-card {
  border-left: 8rpx solid #1668dc;
}

.trip-summary {
  font-size: 26rpx;
}

.plate {
  font-size: 32rpx;
  font-weight: 700;
  letter-spacing: 1rpx;
}

.ok-text {
  color: #18a058;
}

.warn-text {
  color: #d97706;
}

.store-list {
  margin-top: 12rpx;
  border-top: 1rpx solid #f0f1f3;
  padding-top: 12rpx;
}

.store-item {
  display: flex;
  align-items: center;
  font-size: 24rpx;
  padding: 8rpx 0;
}

.store-seq {
  width: 40rpx;
  height: 40rpx;
  line-height: 40rpx;
  text-align: center;
  border-radius: 50%;
  background: #eef0f3;
  color: #4b5563;
  font-size: 22rpx;
  margin-right: 12rpx;
  flex-shrink: 0;
}

.store-name {
  flex: 1;
}

.store-load {
  margin-right: 12rpx;
}

.foot-tip {
  text-align: center;
  font-size: 22rpx;
  padding: 16rpx 0 40rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
