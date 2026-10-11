<script setup>
/**
 * 作业任务详情（现场作业主线第 2 页）。
 *
 * 路由参数：id = 作业任务（子任务）ID。
 *
 * ★ 为什么详情页要「先拉列表再 find」：
 *   后端**没有「按 id 查子任务」的接口** —— /work-orders/subtasks/mine 是唯一的
 *   作业任务接口，它只能按分页查列表（work_orders.py 的 my_subtasks）。
 *   所以这里的定位顺序是：
 *     ① 先在自己的任务里找（pageSize 取接口上限 200，个人数据权限账号拿到的是全部自己的活）；
 *     ② 自己的列表里没有，再用 scopeAll: true 找一遍 —— 管理员/站点管理员从消息里
 *        点进来时，任务不在他名下，只在「全部」口径里；
 *   ③ 两处都没有，就明确告诉用户「任务不存在或不属于当前账号」，给返回按钮，
 *      而不是留一个永远转圈的空白页。
 *
 * ★ 定位到子任务后，工单级信息（时效、起止日期、次数、进度、站点地址）与巡检记录
 *   都从 work_order_id 走各自的接口取：一处失败不影响另一处，所以拆成两次独立的 try。
 */
import { computed, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import {
  formatDate,
  formatDateTime,
  isPastDate,
  orderStatusClass,
  orderTypeClass,
  safeDecode,
  taskStatusClass,
  timeStatusClass,
} from '@/utils/format'
import { accountProfile, errorText, requireLogin } from '@/utils/ui'

/** 接口 page_size 的上限是 200（work_orders.py 的 my_subtasks 有 le=200 校验） */
const LOOKUP_PAGE_SIZE = 200

const subtaskId = ref('')
const task = ref(null)
/** 工单详情整体响应：{ work_order, subtasks, subtask_stats, stations, permissions } */
const orderInfo = ref(null)
/** 巡检记录响应：{ work_order, subtasks } */
const inspection = ref(null)

const loading = ref(false)
const errorMsg = ref('')
/** 巡检记录单独的错误：工单信息已经加载出来了，不该因为巡检记录失败而整页报错 */
const inspectError = ref('')
/** 正在把状态推到「巡检中」：防止连点发出两个请求、跳两次页面 */
const starting = ref(false)

const workOrder = computed(() => orderInfo.value?.work_order || null)
const stats = computed(() => orderInfo.value?.subtask_stats || null)
const subtasks = computed(() => orderInfo.value?.subtasks || [])

/* ------------------------------------------------------------------ *
 * 「同一工单的其它作业任务」的展示窗口
 * ------------------------------------------------------------------ *
 * ★ 为什么不能把 subtasks 全列出来（用户实测反馈「怎么这么多」）：
 *   AI 智能工单调度生成的大工单会一次拆出上百个子任务 ——
 *   实测 WO202610110944021538（8 个站点 × 巡检周期 × 频率）**共 128 条**。
 *   128 行铺在详情页里，会把「我这条排第几、还有几条没干」这个真正有用的信息
 *   淹掉，页面也会明显卡顿。
 *   所以：默认只显示当前这条附近的几条 + 一行分布小结，要看全部再展开。
 * ------------------------------------------------------------------ */
const SUBTASK_PREVIEW = 5
const showAllSubtasks = ref(false)

/** 当前账号名下子任务 id 的集合（findTask 里填充） */
const mySubtaskIdMap = ref({})

/** 管理端账号（站点/项目/平台数据权限）：整张工单的任务都在他的可见范围内 */
const isManager = computed(() => !accountProfile().isField)

/**
 * 「同一工单的其它作业任务」只列**我名下**的那些。
 *
 * ★ 为什么必须过滤（用户实测踩到的坑，报的是「从巡检页面退出来任务就不见了」）：
 *   `GET /work-orders/{id}` 返回的是**整张工单的全部子任务，不按执行人过滤**。
 *   AI 生成的大工单实测 128 条，分给 3 个运维，某个人名下只有其中 22 条。
 *   原来把 128 条全列出来并做成可点，点进别人的任务时详情页按 id
 *   在自己的列表里定位不到 → 显示「任务不存在或不属于当前账号」，
 *   而跳转用的又是 redirectTo（会关掉原来那页）→ 返回时直接掉回任务列表，
 *   用户的感觉就是「我刚才那条任务不见了」。
 *   过滤之后：列表里的每一条都是自己的，点进去一定找得到，返回也不会丢上下文。
 */
const ownSubtasks = computed(() => {
  const list = subtasks.value
  if (isManager.value) return list
  return list.filter((s) => !!mySubtaskIdMap.value[s.id])
})

/** 该工单里「我的」子任务分布（现场只关心还剩几条要跑） */
const subtaskSummary = computed(() => {
  const list = ownSubtasks.value
  const done = list.filter((s) => s.status === '已完成').length
  const doing = list.filter((s) => s.status === '巡检中').length
  return { total: list.length, done, doing, todo: list.length - done - doing }
})

/** 该工单全部子任务数（说明「你名下只占其中几条」时用） */
const orderSubtaskTotal = computed(() => subtasks.value.length)

/** 是否值得给「展开全部」按钮（少量子任务时直接全列，不折腾） */
const canExpandSubtasks = computed(() => ownSubtasks.value.length > SUBTASK_PREVIEW + 2)

/** 实际渲染的那几条：展开时全给，否则以当前任务为中心取一小段 */
const visibleSubtasks = computed(() => {
  const list = ownSubtasks.value
  if (showAllSubtasks.value || !canExpandSubtasks.value) return list
  const index = list.findIndex((s) => s.id === subtaskId.value)
  if (index < 0) return list.slice(0, SUBTASK_PREVIEW)
  const start = Math.max(0, index - 2)
  return list.slice(start, start + SUBTASK_PREVIEW)
})

/**
 * 跳到同工单的另一条作业任务。
 * ★ 用 redirectTo：切任务不该把页面栈越压越深（现场会连着翻好几条）。
 *   代价是「返回」会回到任务列表而不是上一条任务 —— 这是刻意的，
 *   比栈深不可控、退半天退不出去好。
 * ★ 只允许跳自己名下的（canJump），别人的任务点了会明确提示，
 *   而不是跳过去显示「任务不存在」。
 */
function openSubtask(sub) {
  if (!sub || sub.id === subtaskId.value) return
  if (!canJump(sub)) {
    uni.showToast({
      title: `这是${sub.assignee_name || '其他人'}的作业任务，不在你名下`,
      icon: 'none',
      duration: 2500,
    })
    return
  }
  uni.redirectTo({ url: `/pages/tasks/detail?id=${encodeURIComponent(sub.id)}` })
}
const canInspect = computed(() => accountProfile().canInspect)

/**
 * 工单进度（已完成的子任务 / 总数）。
 * ★ 优先用 subtask_stats 现算的结果：work_order 上的 subtask_done 是列表里的快照字段，
 *   子任务刚被别的账号结掉时可能还没回填，stats 是详情接口当场按子任务状态数的，更可信。
 */
const progressDone = computed(() => stats.value?.completed ?? workOrder.value?.subtask_done ?? 0)
const progressTotal = computed(() => stats.value?.total ?? workOrder.value?.subtask_total ?? 0)
const progressPercent = computed(() => {
  const total = Number(progressTotal.value) || 0
  const done = Number(progressDone.value) || 0
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)))
})

