<script setup>
/**
 * 趟次详情 —— 司机端的核心页面。
 *
 * 数据来源：GET /api/mobile/trips/{trip_key}
 * 门店顺序由后端按 sequence 排好返回，前端**不再排序**：
 * 顺序是调度方案的执行结果，前端重排会出现「界面上看到的顺序和考核口径不一致」。
 *
 * ★ 打卡状态机（与 backend/app/services/mobile.py 的校验一一对应）：
 *     dispatched 待打卡 → [到店 arrive] → arrived 已到店
 *     arrived 已到店     → [离店 depart] 或 [完成 complete] → done 已完成
 *   「离店」和「完成」在服务端是**平的**两个终态动作（都落 done），
 *   所以到店之后两个按钮都给，不要求先离店再完成（那样第二步会被 409 拦掉）。
 *
 * ★ 409 不是系统故障：重复点击、弱网重发都会撞上，提示即可，绝不能让页面崩。
 *
 * ★ 确认接单（本次新增）：页面顶部一条确认带 —— 未确认时是橙色背景 + 醒目的
 *   「确认收到」按钮，已确认时是绿色 + 「已确认接单 时间」。
 *   确认成功后就地更新本地状态并 toast，不整页重拉（弱网下重拉会让司机以为没反应）。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import * as api from '@/api'
import {
  acceptStatusClass,
  acceptStatusText,
  actionLabel,
  applyAcceptance,
  callPhone,
  copyText,
  formatDate,
  formatTime,
  stopStatusClass,
  stopStatusLabel,
  timeWindowLabel,
  tripState,
  tripStatusClass,
  tripStatusText,
} from '@/utils/format'
import { requireLogin } from '@/utils/ui'

const tripKey = ref('')
const detail = ref(null)
const loading = ref(false)
const errorMsg = ref('')
/** 正在打卡的明细 id：防止连点（这是 409 的主要来源） */
const actingId = ref(0)
/** 正在确认接单（后端幂等，这里只是防重复请求） */
const accepting = ref(false)

const stops = computed(() => detail.value?.stops || [])

/** 是否还有门店没打卡完（待打卡 = dispatched） */
const hasPending = computed(() => stops.value.some((s) => s.status === 'dispatched'))
/** 是否有已到店未离店的门店 */
const hasArrived = computed(() => stops.value.some((s) => s.status === 'arrived'))

/**
 * 是否显示「完成本趟」。
 * ★ 后端没有「趟次级完成」接口（完成是按门店打的），所以这里在最后一个
 *   已到店的门店上打 complete —— 服务端把它的明细推进到 done，
 *   整趟进度就齐了。只在还有门店没完成时显示，避免重复提交撞 409。
 */
const canCompleteTrip = computed(() => {
  if (!stops.value.length || hasPending.value) return false
  return stops.value.some((s) => s.status !== 'done' && s.status !== 'completed')
})

/** 进度百分比 */
const progress = computed(() => {
  if (!detail.value?.store_count) return 0
  return Math.round((detail.value.done_stores / detail.value.store_count) * 100)
})

async function load() {
  if (!requireLogin()) return
  if (!tripKey.value) {
    errorMsg.value = '缺少趟次标识（trip_key）'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    detail.value = await api.fetchTripDetail(tripKey.value)
  } catch (err) {
    errorMsg.value = err.message || '加载趟次详情失败'
    detail.value = null
  } finally {
    loading.value = false
  }
}

/**
 * 取当前定位（打卡定位是「现场事实」的一部分，但**不阻塞打卡**）。
 * 用户拒绝授权或定位失败时返回空对象，打卡照常进行。
 */
function getLocation() {
  return new Promise((resolve) => {
    uni.getLocation({
      type: 'gcj02', // 微信小程序的 openLocation 要求 gcj02
      success: (res) => resolve({ latitude: res.latitude, longitude: res.longitude }),
      fail: () => resolve({}),
    })
  })
}

/**
 * 确认收到任务（趟次级，与门店打卡无关）。
 *
 * ★ 幂等：后端重复调用返回 200 且不覆盖首次确认时间，
 *   所以这里不做二次确认弹窗，只防连点。
 * ★ 成功后**就地**更新 detail.accepted / accepted_at 并 toast，
 *   不重新 load()：弱网下重拉会让司机以为没点上。
 */
