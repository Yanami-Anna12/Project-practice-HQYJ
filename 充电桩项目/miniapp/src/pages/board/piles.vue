<script setup>
/**
 * 充电桩状态（从掌上看板进来的二级页）。
 *
 * 数据来源：
 *   · GET /admin/piles/status-summary → 顶部三档状态 + 枪数总计（不带条件，全量汇总）；
 *   · GET /admin/piles               → 下面的列表（状态 / 关键词 / 站点 / 分页）；
 *   · GET /admin/stations/options     → 站点筛选下拉。
 *
 * ★ 顶部汇总与下面列表**口径不同**：汇总是全量（后端按数据权限过滤），
 *   不随下面的 chip / 关键词变化；列表才是筛选结果。页面上写明这一点，
 *   否则「筛了故障却还是显示运行 20 台」会被当成 bug。
 *
 * ★ 质保到期：过保的桩要一眼看出来（过保意味着维修要花钱走审批），
 *   用 utils/format 的 isPastDate 自己比日期，不依赖后端多给一个字段。
 *
 * ★ 本页是二级页，**不放底部导航**（用 .page-plain 收掉底部留白），
 *   但给一个「返回看板」按钮兜底：H5 直接刷新本页时是没有上一页栈的。
 */
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import { formatDate, isPastDate, pileStatusClass } from '@/utils/format'
import { errorText, requireLogin } from '@/utils/ui'

/** 与后端状态枚举一致；「全部」= 不传 status */
const STATUS_CHIPS = ['全部', '运行', '故障', '停用']
const PILE_STATUS_ORDER = ['运行', '故障', '停用']
const PAGE_SIZE = 10

const summary = ref(null)
const stations = ref([])
const items = ref([])
const page = ref(1)
const total = ref(0)
const hasNext = ref(false)
const loading = ref(false)
const loadingMore = ref(false)
const errorMsg = ref('')

const status = ref('全部')
const keywordDraft = ref('')
const keyword = ref('')
/** 站点下拉的选中下标：0 = 全部站点（不传 station_id） */
const stationIndex = ref(0)

/**
 * 固定按 运行/故障/停用 三档展示。
 * ★ 不直接渲染 status_dist：后端只返回有数据的档位，某档为 0 时整块消失，
 *   而「停用 0 台」本身就是管理者要确认的信息。
 */
const pileRows = computed(() => {
  const dist = (summary.value && summary.value.status_dist) || []
  const map = {}
  dist.forEach((row) => {
    map[row.name] = row.value
  })
  return PILE_STATUS_ORDER.map((name) => ({ name, value: Number(map[name]) || 0 }))
})

const gunTotal = computed(() => Number((summary.value && summary.value.gun_total) || 0))

/** 站点下拉的展示文案：第一个永远是「全部站点」 */
const stationNames = computed(() => ['全部站点'].concat(stations.value.map((s) => s.name)))

/** 当前选中的站点 id（全部站点时为 undefined，api 层会把它从参数里去掉） */
const stationId = computed(() => {
  if (stationIndex.value <= 0) return undefined
  const hit = stations.value[stationIndex.value - 1]
  return hit ? hit.id : undefined
})

/* ---------------- 加载 ---------------- */
async function loadSummary() {
  try {
    summary.value = await api.fetchPileStatusSummary()
  } catch (err) {
    // 汇总失败只是没有顶部数字，列表照常可用
    summary.value = null
    console.warn('[piles] 状态汇总获取失败', err)
  }
}