/**
 * 本子任务的巡检记录。
 * ★ 后端按工单返回记录，一个工单下可能有多个站点的记录，所以要按 subtask_id 过滤 ——
 *   不过滤会把别的站点的照片和异常项显示到当前任务上。
 *   过滤后为空时（后端没记录 subtask_id 关联）退回展示第一条，保证「已完成」的任务有东西可看。
 */
const myRecord = computed(() => {
  const details = (inspection.value && inspection.value.subtasks) || []
  const mine = details.filter((d) => d.subtask_id === subtaskId.value)
  const first = mine.find((d) => (d.records || []).length)
  if (first) return first
  if (mine.length) return mine[0]
  return details.find((d) => (d.records || []).length) || null
})

/** 巡检记录（取最近一条：同一任务可能补录过多次） */
const record = computed(() => {
  const records = (myRecord.value && myRecord.value.records) || []
  return records.length ? records[records.length - 1] : null
})

/** 异常项清单 */
const abnormalItems = computed(() =>
  (((myRecord.value && myRecord.value.items) || []).filter((i) => i.result === '异常')),
)

/**
 * 现场照片。
 * ★ 必须走 api.absoluteUrls 补全：后端存的是 /static/data/uploads/... 相对路径，
 *   小程序里 <image src> 给相对路径就是一张空白图（H5 走代理反而正常，最容易漏测）。
 * ★ 去重：整单照片与巡检项照片可能是同一张（同一 URL 存了两处），不去重会重复渲染。
 */
