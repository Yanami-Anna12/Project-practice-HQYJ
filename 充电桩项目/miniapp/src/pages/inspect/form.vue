<script setup>
/**
 * 巡检情况录入（现场作业核心场景）。
 *
 * 路由参数：subtaskId（必填）、orderType（工单类型，决定巡检项模板）、orderName（工单名，仅展示）。
 *
 * ★ 现场流程按真实顺序排：到场签到 → 逐项点正常/异常 → 拍现场照片 → 填备注 → 提交。
 *   每个环节都能「降级继续」：
 *   · 定位拿不到（地下室、信号差）→ 允许签到，只是不带经纬度，服务端这几个字段本来就可选；
 *   · 照片上传失败 → 只丢弃失败的那几张，已选好的巡检项一个字都不能丢；
 *   · 提交失败 → **留在原页、数据全保留**，现场人员最恨的是填完二十项之后白填。
 *
 * ★ 提交前只校验「至少勾了一项」：巡检项一多，逐个必填在电站现场根本做不完，
 *   但一项都没勾的提交一定是误触，必须拦住（后端会存一条空记录，工单进度也会乱）。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import * as api from '@/api'
import { getLocationSafe, nowClock, safeDecode } from '@/utils/format'
import { errorText, requireLogin } from '@/utils/ui'

/** 最多 9 张现场照片（九宫格一屏），与后端附件上限（12）留有余量 */
const MAX_PHOTOS = 9

const subtaskId = ref('')
const orderType = ref('巡视')
const orderName = ref('')

const loading = ref(false)
const errorMsg = ref('')
/** 正在提交（暂存或提交完成），防止连点发出两次巡检记录 */
const submitting = ref(false)

/** 模板原始数据：巡检项按 group 分块，交给模板渲染 */
const template = ref([])
/** 分组后的巡检项（按模板给的顺序分组，不重排，现场按手感从上往下点） */
const groups = ref([])
/** 备注长度上限，由后端模板接口给（PDF 3.4：200 字） */
const maxRemarkLength = ref(200)
/** 结果选项，由后端给（正常 / 异常），页面不写死文案 */
const resultOptions = ref(['正常', '异常'])

/** 每项的作答：key = 巡检项名称，value = { result, remark }。未作答的项不进这个表 */
const answers = ref({})

/** 签到信息：{ location, lng, lat, time } */
const checkin = ref(null)
/** 是否拿不到定位（签到成功但没坐标）—— 页面要如实说明，不能假装有定位 */
const noLocation = ref(false)

/** 整单备注 */
const remark = ref('')
/** 已上传成功的照片（后端相对路径 + 本地预览路径） */
const photos = ref([])
const uploading = ref(false)
/** 上传进度：{ done, total }，用于显示「上传中 2/3…」 */
const uploadProgress = ref({ done: 0, total: 0 })

/* ------------------------------------------------------------------ *
 * 派生数据
 * ------------------------------------------------------------------ */

/** 已勾选的项数 */
const checkedCount = computed(() => Object.keys(answers.value).length)
/** 已判定异常的项数 */
const abnormalCount = computed(
  () => Object.values(answers.value).filter((a) => a.result === '异常').length,
)
/** 巡检项总数（进度提示的分母） */
const totalCount = computed(() => template.value.length)
/** 还有哪些项没勾（「全部正常」按这些项来补） */
const uncheckedCount = computed(() => Math.max(0, totalCount.value - checkedCount.value))

/** 图片绝对地址（<image src> 必须是绝对地址，模板里直接调这个） */
const absoluteUrl = api.absoluteUrl

/** 是否处于「巡检中」未完成的作答状态 */
const showRemarkInput = (name) => answers.value[name]?.result === '异常'

/**
 * 「正常 / 异常」按钮的选中样式。
 * ★ 在 script 里算好类名再交给 :class（只返回一个字符串）：
 *   小程序编译器的 :class 表达式越简单越不容易出错，
 *   而且「异常=红、正常=绿」这套判定只在这里写一次。
 */
