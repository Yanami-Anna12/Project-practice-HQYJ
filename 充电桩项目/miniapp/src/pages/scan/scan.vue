<script setup>
/**
 * 扫码查桩报修（现场真实动作：走到桩前 → 扫桩身资产码 → 直接报修）。
 *
 * 为什么要有这一页：报修表单要选「项目 → 站点 → 桩」三层，
 * 而人已经站在桩前面了，这三层其实是**已知信息**。扫一下资产码把它变成一次点击，
 * 报修时项目、站点、桩全部自动带出（见 pages/fault/report.vue 的 onLoad 参数）。
 *
 * ★ H5 没有摄像头：uni.scanCode 在浏览器里不可用（调用即 fail），
 *   所以手动输入资产码不是「备选」而是 H5 端的**主入口**，默认就展示；
 *   平台判断用 @/config 的 PLATFORM_NAME —— 微信运行时没有 Node 的那套全局对象，
 *   页面里一律通过 PLATFORM_NAME 判断平台，不读任何构建期环境变量。
 */
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'

import * as api from '@/api'
import { PLATFORM_NAME } from '@/config'
import { faultLevelClass, faultStatusClass, formatDateTime, pileStatusClass } from '@/utils/format'
import { accountProfile, errorText, requireLogin } from '@/utils/ui'

const isH5 = PLATFORM_NAME === 'h5'
/** 两种平台给同一句人话：H5 说清为什么只能手输，小程序说清扫不出来时怎么办 */
const scanHint = isH5
  ? '浏览器里没有摄像头扫码，请手动输入资产码（小程序端可直接扫桩身二维码）'
  : '对准桩身上的资产码二维码扫描；二维码磨损扫不出来时，也可以在下面手动输入'

const assetInput = ref('')
/** 最近一次查询用的关键词：查不到桩时，「直接报修」靠它把资产码带到报修页 */
const keyword = ref('')
const results = ref([])
const selected = ref(null)
const searching = ref(false)
/** 是否查询过：用来区分「还没查」和「查了但没有」，否则一进页面就显示空态很怪 */
const searched = ref(false)
const errorMsg = ref('')

/** 站点选项：只为按 station_id 反查 project_id（报修页要项目才能全自动带出） */
const stations = ref([])
const history = ref([])
const historyLoading = ref(false)
const historyError = ref('')

/**
 * 从扫码结果里提取资产码。
 * ★ 桩身二维码里的内容不一定是纯资产码：可能是带前缀的文本，也可能是一段带参数的 URL，
 *   所以先按资产码的形态（两位字母 + 6 位以上数字，如 CP0010016）取第一段匹配；
 *   取不到就把整串交给后端当关键词模糊查 —— 后端按 asset_code ilike 匹配，
 *   关键词宽一点最多多几条候选，比直接报「查不到」友好得多。
 */
function extractAssetCode(text) {
  const raw = String(text == null ? '' : text).trim()
  if (!raw) return ''
  const matched = raw.match(/[A-Za-z]{2}\d{6,}/)
  return matched ? matched[0] : raw
}

/** 扫一扫 */
function scan() {
  if (isH5) {
    // 浏览器端点了就给手动输入的说明，而不是弹一个看不懂的「不支持」
    uni.showToast({ title: scanHint, icon: 'none', duration: 3000 })
    return
  }
  if (typeof uni.scanCode !== 'function') {
    uni.showToast({ title: scanHint, icon: 'none', duration: 3000 })
    return
  }
  uni.scanCode({
    scanType: ['qrCode', 'barCode'],
    success: (res) => {
      const code = extractAssetCode(res && res.result)
      if (!code) {
        uni.showToast({ title: '没识别出资产码，请手动输入', icon: 'none', duration: 2500 })
        return
      }
      assetInput.value = code
      runQuery()
    },
    fail: () => {
      // 用户取消、摄像头被占用、二维码磨损都会走到这里 —— 统一引导手动输入，不报错吓人
      uni.showToast({ title: '没有扫到，可在下面手动输入资产码', icon: 'none', duration: 2500 })
    },
  })
}

/** 按资产码查询充电桩（后端按 asset_code 模糊匹配，最多返回 200 条） */
async function runQuery() {
  if (searching.value) return
  const kw = assetInput.value.trim()
  if (!kw) {
    uni.showToast({ title: '请输入或扫描桩资产码', icon: 'none' })
    return
  }
  searching.value = true
  errorMsg.value = ''
  selected.value = null
  history.value = []
  historyError.value = ''
  try {
    const list = (await api.fetchPileOptions({ keyword: kw })) || []
    results.value = list
    searched.value = true
    keyword.value = kw
    // 只查到一个就直接选中：现场不想多点一次
    if (list.length === 1) selectPile(list[0])
  } catch (err) {
    results.value = []
    searched.value = true
    errorMsg.value = errorText(err, '查询失败，请检查网络后重试')
  } finally {
    searching.value = false
  }
}

