<script setup>
/**
 * 我的作业任务（现场作业主线首页，底部导航「任务」）。
 *
 * 数据来源：GET /work-orders/subtasks/mine（api.fetchMySubtasks）
 *
 * ★ 一行 = 一个站点的一次巡检/消缺动作（子任务），**不是整张工单**。
 *   一张工单可能覆盖好几个站点，会被拆成好几条作业任务。
 *   现场人员关心的是「我下一趟去哪、几点去」，所以列表按作业任务粒度展示。
 *
 * ★ 排序为什么在页面里做（后端返回的是按计划日期升序）：
 *   现场最关心的是「今天要跑的」和「已经拖过计划日期的」两类，
 *   后端没有这个口径，所以前端把这两类提到最前面 —— 让当天一进页面就能看到。
 *   只改展示顺序、不改筛选结果，分页追加时不会出现「翻页后前面的条目跳位」，
 *   因为排序键（今天 / 过期 / 其它 + 计划日期 + 序号）在整份数据上是稳定的。
 *
 * ★ onShow 重拉：从详情页「开始巡检」返回、或从巡检录入页提交完成后返回，
 *   状态必须立刻变成「巡检中 / 已完成」，否则现场会以为刚才那一下没生效。
 */
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import {
  formatDate,
  isPastDate,
  isToday,
  orderTypeClass,
  taskStatusClass,
} from '@/utils/format'
import { errorText, requireLogin } from '@/utils/ui'

/** 状态筛选项。空字符串 = 全部（不传 status 参数） */
const STATUS_CHIPS = [
  { label: '全部', value: '' },
  { label: '待完成', value: '待完成' },
  { label: '巡检中', value: '巡检中' },
  { label: '已完成', value: '已完成' },
]

const PAGE_SIZE = 20

const status = ref('')
/** 输入框里的关键词（未提交），点「查询」或回车才同步给 keyword */
const keywordInput = ref('')
/** 已提交的关键词（真正参与请求） */
const keyword = ref('')
const items = ref([])
/** 分页信息（meta.has_next 决定「加载更多」是否出现） */
const meta = ref({ page: 1, total: 0, has_next: false })
const loading = ref(false)
/** 是否正在追加下一页：与 loading 分开，避免「加载更多」把整页替换成加载中 */
const loadingMore = ref(false)
const errorMsg = ref('')

/* ------------------------------------------------------------------ *
 * 派生数据
 * ------------------------------------------------------------------ */

/**
 * 展示顺序。
 * ★ 排序键里带上格式化后的计划日期，是为了让「2026-10-12」这种字符串按字典序
 *   就等于按时间序（后端给的是 YYYY-MM-DD，正好可比），不依赖 new Date() 解析。
 */
const visibleItems = computed(() => {
  const rank = (item) => {
    if (isToday(item.plan_date)) return 0
    if (isPastDate(item.plan_date)) return 1
    return 2
  }
  return [...items.value].sort((a, b) => {
    const diff = rank(a) - rank(b)
    if (diff !== 0) return diff
    const dateDiff = formatDate(a.plan_date).localeCompare(formatDate(b.plan_date))
    if (dateDiff !== 0) return dateDiff
    return (Number(a.sequence) || 0) - (Number(b.sequence) || 0)
  })
})

/** 已过计划日期且没做完的条数（顶部橙色提醒条用） */
const overdueCount = computed(
  () =>
    items.value.filter((item) => item.status !== '已完成' && isPastDate(item.plan_date)).length,
)

/** 今天要跑的条数 */
const todayCount = computed(() => items.value.filter((item) => isToday(item.plan_date)).length)

/** 已经取到数据时的总数（分页 meta 给了就用它，否则用本地长度） */
const totalText = computed(() => meta.value.total || items.value.length)

/* ------------------------------------------------------------------ *
 * 数据加载
 * ------------------------------------------------------------------ */

/**
 * 拉取列表。
 * @param {object} [options]
 * @param {boolean} [options.append] true = 追加下一页（「加载更多」），false = 从头替换
 */