async function confirmAccept() {
  if (!detail.value || detail.value.accepted || accepting.value) return
  accepting.value = true
  uni.showLoading({ title: '确认中…', mask: true })
  try {
    const res = await api.acceptTrip(tripKey.value)
    uni.hideLoading()
    applyAcceptance(detail.value, res)
    uni.showToast({
      title: res?.already_accepted ? '该趟次此前已确认' : '已确认接单',
      icon: 'success',
      duration: 2000,
    })
  } catch (err) {
    uni.hideLoading()
    let tip = err.message || '确认失败'
    if (err.code === 403) {
      tip = '该趟次不属于你名下的车辆，无法确认'
    } else if (err.code === 0) {
      tip = '网络不通，确认未提交成功，请到有信号的地方重试'
    }
    uni.showModal({ title: '确认未成功', content: tip, showCancel: false, confirmText: '知道了' })
  } finally {
    accepting.value = false
  }
}

/** 打卡 */
async function doCheckin(stop, action) {
  if (actingId.value) return
  actingId.value = stop.plan_detail_id
  uni.showLoading({ title: '提交中…', mask: true })
  try {
    const location = await getLocation()
    const res = await api.checkin({
      plan_detail_id: stop.plan_detail_id,
      action,
      latitude: location.latitude,
      longitude: location.longitude,
    })
    uni.hideLoading()
    uni.showToast({ title: res?.message || `已记录${actionLabel(action)}`, icon: 'none', duration: 2500 })
    await load()
  } catch (err) {
    uni.hideLoading()
    // 409 = 重复打卡/顺序不对（业务冲突），403 = 不是自己的车，0 = 网络不通
    let tip = err.message || '打卡失败'
    if (err.code === 409) {
      tip = `${tip}（请勿重复打卡，页面已为你刷新）`
    } else if (err.code === 403) {
      tip = '该门店不属于你名下的车辆，无法打卡'
    } else if (err.code === 0) {
      tip = '网络不通，打卡未提交成功，请到有信号的地方重试'
    }
    uni.showModal({
      title: '打卡未成功',
      content: tip,
      showCancel: false,
      confirmText: '知道了',
    })
    // 无论成功与否都刷新一次：409 往往说明本地状态已经过期
    if (err.code === 409) await load()
  } finally {
    actingId.value = 0
  }
}

/** 完成本趟：在最后一个未完成、已到店的门店上打 complete */
function completeTrip() {
  const target = [...stops.value].reverse().find((s) => s.status !== 'done' && s.status !== 'completed')
  if (!target) {
    uni.showToast({ title: '没有待完成的门店', icon: 'none' })
    return
  }
  uni.showModal({
    title: '完成本趟',
    content: `将把「${target.store_name}」标记为完成，整趟结束。确定吗？`,
    success: (res) => {
      if (res.confirm) doCheckin(target, 'complete')
    },
  })
}

/** 导航：有坐标用系统地图，没有坐标退化为复制地址 */
function navigate(stop) {
  if (stop.latitude != null && stop.longitude != null) {
    uni.openLocation({
      latitude: Number(stop.latitude),
      longitude: Number(stop.longitude),
      name: stop.store_name,
      address: stop.address || '',
      scale: 16,
      fail: () => {
        // H5 端 openLocation 支持有限（浏览器下会走地图网页），失败就退回复制
        copyText(stop.address || stop.store_name, '已复制门店地址')
      },
    })
    return
  }
  copyText(stop.address || stop.store_name, '该门店没有坐标，已复制地址')
}

function reportException(stop) {
  // 带上门店信息，上报后调度员能看到是「哪一趟的哪一家店」出的问题
  const parts = [`tripKey=${encodeURIComponent(tripKey.value)}`, `taskId=${detail.value?.task_id || ''}`]
  if (stop) {
    parts.push(`storeId=${stop.store_id}`)
    parts.push(`planDetailId=${stop.plan_detail_id}`)
    parts.push(`storeName=${encodeURIComponent(stop.store_name || '')}`)
  }
  uni.navigateTo({ url: `/pages/exception/report?${parts.join('&')}` })
}

onLoad((options) => {
  // trip_key 里有冒号，跳转时已 encode，这里再兜一层
  tripKey.value = decodeURIComponent(options?.tripKey || '')
  load()
})
</script>