/** 选中一台桩并顺手拉它的历史故障（查桩之后最想看的就是「这桩以前坏过什么」） */
function selectPile(pile) {
  selected.value = pile
  loadHistory(pile.asset_code)
}

/** 该桩的历史故障：列表接口的 keyword 支持桩资产码，取最近 5 条足够现场判断 */
async function loadHistory(assetCode) {
  if (!assetCode) return
  historyLoading.value = true
  historyError.value = ''
  try {
    const data = (await api.fetchFaults({ keyword: assetCode, pageSize: 5 })) || {}
    history.value = data.items || []
  } catch (err) {
    history.value = []
    historyError.value = errorText(err, '历史故障加载失败')
  } finally {
    historyLoading.value = false
  }
}

/**
 * 反查项目：报修页需要 projectId 才能把「项目」也自动带出来。
 * /admin/stations/options 每条都带 project_id，本地匹配即可，不用再加接口；
 * 查不到就不带（报修页会让用户自己选，不会卡住）。
 */
function projectIdOf(stationId) {
  const hit = stations.value.find((item) => item.id === stationId)
  return (hit && hit.project_id) || ''
}

/** 去报修：把桩、站点、项目、资产码一起带过去，报修页不再让用户重选 */
function goReport(pile) {
  const target = pile || selected.value
  if (!target) {
    // 查不到桩也要能报修（新装未登记、台账漏录的桩现场是有的）：
    // 只带资产码，报修页会用它再查一次并把站点、项目补上。
    uni.navigateTo({ url: `/pages/fault/report?assetCode=${encodeURIComponent(keyword.value)}` })
    return
  }
  const params = [
    `pileId=${encodeURIComponent(target.id)}`,
    `assetCode=${encodeURIComponent(target.asset_code || '')}`,
  ]
  if (target.station_id) {
    params.push(`stationId=${encodeURIComponent(target.station_id)}`)
    const projectId = projectIdOf(target.station_id)
    if (projectId) params.push(`projectId=${encodeURIComponent(projectId)}`)
  }
  uni.navigateTo({ url: `/pages/fault/report?${params.join('&')}` })
}

function openFault(item) {
  uni.navigateTo({ url: `/pages/fault/detail?id=${encodeURIComponent(item.id)}` })
}

/**
 * 返回工作台（兜底出口）。
 * 工具页正常用系统返回键就行；但 H5 直接输 URL 进来时页面栈里没有上一页，
 * 那时按账号落地页 redirectTo，避免停在一个没有出口的页面上。
 */
function backToWorkbench() {
  if (getCurrentPages().length > 1) {
    uni.navigateBack()
    return
  }
  uni.redirectTo({
    url: accountProfile().home || '/pages/home/index',
    fail: () => {
      uni.navigateBack()
    },
  })
}

onLoad(() => {
  if (!requireLogin()) return
  loadStations()
})

/** 站点列表只用于反查项目，失败不影响扫码与报修主流程 */
async function loadStations() {
  try {
    stations.value = (await api.fetchStationOptions()) || []
  } catch (err) {
    console.warn('[scan] 站点列表加载失败，报修时项目需手动选择', err)
  }
}
</script>