function resultBtnClass(name, option) {
  const answer = answers.value[name]
  if (!answer || answer.result !== option) return 'result-btn'
  return option === '异常' ? 'result-btn result-btn-bad' : 'result-btn result-btn-ok'
}

/* ------------------------------------------------------------------ *
 * 加载与作答
 * ------------------------------------------------------------------ */

async function load() {
  if (!requireLogin()) return
  if (!subtaskId.value) {
    errorMsg.value = '缺少作业任务标识（subtaskId），请从任务详情页的「开始巡检」进入'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await api.fetchInspectionTemplate(orderType.value)
    template.value = (data && data.template) || []
    maxRemarkLength.value = (data && data.max_remark_length) || 200
    if (data && data.result_options && data.result_options.length) {
      resultOptions.value = data.result_options
    }
    // 按模板顺序分组：用 Map 保序，前后端的分类顺序保持一致（现场是照着纸质清单点的）
    const map = new Map()
    template.value.forEach((item) => {
      const key = item.group || '通用'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(item)
    })
    groups.value = Array.from(map.entries()).map(([name, items]) => ({ name, items }))
  } catch (err) {
    // 模板拿不到就一项都录不了，必须给出错误态 + 重试，不能让人对着空白页发呆
    errorMsg.value = errorText(err, '巡检项模板加载失败')
    template.value = []
    groups.value = []
  } finally {
    loading.value = false
  }
}

/** 点「正常 / 异常」 */
function chooseResult(name, result) {
  const current = answers.value[name] || { result: '', remark: '' }
  // 再点一次同一项 = 取消选择（现场点错了要能退回去，否则只能选一个不想要的）
  if (current.result === result) {
    const next = { ...answers.value }
    delete next[name]
    answers.value = next
    return
  }
  answers.value = { ...answers.value, [name]: { result, remark: current.remark || '' } }
}

/** 异常项备注（v-model）：先展开输入框再写内容，未作答的项不允许写备注 */
function updateRemark(name, value) {
  const current = answers.value[name]
  if (!current) return
  answers.value = { ...answers.value, [name]: { ...current, remark: value } }
}

/**
 * 一键全部正常。
 * ★ 现场绝大多数项本来就是正常的，一项项点十四下太慢；但这是批量覆盖操作，
 *   会把已勾的「异常」也改成正常，所以必须二次确认。
 */
function markAllNormal() {
  if (loading.value || !template.value.length) return
  const message = uncheckedCount.value
    ? `将把还没勾的 ${uncheckedCount.value} 项全部标为「正常」，已勾的异常项保持不变。`
    : '所有项都已经勾过了，确认把全部项目标为「正常」吗？'
  uni.showModal({
    title: '全部标为正常',
    content: message,
    confirmText: '确认',
    success: (res) => {
      if (!res.confirm) return
      const next = { ...answers.value }
      template.value.forEach((item) => {
        const current = next[item.name]
        if (!current) next[item.name] = { result: '正常', remark: '' }
      })
      answers.value = next
    },
  })
}

/** 清空作答（重新点一遍） */
function clearAll() {
  if (!checkedCount.value) return
  uni.showModal({
    title: '清空勾选',
    content: '将清空本页所有已勾选的巡检结果，照片与备注不受影响。',
    success: (res) => {
      if (res.confirm) answers.value = {}
    },
  })
}

/* ------------------------------------------------------------------ *
 * 到场签到 / 离店
 * ------------------------------------------------------------------ */

/**
 * 到场签到。
 * ★ 定位失败也要能签到：现场经常在地下室或信号死角，卡住签到等于卡住整个流程，
 *   所以先拿定位、拿不到就把 location 写成「已签到」并置 noLocation 标记，
 *   页面用 .hint-bar 如实告诉用户「本次不带坐标提交」。
 */