const photos = computed(() => {
  const list = []
  if (record.value) list.push(...api.absoluteUrls(record.value.images))
  abnormalItems.value.forEach((item) => list.push(...api.absoluteUrls(item.images)))
  return Array.from(new Set(list.filter(Boolean)))
})

/* ------------------------------------------------------------------ *
 * 数据加载
 * ------------------------------------------------------------------ */

/**
 * 在自己的任务列表里定位当前子任务，同时记下自己名下子任务的 id 集合
 * （`mySubtaskIdMap` 在上面声明，「同一工单的其它作业任务」用它过滤出只属于我的那些）。
 */
async function findTask() {
  const mine = await api.fetchMySubtasks({ pageSize: LOOKUP_PAGE_SIZE })
  const mineItems = (mine && mine.items) || []
  mySubtaskIdMap.value = mineItems.reduce((acc, item) => {
    acc[item.id] = true
    return acc
  }, {})

  const found = mineItems.find((i) => i.id === subtaskId.value)
  if (found) return found

  // 兜底：管理端账号从消息/分享进来时，任务不在他名下，只在 scope_all 口径里
  const all = await api.fetchMySubtasks({ pageSize: LOOKUP_PAGE_SIZE, scopeAll: true })
  return ((all && all.items) || []).find((i) => i.id === subtaskId.value) || null
}

/** 这一条能不能点进去（自己的、或管理端账号） */
function canJump(sub) {
  if (!sub) return false
  return isManager.value || !!mySubtaskIdMap.value[sub.id]
}

async function load() {
  if (!requireLogin()) return
  if (!subtaskId.value) {
    errorMsg.value = '缺少作业任务标识（页面链接不完整，请从任务列表进入）'
    return
  }
  loading.value = true
  errorMsg.value = ''
  inspectError.value = ''
  task.value = null
  orderInfo.value = null
  inspection.value = null

  try {
    task.value = await findTask()
    if (!task.value) {
      errorMsg.value = '任务不存在或不属于当前账号'
      return
    }
  } catch (err) {
    errorMsg.value = errorText(err, '加载作业任务失败')
    return
  } finally {
    loading.value = false
  }

  // 工单级信息：失败不影响任务本身与下方按钮的展示，只提示一句
  try {
    orderInfo.value = await api.fetchWorkOrder(task.value.work_order_id)
  } catch (err) {
    console.warn('[tasks] 工单信息加载失败', err)
    uni.showToast({ title: errorText(err, '工单信息加载失败'), icon: 'none', duration: 2500 })
  }

  // 巡检记录只在已完成时才有意义（未完成的工单后端本来也不会有记录）
  if (task.value.status === '已完成') {
    try {
      inspection.value = await api.fetchOrderInspection(task.value.work_order_id)
    } catch (err) {
      inspectError.value = errorText(err, '巡检记录加载失败')
    }
  }
}

/* ------------------------------------------------------------------ *
 * 动作
 * ------------------------------------------------------------------ */

/**
 * 开始巡检：先把作业任务推到「巡检中」，成功后才跳录入页。
 * ★ 顺序不能反：先跳页面再改状态的话，弱网下状态没改成功、用户却在录入页，
 *   提交时后端会按「待完成」的旧状态走，工单进度就永远差这一格。
 * ★ 失败一律 toast 且**不跳转**，让人留在详情页重试。
 */