<template>
  <view class="page">
    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试 -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load">重 试</button>
    </view>

    <template v-else-if="detail">
      <!-- 确认接单带：三色与列表卡片一致（红=未确认 / 黄=已接单未完成 / 绿=已完成） -->
      <view class="accept-bar" :class="`accept-bar-${tripState(detail)}`">
        <view class="accept-text">
          <view class="accept-status">
            {{ acceptStatusText(detail) }}
          </view>
          <view class="accept-hint">
            {{
              tripState(detail) === 'done'
                ? '本趟已跑完，记录保留在这里可随时回看'
                : detail.accepted
                  ? '调度中心已知悉你收到该趟任务'
                  : '请先确认收到任务，再按门店顺序执行'
            }}
          </view>
        </view>
        <button
          v-if="tripState(detail) === 'pending'"
          class="btn btn-primary accept-btn"
          :disabled="accepting"
          @click="confirmAccept"
        >
          {{ accepting ? '确认中…' : '确认收到' }}
        </button>
        <text v-else class="accept-mark">✓</text>
      </view>

      <!-- 趟次概览 -->
      <view class="card">
        <view class="trip-head">
          <text class="plate">{{ detail.plate_no || '未知车牌' }}</text>
          <text class="tag" :class="tripStatusClass(detail.trip_status)">
            {{ tripStatusText(detail) }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">任务 / 方案</text>
          <text class="row-value">{{ detail.task_code }} / {{ detail.plan_code || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">出车顺序</text>
          <text class="row-value">
            本车今天第 {{ detail.trip_no }} 趟<text
              v-if="detail.vehicle_trip_count > 1"
            >（共 {{ detail.vehicle_trip_count }} 趟）</text>
            · {{ timeWindowLabel(detail.time_window) }}送
          </text>
        </view>
        <view class="row">
          <text class="row-label">日期</text>
          <text class="row-value">{{ formatDate(detail.schedule_date) }}</text>
        </view>
        <view class="row">
          <text class="row-label">车型</text>
          <text class="row-value">
            {{ detail.vehicle_type_name || detail.vehicle_type || '—' }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">司机</text>
          <text class="row-value">
            {{ detail.driver_name || '—' }}
            <text v-if="detail.driver_phone" class="phone-link" @click="callPhone(detail.driver_phone)">
              {{ detail.driver_phone }}
            </text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">门店 / 总货量</text>
          <text class="row-value">{{ detail.store_count }} 家 · {{ detail.total_load }} 件</text>
        </view>

        <view class="progress-line">
          <view class="progress-bar">
            <view class="progress-inner" :style="{ width: progress + '%' }" />
          </view>
          <text class="progress-text">
            已完成 {{ detail.done_stores }}/{{ detail.store_count }}（{{ progress }}%）
            <text v-if="detail.arrived_stores"> · {{ detail.arrived_stores }} 家已到店未离店</text>
          </text>
        </view>
      </view>

      <!-- 门店序列 -->
      <view class="section-title">门店顺序（按调度顺序执行）</view>

      <view v-for="(stop, index) in stops" :key="stop.plan_detail_id" class="card stop-card">
        <view class="stop-head">
          <view class="seq" :class="stop.status === 'done' ? 'seq-done' : ''">{{ index + 1 }}</view>
          <view class="stop-name">{{ stop.store_name }}</view>
          <text class="tag" :class="stopStatusClass(stop.status)">
            {{ stopStatusLabel(stop.status) }}
          </text>
        </view>

        <view class="stop-addr" @click="navigate(stop)">{{ stop.address || '（无地址）' }}</view>

        <view class="row">
          <text class="row-label">货量</text>
          <text class="row-value">{{ stop.load_amount }} 件</text>
        </view>
        <view class="row">
          <text class="row-label">联系人</text>
          <text class="row-value">
            {{ stop.contact || '—' }}
            <text v-if="stop.phone" class="phone-link" @click="callPhone(stop.phone)">
              {{ stop.phone }}
            </text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">坐标</text>
          <text class="row-value">
            {{
              stop.latitude != null && stop.longitude != null
                ? `${stop.latitude}, ${stop.longitude}`
                : '无（导航将复制地址）'
            }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">最近执行</text>
          <text class="row-value">
            {{
              stop.last_action
                ? `${actionLabel(stop.last_action)} ${formatTime(stop.last_action_at)}`
                : '暂无打卡记录'
            }}
            <text v-if="stop.photo_attachment_ids && stop.photo_attachment_ids.length">
              · {{ stop.photo_attachment_ids.length }} 张照片
            </text>
          </text>
        </view>

        <!-- 操作区 -->
        <view class="stop-actions">
          <button class="btn btn-default act-btn" @click="navigate(stop)">导航</button>
          <button
            v-if="stop.status === 'dispatched'"
            class="btn btn-primary act-btn"
            :disabled="actingId === stop.plan_detail_id"
            @click="doCheckin(stop, 'arrive')"
          >
            到店打卡
          </button>
          <button
            v-if="stop.status === 'arrived'"
            class="btn btn-primary act-btn"
            :disabled="actingId === stop.plan_detail_id"
            @click="doCheckin(stop, 'depart')"
          >
            离店
          </button>
          <button
            v-if="stop.status === 'arrived'"
            class="btn btn-plain act-btn"
            :disabled="actingId === stop.plan_detail_id"
            @click="doCheckin(stop, 'complete')"
          >
            直接完成
          </button>
          <button
            v-if="stop.status === 'planned'"
            class="btn btn-disabled act-btn"
            disabled
          >
            趟次未下发
          </button>
          <button class="btn btn-plain act-btn" @click="reportException(stop)">异常</button>
        </view>
      </view>

      <!-- 底部汇总操作 -->
      <view class="foot-actions">
        <button class="btn btn-plain foot-btn" @click="reportException(null)">整趟异常上报</button>
        <button class="btn btn-plain foot-btn" @click="load">刷新状态</button>
      </view>
      <button v-if="canCompleteTrip" class="btn btn-primary complete-btn" @click="completeTrip">
        完成本趟
      </button>
      <view v-else-if="detail.trip_status === 'done'" class="all-done">本趟已全部完成 ✓</view>
    </template>
  </view>
</template>

<style scoped>
/* 确认接单带 */
.accept-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
}

/* 三色确认带：红=未确认 / 黄=已接单未完成 / 绿=已完成（与列表卡片同一口径） */
.accept-bar-pending {
  background: #fdecec;
  border-left: 8rpx solid #d03050;
}

.accept-bar-accepted {
  background: #fff7e0;
  border-left: 8rpx solid #d9a406;
}

.accept-bar-done {
  background: #e8f7ee;
  border-left: 8rpx solid #18a058;
}

.accept-status {
  font-size: 30rpx;
  font-weight: 600;
}

.accept-bar-pending .accept-status {
  color: #c0392b;
}

.accept-bar-accepted .accept-status {
  color: #b7791f;
}

.accept-bar-done .accept-status {
  color: #18a058;
}

.accept-hint {
  color: #8a9099;
  font-size: 22rpx;
  margin-top: 8rpx;
}

.accept-btn {
  font-size: 26rpx;
  line-height: 2.2;
  padding: 0 28rpx;
  margin: 0;
  flex-shrink: 0;
}

.accept-mark {
  color: #18a058;
  font-size: 48rpx;
  font-weight: 700;
}

.trip-head {
  display: flex;
  align-items: center;
  margin-bottom: 12rpx;
}

.plate {
  font-size: 36rpx;
  font-weight: 700;
  letter-spacing: 2rpx;
}

.tag {
  margin-left: auto;
}

.phone-link {
  color: #1668dc;
  margin-left: 12rpx;
}

.progress-line {
  margin-top: 16rpx;
}

.progress-bar {
  height: 12rpx;
  background: #eef0f3;
  border-radius: 6rpx;
  overflow: hidden;
}

.progress-inner {
  height: 100%;
  background: #18a058;
}

.progress-text {
  display: block;
  color: #8a9099;
  font-size: 22rpx;
  margin-top: 8rpx;
}

.section-title {
  font-size: 28rpx;
  font-weight: 600;
  margin: 8rpx 0 16rpx;
}

.stop-card {
  border-top: 6rpx solid #eef0f3;
}

.stop-head {
  display: flex;
  align-items: center;
  margin-bottom: 12rpx;
}

.seq {
  width: 44rpx;
  height: 44rpx;
  line-height: 44rpx;
  text-align: center;
  border-radius: 50%;
  background: #1668dc;
  color: #ffffff;
  font-size: 24rpx;
  margin-right: 16rpx;
  flex-shrink: 0;
}

.seq-done {
  background: #18a058;
}

.stop-name {
  font-size: 30rpx;
  font-weight: 600;
  flex: 1;
}

.stop-addr {
  color: #4b5563;
  font-size: 26rpx;
  padding: 12rpx 0 4rpx;
  text-decoration: underline;
  word-break: break-all;
}

.stop-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 20rpx;
}

.act-btn {
  flex: 1;
  font-size: 26rpx;
}

.foot-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 8rpx;
}

.foot-btn {
  flex: 1;
}

.complete-btn {
  margin-top: 20rpx;
}

.all-done {
  text-align: center;
  color: #18a058;
  font-size: 28rpx;
  padding: 24rpx 0;
}

.retry-btn {
  width: 320rpx;
}
</style>