async function doCheckin() {
  uni.showLoading({ title: '定位中…', mask: true })
  try {
    const loc = await getLocationSafe()
    noLocation.value = !loc
    // ★ 时间戳一律走 nowClock()（本地时区）。
    //   曾经写成 formatTime(new Date().toISOString()) —— toISOString() 是 UTC，
    //   东八区下 09:21 签到会显示成「已签到 01:21」，现场会以为没记上。
    const signedAt = nowClock()
    checkin.value = loc
      ? {
          location: loc.address || '已签到',
          lng: loc.longitude ?? null,
          lat: loc.latitude ?? null,
          time: signedAt,
        }
      : { location: '已签到', lng: null, lat: null, time: signedAt }
    uni.hideLoading()
    uni.showToast({
      title: loc ? '已签到' : '已签到（未取到定位）',
      icon: 'none',
      duration: 2000,
    })
  } catch (err) {
    uni.hideLoading()
    uni.showToast({ title: errorText(err, '签到失败'), icon: 'none' })
  }
}

/* ------------------------------------------------------------------ *
 * 现场照片
 * ------------------------------------------------------------------ */

/** 选图并逐张上传 */
async function choosePhotos() {
  if (uploading.value) return
  const remain = MAX_PHOTOS - photos.value.length
  if (remain <= 0) {
    uni.showToast({ title: `最多上传 ${MAX_PHOTOS} 张`, icon: 'none' })
    return
  }
  uni.chooseImage({
    count: remain,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: async (res) => {
      const paths = res.tempFilePaths || []
      if (!paths.length) return
      uploading.value = true
      uploadProgress.value = { done: 0, total: paths.length }
      try {
        // 逐个上传，任何一张失败都不影响别的：失败的丢掉并提示，成功的照常进列表
        const results = await Promise.allSettled(
          paths.map((filePath, index) =>
            api
              .uploadImages({
                filePaths: [filePath],
                bizType: 'inspection',
                onProgress: () => {
                  uploadProgress.value = { done: index + 1, total: paths.length }
                },
              })
              .then((files) => ({ file: files[0], filePath })),
          ),
        )
        const ok = []
        const failed = []
        results.forEach((result) => {
          if (result.status === 'fulfilled' && result.value.file && result.value.file.url) {
            // 只留后端返回的相对路径：绝对地址交给 absoluteUrl 统一补，
            // 免得多存一份本地临时路径（临时路径过一会儿就失效了，误用会显示空白图）
            ok.push({ url: result.value.file.url })
          } else {
            failed.push(result.status === 'rejected' ? result.reason : null)
          }
        })
        if (ok.length) photos.value = photos.value.concat(ok)
        if (failed.length) {
          /*
           * 失败的图片**不进列表**（没有 URL 就没法提交），只提示。
           * 提示语优先用后端/网络给的原因，取不到就说明「重新选一次即可」——
           * 现场人员看到「N 张上传失败」+ 原因，才知道是重拍还是等信号。
           */
          const reason = failed[0] ? errorText(failed[0], '') : ''
          uni.showToast({
            title: reason
              ? `${failed.length} 张上传失败：${reason}`
              : `${failed.length} 张上传失败，请重新选择`,
            icon: 'none',
            duration: 3000,
          })
        }
      } finally {
        uploading.value = false
        uploadProgress.value = { done: 0, total: 0 }
      }
    },
  })
}

/** 删除一张（@click.stop 挡住外层预览，避免删图时顺手把大图弹出来） */
function removePhoto(index) {
  const next = photos.value.slice()
  next.splice(index, 1)
  photos.value = next
}

function previewPhotos(index) {
  if (!photos.value.length) return
  // ★ 预览必须用绝对地址（后端给的是 /static/... 相对路径，小程序端显示不出来）
  uni.previewImage({
    urls: photos.value.map((p) => api.absoluteUrl(p.url)),
    current: index,
  })
}

/* ------------------------------------------------------------------ *
 * 提交
 * ------------------------------------------------------------------ */

/** 组装已勾选的巡检项：没勾的项一律不传（后端会当成「没检查这一项」） */
function buildItems() {
  return template.value
    .filter((item) => answers.value[item.name])
    .map((item) => {
      const answer = answers.value[item.name]
      return {
        item_name: item.name,
        item_group: item.group || null,
        result: answer.result || resultOptions.value[0] || '正常',
        remark: answer.remark || '',
        images: [],
      }
    })
}

