<script setup>
/**
 * 任务列表（管理端只读）。
 *
 * 数据来源：GET /api/scheduling/tasks（网页端同一个接口、同一套权限 scheduling:read）
 *   · 每张卡片显示任务号、日期、时段/状态、方案数；
 *   · 方案数需要任务详情才有（TaskOut 本身不带），所以列表加载时**并发**取每个任务的
 *     详情（演示库只有几条任务，一次并发拿完足够快）；
 *     某条任务详情失败不影响其它卡片显示（该卡片的方案数显示为「—」）。
 *
 * ★ 本页只读：没有任何创建/确认/下发按钮 —— 那些操作在网页端做，
 *   小程序端刻意只做「看一眼」。
 */
import { ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import { formatDate, taskStatusClass, taskStatusText, timeWindowLabel } from '@/utils/format'
import { requireLogin } from '@/utils/ui'

/** [{ task, planCount, recommended }] */
const rows = ref([])
const loading = ref(false)
const errorMsg = ref('')
const forbidden = ref(false)

async function load() {
  if (!requireLogin()) return
  loading.value = true
  errorMsg.value = ''
  forbidden.value = false
  try {
    const tasks = await api.fetchSchedulingTasks({ limit: 50 })
    const list = Array.isArray(tasks) ? tasks : []
    // 先渲染列表（方案数待补），避免等所有详情回来才看到东西
    rows.value = list.map((task) => ({ task, planCount: -1, recommended: '' }))
    loading.value = false

    // 并发补方案数：单条失败只影响它自己
    const details = await Promise.all(
      list.map((task) =>
        api
          .fetchSchedulingTask(task.id)
          .then((detail) => ({ id: task.id, detail }))
          .catch(() => ({ id: task.id, detail: null })),
      ),
    )
    const byId = {}
    details.forEach((item) => {
      byId[item.id] = item.detail
    })
    rows.value = list.map((task) => {
      const detail = byId[task.id]
      const plans = (detail && detail.plans) || []
      const best = plans.find((p) => p.is_recommended) || plans[0]
      return {
        task,
        planCount: detail ? plans.length : -2, // -2 表示详情没取到
        recommended: best ? best.plan_code : '',
      }
    })
  } catch (err) {
    if (err.code === 403) {
      forbidden.value = true
      errorMsg.value = '当前账号没有查看调度任务的权限（需要 scheduling:read）'
    } else {
      errorMsg.value = err.message || '加载任务列表失败'
    }
    rows.value = []
  } finally {
    loading.value = false
  }
}

function openTask(task) {
  uni.navigateTo({ url: `/pages/board/task-detail?id=${task.id}` })
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
        <text class="title">调度任务</text>
        <text class="desc"> 共 {{ rows.length }} 条（只读）</text>
      </view>
      <view class="mini-btn" @click="load">刷新</view>
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button v-if="!forbidden" class="btn btn-primary retry-btn" @click="load">重 试</button>
      <view v-else class="muted forbidden-tip">司机账号没有任务列表，请用「趟次」tab。</view>
    </view>

    <view v-else-if="!rows.length" class="empty">还没有调度任务</view>

    <view v-else>
      <view v-for="row in rows" :key="row.task.id" class="card task-card" @click="openTask(row.task)">
        <view class="task-head">
          <text class="task-code">{{ row.task.code }}</text>
          <text class="tag" :class="taskStatusClass(row.task.status)">
            {{ taskStatusText(row.task.status) }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">日期 / 时段</text>
          <text class="row-value">
            {{ formatDate(row.task.schedule_date) }} · {{ timeWindowLabel(row.task.time_window) }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">方案数</text>
          <text class="row-value">
            <template v-if="row.planCount > 0">
              {{ row.planCount }} 套<text v-if="row.recommended"> · 推荐 {{ row.recommended }}</text>
            </template>
            <template v-else-if="row.planCount === 0">未生成方案</template>
            <template v-else>—</template>
          </text>
        </view>
        <view class="row">
          <text class="row-label">创建人 / 版本</text>
          <text class="row-value">{{ row.task.created_by || '—' }} · {{ row.task.rule_version }}</text>
        </view>
        <view class="task-foot muted">
          点击查看方案对比与趟次确认情况 ›<text v-if="row.task.replan_count"> · 已重排 {{ row.task.replan_count }} 次</text>
        </view>
      </view>
    </view>

    <BottomNav />
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

.task-card {
  border-left: 8rpx solid #1668dc;
}

.task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.task-code {
  font-size: 32rpx;
  font-weight: 700;
  letter-spacing: 1rpx;
}

.task-foot {
  margin-top: 16rpx;
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