async function loadStations() {
  try {
    const list = await api.fetchStationOptions()
    stations.value = Array.isArray(list) ? list : []
  } catch (err) {
    // 站点下拉拿不到时退化成「只有全部站点」，不阻塞列表
    stations.value = []
    console.warn('[piles] 站点选项获取失败', err)
  }
}

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
    const data = await api.fetchPiles({
      stationId: stationId.value,
      keyword: keyword.value || undefined,
      status: status.value === '全部' ? undefined : status.value,
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
      errorMsg.value = errorText(err, '加载充电桩失败')
    } else {
      // 翻页失败只 toast：已经拉到的列表不能因为翻页失败而清空
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

/** 状态 chip：值没变不重查，变了必须回到第 1 页 */
function setStatus(value) {
  if (status.value === value) return
  status.value = value
  load(true)
}

function applyKeyword() {
  keyword.value = keywordDraft.value.trim()
  load(true)
}

function onStationChange(event) {
  stationIndex.value = Number(event.detail.value) || 0
  load(true)
}

/** 重置：三个条件一起清掉（只清一个会让人以为「重置没生效」） */
function resetFilters() {
  keywordDraft.value = ''
  keyword.value = ''
  stationIndex.value = 0
  status.value = '全部'
  load(true)
}

/* ---------------- 跳转 ---------------- */
function goBack() {
  // 从看板点进来时栈里有上一页；H5 直接刷新本页时没有，退回看板兜底
  if (getCurrentPages().length > 1) {
    uni.navigateBack()
    return
  }
  uni.redirectTo({ url: '/pages/board/index' })
}

onShow(() => {
  // 站点选项只在第一次进页面时拉一次（它几乎不变），其余每次显示都刷新数据
  if (!stations.value.length) loadStations()
  loadSummary()
  load(true)
})

onPullDownRefresh(async () => {
  await Promise.all([loadSummary(), load(true)])
  // ★ 必须调用，否则转圈会一直停在顶部
  uni.stopPullDownRefresh()
})
</script>

<template>
  <view class="page page-plain">
    <!-- 顶部三档 + 枪数：全量汇总，不随下面筛选变化 -->
    <view class="stat-grid">
      <view v-for="row in pileRows" :key="row.name" class="stat-card">
        <view class="stat-value">{{ row.value }}</view>
        <view class="stat-label">
          <text class="tag" :class="pileStatusClass(row.name)">{{ row.name }}</text>
        </view>
      </view>
    </view>
    <view class="card gun-card">
      <view class="row">
        <text class="row-label">充电枪总数</text>
        <text class="row-value strong">{{ gunTotal }} 把</text>
      </view>
      <view class="desc">
        顶部三档与枪数为全量汇总（按当前账号数据权限），不随下面的筛选变化；列表才是筛选结果。
      </view>
    </view>

    <!-- 关键词 + 站点筛选 -->
    <view class="card filter-card">
      <input
        v-model="keywordDraft"
        class="form-input"
        type="text"
        placeholder="资产码 / 名称 / 型号"
        confirm-type="search"
        @confirm="applyKeyword"
      />
      <picker
        class="station-picker"
        mode="selector"
        :range="stationNames"
        :value="stationIndex"
        @change="onStationChange"
      >
        <view class="form-picker">
          <text>{{ stationNames[stationIndex] }}</text>
          <text class="picker-arrow">▾</text>
        </view>
      </picker>
      <view class="filter-actions">
        <view class="btn btn-primary filter-btn" @click="applyKeyword">搜 索</view>
        <view class="btn btn-plain filter-btn" @click="resetFilters">重 置</view>
      </view>
    </view>

    <view class="chip-row">
      <view
        v-for="item in STATUS_CHIPS"
        :key="item"
        class="chip"
        :class="status === item ? 'chip-active' : ''"
        @click="setStatus(item)"
      >
        {{ item }}
      </view>
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <view class="btn btn-primary retry-btn" @click="load(true)">重 试</view>
    </view>

    <view v-else-if="!items.length" class="empty">没有符合条件的充电桩</view>

    <template v-else>
      <view v-for="pile in items" :key="pile.id" class="card pile-card">
        <view class="pile-head">
          <!-- 资产码是现场扫码/对账时唯一认得出的标识，等宽字体 + 醒目 -->
          <text class="asset-code">{{ pile.asset_code }}</text>
          <text class="tag" :class="pileStatusClass(pile.status)">{{ pile.status }}</text>
          <!-- 在线状态走 pileStatusClass 的「运行/离线」两档，配色口径只有一个来源 -->
          <text class="tag" :class="pileStatusClass(pile.online ? '运行' : '离线')">
            {{ pile.online ? '在线' : '离线' }}
          </text>
          <text v-if="isPastDate(pile.warranty_until)" class="tag tag-warn">已过保</text>
        </view>

        <view class="pile-name">{{ pile.name }}</view>

        <view class="row">
          <text class="row-label">所属站点</text>
          <text class="row-value">{{ pile.station_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">型号</text>
          <text class="row-value">{{ pile.model || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">额定功率</text>
          <text class="row-value">
            {{ pile.rated_power ? pile.rated_power + ' kW' : '—' }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">枪型 / 枪数</text>
          <text class="row-value">{{ pile.gun_types || '—' }} · {{ pile.gun_count || 0 }} 枪</text>
        </view>
        <view class="row">
          <text class="row-label">厂商</text>
          <text class="row-value">{{ pile.manufacturer || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">投运日期</text>
          <text class="row-value">{{ formatDate(pile.install_date) }}</text>
        </view>
        <view class="row">
          <text class="row-label">质保到期</text>
          <text class="row-value" :class="isPastDate(pile.warranty_until) ? 'expired-text' : ''">
            {{ formatDate(pile.warranty_until) }}
          </text>
        </view>
      </view>

      <view v-if="hasNext" class="load-more" @click="loadMore">
        {{ loadingMore ? '加载中…' : '加载更多' }}
      </view>
      <view v-else class="list-hint muted">共 {{ total }} 台充电桩</view>
    </template>

    <view class="back-row">
      <view class="btn btn-default back-btn" @click="goBack">返回看板</view>
    </view>
  </view>
</template>

<style scoped>
.gun-card {
  padding: 20rpx 24rpx;
}

.filter-card {
  padding: 20rpx 24rpx;
}

.station-picker {
  margin-top: 16rpx;
}

.filter-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 16rpx;
}

.filter-btn {
  flex: 1;
}

.pile-card {
  border-left: 8rpx solid #1677ff;
}

.pile-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.asset-code {
  font-family: Consolas, Menlo, monospace;
  font-size: 30rpx;
  font-weight: 700;
  margin-right: 12rpx;
}

.pile-name {
  font-size: 28rpx;
  font-weight: 600;
  margin: 12rpx 0 8rpx;
}

/* 过保日期也用橙色点一下，和「已过保」标签呼应（不是业务状态，所以不占用状态配色表） */
.expired-text {
  color: #d97706;
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

.back-row {
  padding: 16rpx 0 40rpx;
}

.back-btn {
  width: 320rpx;
  margin: 0 auto;
}

.retry-btn {
  width: 320rpx;
  margin: 0 auto;
}
</style>