/**
 * 提交。
 * @param {boolean} finish true = 提交并完成（会结掉这个作业任务）
 */
async function submit(finish) {
  if (submitting.value) return
  const items = buildItems()
  if (!items.length) {
    uni.showToast({ title: '请至少完成一项巡检内容', icon: 'none', duration: 2500 })
    return
  }
  if (uploading.value) {
    uni.showToast({ title: '照片还在上传，请稍候', icon: 'none', duration: 2000 })
    return
  }

  submitting.value = true
  uni.showLoading({ title: finish ? '提交中…' : '保存中…', mask: true })
  try {
    /*
     * 离店打卡取「提交那一刻」的定位。
     * ★ 只对「已签到但这次填完就走」的场景取 —— 草稿不算离店（人还在现场，
     *   暂存之后还要接着录）；定位拿不到就传 null，服务端这两个字段可选。
     */
    let checkout = null
    if (checkin.value && finish) {
      const loc = await getLocationSafe()
      checkout = loc
        ? {
            location: loc.address || '离店',
            lng: loc.longitude ?? null,
            lat: loc.latitude ?? null,
          }
        : null
    }

    const res = await api.createInspection({
      subtaskId: subtaskId.value,
      items,
      images: photos.value.map((p) => p.url),
      remark: remark.value,
      checkin: checkin.value
        ? { location: checkin.value.location, lng: checkin.value.lng, lat: checkin.value.lat }
        : null,
      checkout,
      finish,
    })
    uni.hideLoading()
    uni.showToast({
      title: (res && res.message) || (finish ? '提交成功' : '已暂存草稿'),
      icon: 'none',
      duration: 2000,
    })
    /*
     * 成功后等 800ms 再返回：toast 还没显示完就跳页会被跳转动画吃掉，
     * 现场人员看不到「到底成没成」。回上一页（任务详情）后它的 onShow 会自动重拉状态。
     */
    setTimeout(() => {
      uni.navigateBack()
    }, 800)
  } catch (err) {
    uni.hideLoading()
    // ★ 失败必须留在原页：巡检项、照片、备注全部保留，改完直接重试
    uni.showModal({
      title: finish ? '提交未成功' : '暂存未成功',
      content: `${errorText(err, '提交失败')}（已填写的内容都还在，可检查网络后重试）`,
      showCancel: false,
      confirmText: '知道了',
    })
  } finally {
    submitting.value = false
  }
}

/** 提交并完成：会结掉作业任务，必须二次确认 */
function submitAndFinish() {
  if (submitting.value) return
  if (!checkedCount.value) {
    uni.showToast({ title: '请至少完成一项巡检内容', icon: 'none', duration: 2500 })
    return
  }
  uni.showModal({
    title: '提交并完成',
    content: `已检 ${checkedCount.value}/${totalCount.value} 项，异常 ${abnormalCount.value} 项。提交后本作业任务将结单，确定吗？`,
    confirmText: '提交完成',
    success: (res) => {
      if (res.confirm) submit(true)
    },
  })
}

/** 暂存草稿：不结单，稍后可以接着录 */
function saveDraft() {
  submit(false)
}

onLoad((options) => {
  // ★ 三个参数都走 safeDecode：各平台对 query 的解码次数不一致（H5 会多解一次），
  //   而且值里出现孤立 % 时 decodeURIComponent 会抛 URIError ——
  //   那是写在 onLoad 里的，一抛整页数据加载就断了（页面看着在、什么都点不动）。
  subtaskId.value = safeDecode(options && options.subtaskId)
  orderType.value = safeDecode(options && options.orderType) || '巡视'
  orderName.value = safeDecode(options && options.orderName)
  load()
})
</script>