async function startInspect() {
  if (!task.value || starting.value) return
  starting.value = true
  uni.showLoading({ title: '提交中…', mask: true })
  try {
    await api.updateSubtask(task.value.id, { status: '巡检中' })
    uni.hideLoading()
    // 就地更新，避免为了一个状态再拉一次列表（弱网下重拉会让人以为没反应）
    task.value.status = '巡检中'
    goInspectForm()
  } catch (err) {
    uni.hideLoading()
    uni.showToast({ title: errorText(err, '开始巡检失败'), icon: 'none', duration: 2500 })
  } finally {
    starting.value = false
  }
}

/** 巡检录入页：orderType 决定巡检项模板，orderName 用于页面标题区展示 */
function goInspectForm() {
  const query = [
    `subtaskId=${encodeURIComponent(task.value.id)}`,
    `orderType=${encodeURIComponent(task.value.order_type || '巡视')}`,
    `orderName=${encodeURIComponent(task.value.order_name || '')}`,
  ].join('&')
  uni.navigateTo({ url: `/pages/inspect/form?${query}` })
}

function previewPhotos(index) {
  if (!photos.value.length) return
  uni.previewImage({ urls: photos.value, current: index })
}

/** 返回上一页；上一页不存在时（直接从消息进来）退回任务列表 */
function goBack() {
  const pages = getCurrentPages()
  if (pages.length > 1) {
    uni.navigateBack()
    return
  }
  uni.redirectTo({ url: '/pages/tasks/index' })
}

/** 首次进入由 onLoad 触发加载；onShow 只在「从别的页面返回」时补一次 */
const firstShowDone = ref(false)

onLoad((options) => {
  subtaskId.value = safeDecode(options && options.id)
  load()
})

/**
 * ★ 必须补 onShow：从巡检录入页返回时，这一页的 onLoad 不会再跑，
 *   而任务状态可能已经从「待完成 / 巡检中」变成了「已完成」——
 *   不重拉的话页面还显示旧状态和「继续巡检」按钮，点进去只会让人以为没提交成功。
 *   首次进入紧随 onLoad，跳过以免同一个请求发两遍。
 */
onShow(() => {
  if (!firstShowDone.value) {
    firstShowDone.value = true
    return
  }
  if (subtaskId.value) load()
})
</script>