<template>
  <view class="page">
    <view class="hint-bar">
      扫桩身资产码 → 直接定位到桩 → 报修时项目和站点自动带出，不用再一层层选。
    </view>

    <view class="card">
      <view class="section-title">
        <text>扫码查桩</text>
      </view>
      <button v-if="isH5" class="btn btn-plain" @click="scan">扫一扫（浏览器端不可用）</button>
      <button v-else class="btn btn-primary" @click="scan">扫一扫资产码</button>

      <view class="manual-row">
        <input
          v-model="assetInput"
          class="form-input manual-input"
          type="text"
          confirm-type="search"
          placeholder="手动输入资产码，如 CP0010016"
          @confirm="runQuery"
        />
        <button class="btn btn-primary manual-btn" :disabled="searching" @click="runQuery">
          {{ searching ? '查询中…' : '查询' }}
        </button>
      </view>
      <view class="desc">{{ scanHint }}</view>
    </view>

    <view v-if="searching" class="empty">查询中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="runQuery">重 试</button>
    </view>

    <view v-else>
      <!-- 查到多台时列出来点选：同一段关键词可能命中连号的几个资产码 -->
      <view v-if="results.length > 1" class="card">
        <view class="section-title">
          <text>查到 {{ results.length }} 台，请点选</text>
        </view>
        <view
          v-for="pile in results"
          :key="pile.id"
          class="pile-item"
          :class="{ 'pile-item-active': selected && selected.id === pile.id }"
          @click="selectPile(pile)"
        >
          <view class="pile-head">
            <text class="pile-code">{{ pile.asset_code }}</text>
            <text class="tag" :class="pileStatusClass(pile.status)">{{ pile.status }}</text>
          </view>
          <view class="desc">{{ pile.name || '未命名' }} · {{ pile.station_name || '未知站点' }}</view>
        </view>
      </view>

      <!-- 选中的桩：卡片信息 + 两个动作 -->
      <view v-if="selected" class="card">
        <view class="section-title">
          <text>{{ selected.asset_code }}</text>
          <text class="tag" :class="pileStatusClass(selected.status)">{{ selected.status }}</text>
        </view>
        <view class="row">
          <text class="row-label">桩名称</text>
          <text class="row-value">{{ selected.name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">所属站点</text>
          <text class="row-value">{{ selected.station_name || '—' }}</text>
        </view>
        <view class="action-row">
          <button class="btn btn-primary" @click="goReport(selected)">立即报修</button>
          <!-- 历史故障在选中时已自动拉过一次，这个按钮兼顾「再看一遍」和弱网下重试 -->
          <button class="btn btn-default" @click="loadHistory(selected.asset_code)">
            查看该桩历史故障
          </button>
        </view>
      </view>

      <!-- 查不到也要能报修：新装未登记、台账漏录的桩现场确实存在 -->
      <view v-else-if="searched && !results.length" class="card">
        <view class="empty">没有找到该资产码对应的充电桩</view>
        <view class="desc">可能是台账还没登记；照样可以先报修，报修里手动选站点即可。</view>
        <button class="btn btn-primary retry-btn" @click="goReport(null)">直接报修</button>
      </view>
    </view>

    <!-- 该桩历史故障 -->
    <view v-if="selected" class="card">
      <view class="section-title">
        <text>{{ selected.asset_code }} 的历史故障</text>
        <text class="muted">最近 {{ history.length }} 条</text>
      </view>

      <view v-if="historyLoading" class="empty">加载中…</view>
      <view v-else-if="historyError" class="warn-bar" @click="loadHistory(selected.asset_code)">
        {{ historyError }}，点此重试
      </view>
      <view v-else-if="!history.length" class="empty">该桩还没有上报过故障</view>
      <view v-else>
        <view v-for="item in history" :key="item.id" class="his-item" @click="openFault(item)">
          <view class="his-head">
            <text class="his-no">{{ item.fault_no }}</text>
            <text class="tag" :class="faultStatusClass(item.status)">{{ item.status }}</text>
          </view>
          <view class="his-sub">
            <text>{{ item.fault_type || '未填写类型' }}</text>
            <text class="tag" :class="faultLevelClass(item.fault_level)">{{ item.fault_level }}</text>
          </view>
          <view class="his-time">{{ formatDateTime(item.created_at) }}</view>
        </view>
      </view>
    </view>

    <button class="btn btn-plain back-btn" @click="backToWorkbench">返回工作台</button>
  </view>
</template>

<style scoped>
.manual-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 20rpx;
}

.manual-input {
  flex: 1;
}

.manual-btn {
  flex-shrink: 0;
  margin: 0;
  padding: 0 28rpx;
  font-size: 26rpx;
  line-height: 2.6;
}

.pile-item {
  padding: 18rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}

.pile-item:last-child {
  border-bottom: none;
}

/* 命中当前选中的那台：左侧蓝条 + 淡底，避免多点几次分不清选了哪个 */
.pile-item-active {
  background: #f2f7ff;
  border-left: 8rpx solid #1677ff;
  padding-left: 16rpx;
  border-radius: 8rpx;
}

.pile-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pile-code {
  font-size: 30rpx;
  font-weight: 600;
  letter-spacing: 1rpx;
}

.action-row {
  display: flex;
  gap: 20rpx;
  margin-top: 20rpx;
}

.action-row .btn {
  flex: 1;
  margin: 0;
  font-size: 26rpx;
}

.his-item {
  padding: 18rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}

.his-item:last-child {
  border-bottom: none;
}

.his-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.his-no {
  font-size: 28rpx;
  font-weight: 600;
}

.his-sub {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-top: 8rpx;
  font-size: 26rpx;
  color: #4b5563;
}

.his-sub .tag {
  margin-left: 0;
}

.his-time {
  margin-top: 8rpx;
  font-size: 23rpx;
  color: #8a9099;
}

.back-btn {
  margin-top: 8rpx;
}

.retry-btn {
  width: 320rpx;
  margin-top: 20rpx;
}
</style>