<template>
  <view class="page page-with-footer">
    <!-- 是什么任务、按什么清单录，进来先说清楚 -->
    <view class="hint-bar">
      {{ orderName || '作业任务' }} · 巡检类型「{{ orderType }}」。
      到场先签到，再逐项点「正常 / 异常」，异常项请补一句说明并拍照。
    </view>

    <!-- 加载中 -->
    <view v-if="loading" class="empty">加载中…</view>

    <!-- 错误态 + 重试 -->
    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load()">重 试</button>
    </view>

    <template v-else>
      <!-- 到场签到：定位失败也能签，页面如实说明 -->
      <view class="card">
        <view class="checkin-row">
          <view class="checkin-info">
            <view class="checkin-title">
              {{ checkin ? `已签到 ${checkin.time}` : '到场签到' }}
            </view>
            <view class="checkin-loc">
              {{
                checkin
                  ? checkin.location
                  : '记录你到达站点的位置与时间（定位失败也能签到）'
              }}
            </view>
          </view>
          <button
            v-if="!checkin"
            class="btn btn-primary checkin-btn"
            @click="doCheckin"
          >
            到场签到
          </button>
          <view v-else class="checkin-done">✓</view>
        </view>
      </view>

      <!-- 如实告知没有坐标，避免事后对不上稽查口径 -->
      <view v-if="checkin && noLocation" class="hint-bar">
        未获取到定位，本次将以「已签到」提交，不带经纬度。
      </view>

      <!-- 进度 + 快捷操作 -->
      <view class="toolbar">
        <view class="progress-text">
          已检 {{ checkedCount }}/{{ totalCount }} ·
          <text :class="abnormalCount ? 'abnormal-text' : 'muted'">
            异常 {{ abnormalCount }} 项
          </text>
        </view>
        <view class="tool-actions">
          <view class="tool-btn" @click="markAllNormal">全部正常</view>
          <view class="tool-btn" @click="clearAll">清空</view>
        </view>
      </view>

      <!-- 分类巡检项 -->
      <view v-for="group in groups" :key="group.name" class="card">
        <view class="section-title">
          <text>{{ group.name }}</text>
          <text class="muted group-count">{{ group.items.length }} 项</text>
        </view>

        <view v-for="item in group.items" :key="item.name" class="item">
          <view class="item-head">
            <text class="item-name">{{ item.name }}</text>
            <view class="result-btns">
              <view
                v-for="option in resultOptions"
                :key="option"
                :class="resultBtnClass(item.name, option)"
                @click="chooseResult(item.name, option)"
              >
                {{ option }}
              </view>
            </view>
          </view>

          <!-- 判为异常才展开备注：正常项写备注没有意义，展开只会把清单拉长 -->
          <view v-if="showRemarkInput(item.name)" class="remark-box">
            <textarea
              class="form-textarea item-remark"
              :value="answers[item.name].remark"
              :maxlength="maxRemarkLength"
              :show-confirm-bar="true"
              placeholder="异常情况说明（现象、部位、影响）"
              @input="updateRemark(item.name, $event.detail.value)"
            />
            <view class="remark-count">
              {{ (answers[item.name].remark || '').length }}/{{ maxRemarkLength }}
            </view>
          </view>
        </view>
      </view>

      <!-- 现场照片 -->
      <view class="card">
        <view class="section-title">
          <text>现场照片</text>
          <text class="muted group-count">{{ photos.length }}/{{ MAX_PHOTOS }} 张</text>
        </view>

        <view class="image-grid">
          <view v-for="(photo, index) in photos" :key="photo.url" class="grid-cell">
            <!-- ★ src 走 absoluteUrl 补全；删除叉用 view + @click.stop，别用 button（会撑大格子） -->
            <image
              class="grid-img"
              :src="absoluteUrl(photo.url)"
              mode="aspectFill"
              @click="previewPhotos(index)"
            />
            <view class="grid-del" @click.stop="removePhoto(index)">×</view>
          </view>

          <view v-if="photos.length < MAX_PHOTOS" class="upload-add" @click="choosePhotos">
            <text class="upload-plus">+</text>
            <text>{{ uploading ? '上传中…' : '拍照 / 相册' }}</text>
          </view>
        </view>

        <view v-if="uploading" class="uploading-text">
          上传中 {{ uploadProgress.done }}/{{ uploadProgress.total }}…
        </view>
        <view class="desc">照片不是必填，但异常项建议拍一张；上传失败的不会计入，可重新选。</view>
      </view>

      <!-- 整单备注 -->
      <view class="card">
        <view class="section-title">
          <text>巡检备注</text>
          <text class="muted group-count">{{ remark.length }}/{{ maxRemarkLength }}</text>
        </view>
        <textarea
          v-model="remark"
          class="form-textarea"
          :maxlength="maxRemarkLength"
          :show-confirm-bar="true"
          placeholder="本次巡检的整体情况、需跟进事项（可不填）"
        />
      </view>
    </template>

    <!-- 底部操作条：暂存 vs 提交完成，后者会结单所以有二次确认 -->
    <view class="footer-bar">
      <button class="btn btn-plain" :disabled="submitting || loading" @click="saveDraft">
        暂存草稿
      </button>
      <button class="btn btn-primary" :disabled="submitting || loading" @click="submitAndFinish">
        {{ submitting ? '处理中…' : '提交并完成' }}
      </button>
    </view>
  </view>
