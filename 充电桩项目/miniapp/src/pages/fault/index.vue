<script setup>
/**
 * 故障管理（底部 tab 页，现场作业端与管理端共用）。
 *
 * 数据源：
 *   GET /faults/home  累计 / 待核查 / 已核查 / 核查率 + 等级分布（后端按账号数据权限自动过滤）
 *   GET /faults       分页列表：状态 tab ＋ 关键词 ＋ 等级 ＋「我上报的」可叠加
 *
 * ★ onShow 而不是 onLoad 拉数据：从上报页返回、从别的 tab 切回来都要看到最新条数。
 *   否则刚上报的故障不在列表里，现场会以为没提交成功，转头又报一遍。
 *
 * ★ 为什么要自己折算 SLA 截止时间：
 *   列表接口返回的是 FaultOut，**不含** sla_deadline / sla_overdue（只有 /faults/cards 才带），
 *   而「有没有超 SLA」是现场第一眼要判断的东西。这里按后端 fault_card_list 的同一口径
 *   （reported_at 优先、否则 created_at ＋ 等级 SLA 小时）补一个 sla_deadline，
 *   再交给 utils/format.js 的 isSlaOverdue() 判定 —— 超期判定只有那一个入口，
 *   页面里不另写一套规则，后端哪天改了字段也只是这里少算一次。
 */
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'

import * as api from '@/api'
import BottomNav from '@/components/BottomNav.vue'
import {
  faultLevelClass,
  faultLevelColor,
  faultStatusClass,
  fromNow,
  isSlaOverdue,
  percentText,
  progressPercent,
} from '@/utils/format'
import { errorText, requireLogin } from '@/utils/ui'

/** 状态筛选（与后端 tab 取值一致；「全部」由 api 层转成不传 tab） */
const TABS = ['全部', '待核查', '已核查']
/** 「全部等级」的界面文案：选中它时请求不带 fault_level */
const ALL_LEVEL = '全部'
/** 字典拿不到时的等级兜底：后端 FaultLevel 就是这三档 */
const FALLBACK_LEVELS = ['一般', '严重', '危急']
/** 字典拿不到时的 SLA 兜底：与后端 LEVEL_SLA_HOURS.get(level, 72) 的默认值保持一致 */
const FALLBACK_SLA_HOURS = 72
/** 每页条数：现场多用手机流量，首屏 10 条比 20 条到得更快 */
const PAGE_SIZE = 10

/** 首页统计（含等级分布） */
const home = ref({ total: 0, verified: 0, pending: 0, rejected: 0, verify_rate: 0, level_dist: [] })
const items = ref([])
const meta = ref({ page: 1, has_next: false, total: 0 })
const page = ref(1)

const tab = ref('全部')
const level = ref(ALL_LEVEL)
const keyword = ref('')
const mine = ref(false)

const loading = ref(false)
const loadingMore = ref(false)
const errorMsg = ref('')
const homeError = ref('')
/** 等级 → SLA 小时数（/faults/levels），折算超期用 */
const slaHours = ref({})
/** 等级选项：优先用字典，字典没拉到就退回硬编码的三档 */
const levels = ref(FALLBACK_LEVELS)
/** 字典是否已就绪：没就绪前先把列表拉回来会算错超期，所以首次要等它一下 */
let dictsReady = false

/** 超期条数：卡片上的红标签与顶部告警条共用同一个判定，不会出现「有标签但计数是 0」 */
const overdueCount = computed(() => items.value.filter((item) => isSlaOverdue(item)).length)
/** 等级分布条形的宽度基准：拿最大的一档当满格，否则只有一个值时条形会顶满整行 */
const levelDistMax = computed(() =>
  (home.value.level_dist || []).reduce((max, row) => Math.max(max, Number(row.value) || 0), 0)
)
/** 等级 chip 选项：全部等级 + 字典里的等级 */
const levelOptions = computed(() => [ALL_LEVEL, ...levels.value])

function pad(n) {
  return String(n).padStart(2, '0')
}

/**
 * 解析后端时间。
 * ★ 手动拆年月日构造，而不是 new Date('YYYY-MM-DD HH:mm:ss')：iOS 对该格式的解析历史上不一致，
 *   format.js 里的 fromNow 也是靠 replace(' ', 'T') 绕开这个坑的。
 */