async function load({ append = false } = {}) {
  if (!requireLogin()) return
  // ★ 重复点击「加载更多」会在弱网下发出两个同页码请求，追加出重复卡片，这里直接挡掉
  if (append ? loadingMore.value : loading.value) return

  const nextPage = append ? (meta.value.page || 1) + 1 : 1
  if (append) {
    loadingMore.value = true
  } else {
    loading.value = true
    errorMsg.value = ''
  }

  try {
    const data = await api.fetchMySubtasks({
      status: status.value || undefined,
      keyword: keyword.value || undefined,
      page: nextPage,
      pageSize: PAGE_SIZE,
    })
    const list = (data && data.items) || []
    items.value = append ? items.value.concat(list) : list
    meta.value = (data && data.meta) || { page: nextPage, total: list.length, has_next: false }
  } catch (err) {
    if (append) {
      // 追加失败：保留已有数据，只提示这一页没取到，绝不清空现场已经看到的列表
      uni.showToast({ title: errorText(err, '加载下一页失败'), icon: 'none', duration: 2500 })
    } else {
      // 离线容错：整页失败时渲染 .error-box + 重试按钮，不白屏
      errorMsg.value = errorText(err, '加载作业任务失败')
      items.value = []
      meta.value = { page: 1, total: 0, has_next: false }
    }
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

/** 切换状态筛选：页码必须重置回 1，否则会拿第 3 页去查新条件，出现空列表 */
function changeStatus(value) {
  if (status.value === value) return
  status.value = value
  load()
}

/** 提交关键词查询（点「查询」或回车） */
function search() {
  keyword.value = keywordInput.value.trim()
  load()
}

/** 重置筛选条件 */
function resetFilter() {
  status.value = ''
  keywordInput.value = ''
  keyword.value = ''
  load()
}

function openDetail(item) {
  // 进详情用 navigateTo：要保留列表页在栈里，返回时 onShow 才能重拉并看到最新状态
  uni.navigateTo({ url: `/pages/tasks/detail?id=${item.id}` })
}

onShow(() => {
  load()
})

onPullDownRefresh(async () => {
  await load()
  // ★ 必须调用：否则下拉的转圈会永远停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!--
      「作业任务」到底指什么，第一次用的人（包括开发同事）都问过：
      它不是整张工单，而是「去某一个站点做一次巡检」这一件事。
      一张工单派了好几个站点，就会在下面拆成好几条任务。
    -->
    <view class="hint-bar">
      一条作业任务 = 去一个站点做一次巡检（或一次消缺）。
      一张工单如果覆盖多个站点，会拆成好几条作业任务，各做各的、各自结单。
    </view>

    <!-- 状态筛选 -->
    <view class="chip-row">
      <view
        v-for="chip in STATUS_CHIPS"
        :key="chip.label"
        class="chip"
        :class="status === chip.value ? 'chip-active' : ''"
        @click="changeStatus(chip.value)"
      >
        {{ chip.label }}
      </view>
    </view>

    <!-- 关键词搜索（工单编号 / 名称 / 站点） -->
    <view class="search-row">
      <input
        v-model="keywordInput"
        class="form-input search-input"
        type="text"
        placeholder="工单编号 / 名称 / 站点"
        confirm-type="search"
        @confirm="search"
      />
      <view class="search-btn" @click="search">查询</view>
      <view class="search-btn search-btn-plain" @click="resetFilter">重置</view>
    </view>

    <!-- 过期提醒：现场最怕漏掉已经拖过计划日期的任务 -->
    <view v-if="overdueCount > 0" class="warn-bar">
      有 {{ overdueCount }} 条已过计划日期{{ status === '已完成' ? '' : '且尚未完成' }}，请优先处理。
    </view>

    <!-- 今日小结（有数据时才显示，避免空列表下多一块噪音） -->
    <view v-if="!loading && !errorMsg && items.length" class="toolbar">
      <text class="muted">
        共 {{ totalText }} 条 · 今天 {{ todayCount }} 条 · 已加载 {{ items.length }} 条
      </text>
    </view>

    <!-- 加载中 -->
    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试 -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load()">重 试</button>
    </view>

    <!-- 空态 -->
    <view v-else-if="!items.length" class="empty">
      {{
        status || keyword
          ? '没有符合条件的作业任务，可切换筛选或清空关键词'
          : '暂无作业任务。等管理员下派工单后，这里会出现要去的站点'
      }}
    </view>

    <!-- 作业任务卡片 -->
    <view v-else>
      <view
        v-for="item in visibleItems"
        :key="item.id"
        class="card task-card"
        @click="openDetail(item)"
      >
        <view class="task-head">
          <text class="order-no">{{ item.order_no || '—' }}</text>
          <!-- 「今天」「已过期」比状态更紧急，放在状态标签前面 -->
          <text v-if="isToday(item.plan_date)" class="tag tag-running day-tag">今天</text>
          <text
            v-else-if="isPastDate(item.plan_date) && item.status !== '已完成'"
            class="tag tag-danger day-tag"
          >
            已过期
          </text>
          <text class="tag" :class="taskStatusClass(item.status)">{{ item.status }}</text>
        </view>

        <view class="task-name">{{ item.order_name || '未命名工单' }}</view>

        <view class="task-tags">
          <text class="tag tag-inline" :class="orderTypeClass(item.order_type)">
            {{ item.order_type || '其他' }}
          </text>
          <!-- sequence = 本张工单里的第几个站点，多个站点时方便对上计划 -->
          <text class="seq">第 {{ item.sequence }} 个子任务</text>
        </view>

        <view class="row">
          <text class="row-label">站点</text>
          <text class="row-value">{{ item.station_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">充电桩</text>
          <!-- pile_asset_code 可能为 null（整站巡检不指定具体桩），不能显示成空白 -->
          <text class="row-value">
            {{ item.pile_asset_code || '未指定具体桩（整站巡检）' }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">计划</text>
          <text class="row-value">
            <text class="strong">{{ formatDate(item.plan_date) }}</text>
            <text> · {{ item.plan_time_window || '时段未定' }}</text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">执行人</text>
          <text class="row-value">{{ item.assignee_name || '未指派' }}</text>
        </view>

        <!-- 完成后的巡检结论（正常 x 项 / 异常 y 项），一眼看出这站有没有问题 -->
        <view v-if="item.item_summary" class="task-summary">
          巡检结论：{{ item.item_summary }}
        </view>
      </view>

      <!-- 分页：追加而不是覆盖，现场翻页时已经看过的卡片不会跳走 -->
      <view v-if="meta.has_next" class="more-btn" @click="load({ append: true })">
        {{ loadingMore ? '加载中…' : '加载更多' }}
      </view>
      <view v-else-if="items.length >= PAGE_SIZE" class="empty">已经到底了</view>
    </view>

    <BottomNav />
  </view>
</template>

<style scoped>
/* 搜索行：输入框 + 查询 + 重置 */
.search-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.search-input {
  flex: 1;
  background: #ffffff;
}

.search-btn {
  flex-shrink: 0;
  padding: 18rpx 28rpx;
  border-radius: 12rpx;
  background: #1677ff;
  color: #ffffff;
  font-size: 26rpx;
}

.search-btn-plain {
  background: #ffffff;
  color: #4b5563;
  border: 1rpx solid #e6e8eb;
}

/* 卡片标题行：工单编号 + 今天/已过期 + 状态标签 */
.task-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12rpx;
  margin-bottom: 10rpx;
}

.order-no {
  font-size: 28rpx;
  font-weight: 700;
  letter-spacing: 1rpx;
  margin-right: auto;
}

/* 全局 .tag 自带 margin-left: 12rpx（本来是为跟在标题后面设计的），
   这里一行有多个标签且已经用 gap 控距，所以清零避免右边多出空隙 */
.task-head .tag,
.task-tags .tag {
  margin-left: 0;
}

.day-tag {
  font-weight: 600;
}

.task-name {
  font-size: 30rpx;
  font-weight: 600;
  margin-bottom: 12rpx;
}

.task-tags {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 8rpx;
}

.tag-inline {
  margin-left: 0;
}

.seq {
  color: #8a9099;
  font-size: 22rpx;
}

/* 巡检结论条：已完成的任务用它代替「点进去才知道有没有问题」 */
.task-summary {
  margin-top: 14rpx;
  padding: 12rpx 18rpx;
  background: #f7f8fa;
  border-radius: 10rpx;
  color: #14724a;
  font-size: 24rpx;
}

.more-btn {
  text-align: center;
  color: #1677ff;
  background: #ffffff;
  border-radius: 12rpx;
  padding: 22rpx 0;
  font-size: 27rpx;
  margin-bottom: 20rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