</template>

<style scoped>
/* 签到行：左侧时间/位置 + 右侧按钮 */
.checkin-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
}

.checkin-info {
  flex: 1;
}

.checkin-title {
  font-size: 30rpx;
  font-weight: 600;
}

.checkin-loc {
  color: #8a9099;
  font-size: 23rpx;
  margin-top: 8rpx;
  line-height: 1.6;
  word-break: break-all;
}

.checkin-btn {
  flex-shrink: 0;
  font-size: 26rpx;
  line-height: 2.4;
  padding: 0 28rpx;
  margin: 0;
}

/* 已签到：绿色对勾，比再放一个禁用按钮更清楚 */
.checkin-done {
  color: #18a058;
  font-size: 48rpx;
  font-weight: 700;
  flex-shrink: 0;
  padding: 0 12rpx;
}

.progress-text {
  font-size: 26rpx;
}

.abnormal-text {
  color: #d03050;
  font-weight: 600;
}

.tool-actions {
  display: flex;
  gap: 16rpx;
}

.tool-btn {
  padding: 10rpx 24rpx;
  border-radius: 32rpx;
  background: #eef3fb;
  color: #1677ff;
  font-size: 24rpx;
}

.group-count {
  font-size: 22rpx;
  font-weight: 400;
}

/* 单个巡检项 */
.item {
  padding: 16rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}

.item:last-child {
  border-bottom: none;
}

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.item-name {
  flex: 1;
  font-size: 27rpx;
  line-height: 1.5;
}

.result-btns {
  display: flex;
  gap: 12rpx;
  flex-shrink: 0;
}

/* 默认未选：灰底；选中后由 result-btn-ok / result-btn-bad 覆盖 */
.result-btn {
  min-width: 96rpx;
  text-align: center;
  padding: 10rpx 0;
  border-radius: 10rpx;
  border: 1rpx solid #e6e8eb;
  color: #4b5563;
  font-size: 25rpx;
}

.result-btn-ok {
  background: #18a058;
  border-color: #18a058;
  color: #ffffff;
  font-weight: 600;
}

.result-btn-bad {
  background: #d03050;
  border-color: #d03050;
  color: #ffffff;
  font-weight: 600;
}

.remark-box {
  margin-top: 14rpx;
}

.item-remark {
  min-height: 130rpx;
}

.remark-count {
  text-align: right;
  color: #8a9099;
  font-size: 22rpx;
  margin-top: 6rpx;
}

/* 九宫格里的单格：图片 + 右上角删除叉 */
.grid-cell {
  position: relative;
  width: 180rpx;
  height: 180rpx;
}

.grid-del {
  position: absolute;
  top: -12rpx;
  right: -12rpx;
  width: 44rpx;
  height: 44rpx;
  line-height: 42rpx;
  text-align: center;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #ffffff;
  font-size: 30rpx;
  z-index: 2;
}

.uploading-text {
  color: #1677ff;
  font-size: 24rpx;
  margin-top: 12rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