function parseDateTime(value) {
  const matched = String(value || '')
    .replace('T', ' ')
    .slice(0, 19)
    .match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/)
  if (!matched) return null
  return new Date(
    Number(matched[1]),
    Number(matched[2]) - 1,
    Number(matched[3]),
    Number(matched[4]),
    Number(matched[5]),
    Number(matched[6])
  )
}

/** 折算 SLA 截止时间（后端口径：上报时间优先，没有就用创建时间） */
function slaDeadlineOf(item) {
  const base = parseDateTime(item.reported_at || item.created_at)
  if (!base) return ''
  const hours = Number(slaHours.value[item.fault_level]) || FALLBACK_SLA_HOURS
  const deadline = new Date(base.getTime() + hours * 3600 * 1000)
  return (
    `${deadline.getFullYear()}-${pad(deadline.getMonth() + 1)}-${pad(deadline.getDate())} ` +
    `${pad(deadline.getHours())}:${pad(deadline.getMinutes())}:${pad(deadline.getSeconds())}`
  )
}

/** 给列表项补上 sla_deadline（后端已经给了的就沿用后端的） */
function decorate(list) {
  return (list || []).map((item) =>
    item.sla_deadline ? item : { ...item, sla_deadline: slaDeadlineOf(item) }
  )
}

/** 等级 chip 文案：带上 SLA 小时数，方便按响应时限决定先处理哪条 */
function levelChipText(name) {
  if (name === ALL_LEVEL) return '全部等级'
  const hours = slaHours.value[name]
  return hours ? `${name} ${hours}h` : name
}

/** 故障统计：失败只提示一句，不能因为一个统计接口把整个列表页变成错误页 */
async function loadHome() {
  homeError.value = ''
  try {
    home.value = (await api.fetchFaultHome()) || home.value
  } catch (err) {
    homeError.value = errorText(err, '故障统计加载失败')
  }
}

/** 等级 / 状态字典（SLA 小时数、等级选项） */
async function loadDicts() {
  try {
    const dicts = await api.fetchFaultDicts()
    if (dicts && (dicts.levels || []).length) levels.value = dicts.levels
    slaHours.value = (dicts && dicts.level_sla_hours) || {}
    dictsReady = true
  } catch (err) {
    // 字典只影响「chip 上的 SLA 小时数」和超期折算，拿不到就用默认 72 小时，
    // 不能让一个辅助接口失败导致故障列表打不开。
    console.warn('[fault] 故障字典加载失败，SLA 按默认值折算', err)
  }
}

/**
 * 拉列表。
 * @param {boolean} reset true = 从第 1 页重拉（切筛选 / 搜索 / 下拉刷新），false = 加载更多
 */