<template>
  <view class="page page-with-footer">
    <!-- 加载中 -->
    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试（找不到任务时也给返回入口，不让人卡在死页） -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load()">重 试</button>
      <button class="btn btn-plain retry-btn back-btn" @click="goBack">返回任务列表</button>
    </view>

    <template v-else-if="task">
      <!--
        状态说明条：颜色由 taskStatusClass 统一给（与列表卡片同一口径），
        页面里不另写 if/else 判色，避免同一个「待完成」在两处是两种颜色。
      -->
      <view class="banner" :class="taskStatusClass(task.status)">
        <view class="banner-title">{{ task.status }}</view>
        <view class="banner-hint">
          {{
            task.status === '待完成'
              ? '还没开始。到场后先点「开始巡检」，任务会进入巡检中'
              : task.status === '巡检中'
                ? '已开工但没结单，接着录完并提交即可'
                : task.status === '已完成'
                  ? '本作业任务已结单，可回看巡检记录与现场照片'
                  : '该作业任务已取消，无需现场处理'
          }}
        </view>
      </view>

      <!-- 计划日期已过还没做完：现场最需要立刻看到的一条提醒 -->
      <view v-if="task.status !== '已完成' && isPastDate(task.plan_date)" class="warn-bar">
        计划日期 {{ formatDate(task.plan_date) }} 已过，请尽快完成并提交。
      </view>

      <!-- 任务卡片 -->
      <view class="card">
        <view class="task-head">
          <text class="order-no">{{ task.order_no || '—' }}</text>
          <text class="tag" :class="taskStatusClass(task.status)">{{ task.status }}</text>
        </view>
        <view class="task-name">{{ task.order_name || '未命名工单' }}</view>

        <view class="task-tags">
          <text class="tag" :class="orderTypeClass(task.order_type)">
            {{ task.order_type || '其他' }}
          </text>
          <text class="tag" :class="timeStatusClass(workOrder && workOrder.time_status)">
            {{ (workOrder && workOrder.time_status) || '正常' }}
          </text>
        </view>

        <view class="row">
          <text class="row-label">站点</text>
          <text class="row-value">{{ task.station_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">站点地址</text>
          <text class="row-value">{{ (workOrder && workOrder.station_address) || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">充电桩</text>
          <text class="row-value">
            {{ task.pile_asset_code || '未指定具体桩（整站巡检）' }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">计划日期</text>
          <text class="row-value">{{ formatDate(task.plan_date) }}</text>
        </view>
        <view class="row">
          <text class="row-label">计划时段</text>
          <text class="row-value">{{ task.plan_time_window || '时段未定' }}</text>
        </view>
        <view class="row">
          <text class="row-label">执行人</text>
          <text class="row-value">{{ task.assignee_name || '未指派' }}</text>
        </view>
        <view class="row">
          <text class="row-label">站点序号</text>
          <text class="row-value">本工单第 {{ task.sequence }} 个子任务</text>
        </view>
        <view class="row">
          <text class="row-label">完成时间</text>
          <text class="row-value">
            {{ task.status === '已完成' ? formatDateTime(task.completed_at) : '—' }}
          </text>
        </view>
        <view v-if="task.item_summary" class="task-summary">
          巡检结论：{{ task.item_summary }}
        </view>
      </view>

      <!-- 工单信息 -->
      <view class="card">
        <view class="section-title">所属工单</view>
        <template v-if="workOrder">
          <view class="row">
            <text class="row-label">工单编号</text>
            <text class="row-value">{{ workOrder.order_no }}</text>
          </view>
          <view class="row">
            <text class="row-label">工单名称</text>
            <text class="row-value">{{ workOrder.order_name }}</text>
          </view>
          <view class="row">
            <text class="row-label">工单类型</text>
            <text class="row-value">
              <text class="tag" :class="orderTypeClass(workOrder.order_type)">
                {{ workOrder.order_type }}
              </text>
            </text>
          </view>
          <view class="row">
            <text class="row-label">工单状态</text>
            <text class="row-value">
              <text class="tag" :class="orderStatusClass(workOrder.status)">
                {{ workOrder.status }}
              </text>
            </text>
          </view>
          <view class="row">
            <text class="row-label">工单时效</text>
            <text class="row-value">
              <text class="tag" :class="timeStatusClass(workOrder.time_status)">
                {{ workOrder.time_status }}
              </text>
            </text>
          </view>
          <view class="row">
            <text class="row-label">起止日期</text>
            <text class="row-value">
              {{ formatDate(workOrder.inspect_start_date) }} ~
              {{ formatDate(workOrder.inspect_end_date) }}
            </text>
          </view>
          <view class="row">
            <text class="row-label">巡检频率</text>
            <text class="row-value">
              {{ workOrder.inspect_frequency || '—' }} · 共 {{ workOrder.inspect_count || 0 }} 次
            </text>
          </view>
          <view class="row">
            <text class="row-label">负责人员</text>
            <text class="row-value">{{ workOrder.inspector_name || '—' }}</text>
          </view>
          <view class="row">
            <text class="row-label">备注</text>
            <text class="row-value">{{ workOrder.remark || '无' }}</text>
          </view>

          <view class="progress-line">
            <view class="progress-bar">
              <view class="progress-inner" :style="{ width: progressPercent + '%' }" />
            </view>
            <text class="progress-text">
              工单进度 {{ progressDone }}/{{ progressTotal }} 个作业任务已完成（{{ progressPercent }}%）
            </text>
          </view>
        </template>
        <view v-else class="empty">工单信息加载失败，可点下方「重试」再取一次</view>
      </view>

      <!-- 巡检记录（仅已完成的任务展示） -->
      <view v-if="task.status === '已完成'" class="card">
        <view class="section-title">巡检记录</view>

        <view v-if="inspectError" class="error-box">
          <view class="error-text">{{ inspectError }}</view>
          <button class="btn btn-primary retry-btn" @click="load()">重 试</button>
        </view>

        <template v-else-if="record">
          <view class="row">
            <text class="row-label">巡检结果</text>
            <text class="row-value">
              <text class="strong">正常 {{ record.normal_count }} 项</text>
              <text> / </text>
              <text :class="record.abnormal_count ? 'abnormal-text' : 'muted'">
                异常 {{ record.abnormal_count }} 项
              </text>
            </text>
          </view>
          <view class="row">
            <text class="row-label">记录状态</text>
            <!-- 后端巡检详情只回记录本身（不含巡检人），巡检人取子任务的执行人 -->
            <text class="row-value">
              {{ record.status }} · {{ task.assignee_name || '未指派' }}
            </text>
          </view>
          <view class="row">
            <text class="row-label">签到时间</text>
            <text class="row-value">{{ formatDateTime(record.checkin_time) }}</text>
          </view>
          <view class="row">
            <text class="row-label">离店时间</text>
            <text class="row-value">{{ formatDateTime(record.checkout_time) }}</text>
          </view>
          <view class="row">
            <text class="row-label">签到位置</text>
            <text class="row-value">{{ record.checkin_location || '未记录定位' }}</text>
          </view>

          <!-- 异常项清单：现场照片之外最需要回看的内容 -->
          <view v-if="abnormalItems.length" class="abnormal-block">
            <view class="sub-title">异常项（{{ abnormalItems.length }}）</view>
            <view v-for="item in abnormalItems" :key="item.id" class="abnormal-item">
              <view class="abnormal-name">
                <text class="tag tag-danger tag-inline">{{ item.item_group || '通用' }}</text>
                <text>{{ item.item_name }}</text>
              </view>
              <view v-if="item.remark" class="abnormal-remark">{{ item.remark }}</view>
            </view>
          </view>
          <view v-else class="all-normal">本次巡检未发现异常项 ✓</view>

          <!-- 现场照片：src 必须走 absoluteUrls 补全，点击放大 -->
          <view v-if="photos.length" class="photo-block">
            <view class="sub-title">现场照片（{{ photos.length }} 张）</view>
            <view class="image-grid">
              <image
                v-for="(url, index) in photos"
                :key="url"
                class="grid-img"
                :src="url"
                mode="aspectFill"
                @click="previewPhotos(index)"
              />
            </view>
          </view>

          <view v-if="record.remark" class="record-remark">巡检备注：{{ record.remark }}</view>
        </template>

        <view v-else class="empty">暂无巡检记录</view>
      </view>

      <!--
        其它子任务进度：知道同工单还有几个站点没跑，好安排回程。
        ★ 只列**我名下**的那些（ownSubtasks）：整张工单可能有上百条、分给好几个人，
          把别人的也列出来并做成可点，点进去会「任务不存在」（详见 ownSubtasks 的注释）。
      -->
      <view v-if="ownSubtasks.length > 1" class="card">
        <view class="section-title">
          <text>同一工单的其它作业任务</text>
          <text class="muted group-count">{{ subtaskSummary.total }} 条</text>
        </view>

        <!-- 分布小结：现场只关心「还剩几条要跑」，不需要把 100 多行都摊开 -->
        <view class="sub-summary">
          待完成 {{ subtaskSummary.todo }} · 巡检中 {{ subtaskSummary.doing }} ·
          已完成 {{ subtaskSummary.done }}
        </view>

        <!-- 说清楚这里不是整张工单：大工单好几百条，只显示你名下的 -->
        <view v-if="!isManager && orderSubtaskTotal > subtaskSummary.total" class="sub-scope">
          只显示你名下的 {{ subtaskSummary.total }} 条（本工单共 {{ orderSubtaskTotal }} 条，
          其余由其他同事执行）
        </view>

        <view
          v-for="sub in visibleSubtasks"
          :key="sub.id"
          class="sub-row"
          :class="{ 'sub-row-static': !canJump(sub) }"
          @click="openSubtask(sub)"
        >
          <text class="sub-seq">#{{ sub.sequence }}</text>
          <text class="sub-name">
            {{ sub.station_name || '—' }}
            <text v-if="sub.id === task.id" class="sub-self">（当前）</text>
            <!-- 执行人写出来：同一站点会有多条（不同日期/不同人），不写根本分不清 -->
            <text v-if="sub.assignee_name" class="sub-assignee">{{ sub.assignee_name }}</text>
          </text>
          <text class="tag" :class="taskStatusClass(sub.status)">{{ sub.status }}</text>
          <text v-if="canJump(sub)" class="sub-arrow">›</text>
        </view>

        <!-- 只显示了一段时说明白，避免以为「这个工单就 5 条」 -->
        <view v-if="canExpandSubtasks && !showAllSubtasks" class="sub-note">
          为避免长列表刷屏，这里只显示当前任务附近的 {{ visibleSubtasks.length }} 条
        </view>

        <view
          v-if="canExpandSubtasks"
          class="sub-more"
          @click="showAllSubtasks = !showAllSubtasks"
        >
          {{ showAllSubtasks ? '收起' : `展开全部 ${subtaskSummary.total} 条` }}
        </view>
      </view>
    </template>

    <!-- 底部固定操作条：按状态给动作，不给无关按钮 -->
    <view v-if="task" class="footer-bar">
      <button class="btn btn-plain" @click="goBack">返回</button>

      <!-- 待完成 + 有巡检权限 → 先推状态再进录入页 -->
      <button
        v-if="task.status === '待完成' && canInspect"
        class="btn btn-primary"
        :disabled="starting"
        @click="startInspect"
      >
        {{ starting ? '处理中…' : '开始巡检' }}
      </button>

      <!-- 巡检中 → 直接进录入页，不再改状态（后端已经是这个状态） -->
      <button
        v-else-if="task.status === '巡检中'"
        class="btn btn-primary"
        @click="goInspectForm"
      >
        继续巡检
      </button>

      <!-- 已完成 → 不给巡检按钮，只说明可以回看记录 -->
      <view v-else-if="task.status === '已完成'" class="done-tip">已完成，可回看巡检记录</view>

      <!-- 待完成但当前账号没有巡检录入权限：说清原因，不给一个点不动的按钮 -->
      <view v-else-if="task.status === '待完成'" class="done-tip muted-tip">
        当前账号无巡检录入权限
      </view>

      <view v-else class="done-tip muted-tip">该任务不可录入</view>
    </view>

    <!--
      ★ 本页刻意**不挂 <BottomNav />**（二级页一律不挂，只有 tab 页挂）。
        原因不是审美：底部导航是 position:fixed; bottom:0; z-index:100，
        和这里的 .footer-bar 完全重叠 —— 实测两者同时存在时，
        导航会把「开始巡检」整块盖住，按钮看着在、点下去毫无反应
        （Playwright 报的正是「bottom-nav subtree intercepts pointer events」）。
        全项目的约定：tab 页挂导航、二级页（详情/表单）只有操作条。
    -->
  </view>
</template>

<style scoped>
/* 状态说明条：底色与标签同一套（tag-pending/tag-running/tag-done/tag-planned） */
.banner {
  border-radius: 16rpx;
  padding: 22rpx 24rpx;
  margin-bottom: 20rpx;
}

.banner-title {
  font-size: 30rpx;
  font-weight: 600;
}

.banner-hint {
  color: #5b6270;
  font-size: 23rpx;
  margin-top: 8rpx;
  line-height: 1.6;
}

.task-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12rpx;
  margin-bottom: 10rpx;
}

/* 全局 .tag 自带 margin-left: 12rpx，这里用 gap 控距，清零避免右侧多出空隙 */
.task-head .tag,
.task-tags .tag,
.sub-row .tag {
  margin-left: 0;
}

.order-no {
  font-size: 28rpx;
  font-weight: 700;
  letter-spacing: 1rpx;
  margin-right: auto;
}

.task-name {
  font-size: 32rpx;
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

.task-summary {
  margin-top: 14rpx;
  padding: 12rpx 18rpx;
  background: #f7f8fa;
  border-radius: 10rpx;
  color: #14724a;
  font-size: 24rpx;
}

.progress-line {
  margin-top: 16rpx;
}

.progress-text {
  display: block;
  color: #8a9099;
  font-size: 22rpx;
  margin-top: 8rpx;
}

.sub-title {
  font-size: 26rpx;
  font-weight: 600;
  margin: 20rpx 0 12rpx;
}

.abnormal-text {
  color: #d03050;
  font-weight: 600;
}

.abnormal-block {
  margin-top: 8rpx;
}

.abnormal-item {
  background: #fdecec;
  border-radius: 10rpx;
  padding: 14rpx 18rpx;
  margin-bottom: 12rpx;
}

.abnormal-name {
  display: flex;
  align-items: center;
  gap: 12rpx;
  font-size: 26rpx;
  color: #a52240;
}

.abnormal-remark {
  color: #8a5a63;
  font-size: 23rpx;
  margin-top: 8rpx;
  line-height: 1.6;
}

.all-normal {
  color: #18a058;
  font-size: 26rpx;
  padding: 16rpx 0;
}

.photo-block {
  margin-top: 8rpx;
}

.record-remark {
  margin-top: 20rpx;
  padding: 14rpx 18rpx;
  background: #f7f8fa;
  border-radius: 10rpx;
  color: #4b5563;
  font-size: 24rpx;
  line-height: 1.7;
}

/* 同工单其它子任务 */
.sub-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 14rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
  font-size: 26rpx;
}

/* 行现在可点（跳到那条任务），给一点按压反馈，让人知道能点 */
.sub-row:active {
  background: #f7f8fa;
}

/* 不可点的行（别人的任务）：不加按压反馈，也不显示箭头 */
.sub-row-static:active {
  background: transparent;
}

.sub-row:last-child {
  border-bottom: none;
}

/* 执行人：一行里靠右的小灰字 */
.sub-assignee {
  color: #8a9099;
  font-size: 21rpx;
  margin-left: 10rpx;
}

/* 可跳转的箭头提示 */
.sub-arrow {
  color: #c9ced6;
  font-size: 30rpx;
  flex-shrink: 0;
}

/* 说明「只显示你名下的」（大工单会分给多个人） */
.sub-scope {
  font-size: 22rpx;
  color: #8a9099;
  line-height: 1.6;
  padding: 4rpx 0 8rpx;
}

/* 分布小结：一行说清还剩几条要跑 */
.sub-summary {
  font-size: 24rpx;
  color: #4b5563;
  background: #f7f8fa;
  border-radius: 12rpx;
  padding: 14rpx 20rpx;
  margin-bottom: 8rpx;
}

/* 窗口化展示的说明（避免误以为整个工单只有这几条） */
.sub-note {
  font-size: 22rpx;
  color: #8a9099;
  padding: 12rpx 0 4rpx;
  line-height: 1.6;
}

/* 展开 / 收起：整行可点，比一个小按钮好按 */
.sub-more {
  text-align: center;
  color: #1677ff;
  font-size: 25rpx;
  padding: 16rpx 0 4rpx;
  border-top: 1rpx solid #f0f1f3;
  margin-top: 8rpx;
}

.sub-seq {
  color: #8a9099;
  font-size: 22rpx;
  flex-shrink: 0;
}

.sub-name {
  flex: 1;
}

.sub-self {
  color: #1677ff;
  font-size: 22rpx;
}

/* 底部操作条里的纯文字说明（不是按钮，别做成能点的样子） */
.done-tip {
  flex: 1;
  text-align: center;
  color: #18a058;
  font-size: 26rpx;
  line-height: 2.4;
}

.muted-tip {
  color: #8a9099;
}

.retry-btn {
  width: 360rpx;
}

.back-btn {
  margin-top: 20rpx;
}
</style>