async function loadList(reset = true) {
  if (!requireLogin()) return
  if (reset) {
    page.value = 1
    loading.value = true
    errorMsg.value = ''
  } else {
    loadingMore.value = true
  }
  try {
    const data = await api.fetchFaults({
      tab: tab.value,
      keyword: keyword.value.trim(),
      faultLevel: level.value === ALL_LEVEL ? '' : level.value,
      mine: mine.value,
      page: page.value,
      pageSize: PAGE_SIZE,
    })
    const list = decorate(data && data.items)
    items.value = reset ? list : items.value.concat(list)
    meta.value = (data && data.meta) || { page: page.value, has_next: false, total: list.length }
  } catch (err) {
    if (reset) {
      // 保留已经加载出来的卡片：弱网下把眼前看到的故障清空，现场会以为数据丢了
      errorMsg.value = errorText(err, '故障列表加载失败')
    } else {
      // 加载更多失败必须把页码退回去，否则下次重试会静默跳过这一页
      page.value -= 1
      uni.showToast({ title: '加载更多失败，请重试', icon: 'none' })
    }
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

/** 整页刷新（切筛选 / 重试 / 下拉刷新都走它） */
async function refresh() {
  await Promise.all([loadHome(), loadList(true)])
}

function pickTab(value) {
  if (tab.value === value) return
  tab.value = value
  loadList(true)
}

function pickLevel(value) {
  if (level.value === value) return
  level.value = value
  loadList(true)
}

function onMineChange(e) {
  // ★ e.detail.value 是布尔值：switch 与 chip 不同，不需要按下标取数组
  mine.value = !!e.detail.value
  loadList(true)
}

function applySearch() {
  loadList(true)
}

/** 重置：关键词 / 等级 / 我上报的 / 状态一起清掉，避免留下「看起来没数据」的隐形条件 */
function resetFilter() {
  keyword.value = ''
  level.value = ALL_LEVEL
  mine.value = false
  tab.value = '全部'
  loadList(true)
}

function loadMore() {
  if (loadingMore.value || !meta.value.has_next) return
  page.value += 1
  loadList(false)
}

function openDetail(item) {
  uni.navigateTo({ url: `/pages/fault/detail?id=${encodeURIComponent(item.id)}` })
}

function openReport() {
  uni.navigateTo({ url: '/pages/fault/report' })
}

/** 扫桩报修入口：就在故障页旁边，现场不用先退回工作台再找 */
function openScan() {
  uni.navigateTo({ url: '/pages/scan/scan' })
}

onShow(async () => {
  if (!requireLogin()) return
  // 首次先把 SLA 字典拿到手，否则第一批卡片的超期标记会按默认 72 小时算错
  if (!dictsReady) await loadDicts()
  refresh()
})

onPullDownRefresh(async () => {
  await refresh()
  // ★ 必须调用 stopPullDownRefresh：否则下拉的转圈会一直挂在页面顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page">
    <!-- 统计条：全量口径（不受下面筛选影响），一进来就知道整体欠了多少核查 -->
    <view class="stat-grid">
      <view class="stat-card">
        <view class="stat-value">{{ home.total }}</view>
        <view class="stat-label">累计故障</view>
      </view>
      <view class="stat-card">
        <view class="stat-value stat-warn">{{ home.pending }}</view>
        <view class="stat-label">待核查</view>
      </view>
      <view class="stat-card">
        <view class="stat-value stat-done">{{ home.verified }}</view>
        <view class="stat-label">已核查</view>
      </view>
      <view class="stat-card">
        <view class="stat-value stat-primary rate-value">{{ percentText(home.verify_rate) }}</view>
        <view class="stat-label">核查率</view>
      </view>
    </view>

    <view v-if="homeError" class="warn-bar" @click="loadHome">{{ homeError }}，点此重试</view>

    <!-- SLA 超期告警：现场唯一「必须马上动」的信号，放最上面 -->
    <view v-if="overdueCount > 0" class="danger-bar">
      有 {{ overdueCount }} 条故障已超过 SLA 响应时限，请优先处理
    </view>

    <view class="toolbar">
      <text class="title">故障管理</text>
      <view class="toolbar-actions">
        <text class="tool-link" @click="openScan">扫桩报修</text>
        <text class="tool-link tool-link-primary" @click="openReport">＋ 故障上报</text>
      </view>
    </view>

    <!-- 状态筛选 -->
    <view class="chip-row">
      <view
        v-for="item in TABS"
        :key="item"
        class="chip"
        :class="tab === item ? 'chip-active' : ''"
        @click="pickTab(item)"
      >
        {{ item }}
      </view>
    </view>

    <!-- 「我上报的」：只筛当前账号报的单子，跟进自己报的故障用 -->
    <view class="card mine-row">
      <view class="mine-text">
        <text class="strong">只看我上报的</text>
        <view class="desc">打开后仅显示当前账号上报的故障，方便盯自己报的单子</view>
      </view>
      <switch :checked="mine" @change="onMineChange" />
    </view>

    <!-- 关键词搜索：故障编号 / 站点 / 桩资产码，后端是模糊匹配 -->
    <view class="search-row">
      <input
        v-model="keyword"
        class="form-input search-input"
        type="text"
        confirm-type="search"
        placeholder="故障编号 / 站点 / 桩资产码"
        @confirm="applySearch"
      />
      <button class="btn btn-primary search-btn" @click="applySearch">搜索</button>
      <text class="reset-link" @click="resetFilter">重置</text>
    </view>

    <!-- 等级筛选 -->
    <view class="chip-row">
      <view
        v-for="item in levelOptions"
        :key="item"
        class="chip"
        :class="level === item ? 'chip-active' : ''"
        @click="pickLevel(item)"
      >
        {{ levelChipText(item) }}
      </view>
    </view>

    <!-- 刷新失败但手里还有数据：用一条可点的提示条，而不是把列表换成错误页 -->
    <view v-if="errorMsg && items.length" class="warn-bar" @click="refresh">
      {{ errorMsg }}，点此重试
    </view>

    <view v-if="loading && !items.length" class="empty">加载中…</view>

    <view v-else-if="errorMsg && !items.length" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="refresh">重 试</button>
    </view>

    <view v-else-if="!items.length" class="empty">
      没有符合条件的故障{{ keyword ? '，换个关键词或点「重置」试试' : '' }}
    </view>

    <view v-else>
      <view
        v-for="item in items"
        :key="item.id"
        class="card fault-card"
        :style="{ borderLeftColor: faultLevelColor(item.fault_level) }"
        @click="openDetail(item)"
      >
        <view class="fault-head">
          <text class="fault-no">{{ item.fault_no }}</text>
          <text class="tag" :class="faultStatusClass(item.status)">{{ item.status }}</text>
        </view>

        <view class="fault-tags">
          <text class="fault-type">{{ item.fault_type || '未填写类型' }}</text>
          <text class="tag" :class="faultLevelClass(item.fault_level)">{{ item.fault_level }}</text>
          <text v-if="isSlaOverdue(item)" class="tag tag-danger">已超 SLA</text>
        </view>

        <view class="row">
          <text class="row-label">站点</text>
          <text class="row-value">{{ item.station_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">充电桩</text>
          <text class="row-value">{{ item.pile_asset_code || '未指定（整站 / 通信类）' }}</text>
        </view>
        <view class="row">
          <text class="row-label">上报人 / 时间</text>
          <text class="row-value">{{ item.reporter_name || '—' }} · {{ fromNow(item.created_at) }}</text>
        </view>

        <view v-if="item.description" class="fault-desc">{{ item.description }}</view>
        <view class="fault-foot">点击查看详情并核查 ›</view>
      </view>

      <button
        v-if="meta.has_next"
        class="btn btn-plain more-btn"
        :disabled="loadingMore"
        @click="loadMore"
      >
        {{ loadingMore ? '加载中…' : '加载更多' }}
      </button>
      <view v-else class="list-end">已显示全部 {{ items.length }} 条</view>
    </view>

    <!-- 等级分布：整体结构一眼可见，放在列表之后，不挤占现场要处理的卡片 -->
    <view v-if="(home.level_dist || []).length" class="card">
      <view class="section-title">
        <text>等级分布</text>
        <text class="muted">累计 {{ home.total }} 条</text>
      </view>
      <view v-for="row in home.level_dist" :key="row.name" class="dist-row">
        <text class="dist-name">{{ row.name }}</text>
        <view class="dist-bar-wrap">
          <view
            class="dist-bar"
            :style="{
              width: progressPercent(row.value, levelDistMax) + '%',
              background: faultLevelColor(row.name),
            }"
          />
        </view>
        <text class="dist-value">{{ row.value }}</text>
      </view>
    </view>

    <BottomNav />
  </view>
</template>

<style scoped>
/* 核查率是百分比，40rpx 的默认字号在四等分卡片里会换行 */
.rate-value {
  font-size: 34rpx;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 24rpx;
}

.tool-link {
  font-size: 26rpx;
  color: #4b5563;
}

.tool-link-primary {
  color: #1677ff;
  font-weight: 600;
}

.mine-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mine-text {
  flex: 1;
  padding-right: 20rpx;
}

.search-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.search-input {
  flex: 1;
}

.search-btn {
  flex-shrink: 0;
  margin: 0;
  padding: 0 26rpx;
  font-size: 26rpx;
  line-height: 2.6;
}

.reset-link {
  flex-shrink: 0;
  color: #1677ff;
  font-size: 25rpx;
}

/* 等级色条：颜色由 faultLevelColor() 通过 :style 给，这里只定粗细与兜底色 */
.fault-card {
  border-left: 8rpx solid #c9ced6;
}

.fault-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.fault-no {
  font-size: 30rpx;
  font-weight: 600;
}

.fault-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8rpx;
  margin: 10rpx 0 4rpx;
}

.fault-tags .tag {
  margin-left: 0;
}

.fault-type {
  font-size: 27rpx;
  font-weight: 600;
  margin-right: 4rpx;
}

/* 描述摘要固定两行：卡片高度一致，一屏能看到更多故障 */
.fault-desc {
  color: #4b5563;
  font-size: 25rpx;
  line-height: 1.5;
  margin-top: 12rpx;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.fault-foot {
  margin-top: 16rpx;
  font-size: 22rpx;
  color: #8a9099;
}

.more-btn {
  margin-bottom: 20rpx;
}

.list-end {
  text-align: center;
  color: #8a9099;
  font-size: 24rpx;
  padding: 16rpx 0 24rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
