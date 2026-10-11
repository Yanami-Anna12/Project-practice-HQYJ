<script setup>
/**
 * 故障上报（现场核心动作：到桩前先拍照存证，再补文字说明）。
 *
 * ★ 从扫码页进来时带 pileId / stationId / projectId / assetCode：
 *   扫码的全部意义就是「不用再一层层选」，所以 onLoad 直接把桩、站点、项目定好；
 *   参数不全时（例如从消息里点进来只带了资产码）用资产码反查一次，
 *   反查失败也只是退回手动选择，不会把页面卡住。
 *
 * ★ 草稿与正式上报是同一个接口，只有 is_draft 不同：
 *   现场经常是先拍张照存着、回办公室再补文字，所以草稿的必填项必须比正式上报低
 *   （正式上报要求 项目 / 站点 / 故障类型 / 描述 四项，草稿只要求「类型或描述有一项」）。
 *
 * ★ 故障等级允许留空：不选时后端按描述关键词硬约束判定（含「起火 / 漏电 / 跳闸」等），
 *   页面只负责把这条规则说清楚，不复刻到前端，否则规则一改两端就打架。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'

import * as api from '@/api'
import {
  faultLevelClass,
  getLocationSafe,
  locationText,
  percentText,
  safeDecode,
  today,
} from '@/utils/format'
import { errorText, requireLogin } from '@/utils/ui'

/** 现场最常见的故障类型（实测口径）：点一下比打字快，也让后端的类型口径统一 */
const FAULT_TYPES = [
  '充电枪故障',
  '功率模块故障',
  '通信故障',
  '计费异常',
  '刷卡模块故障',
  '屏幕显示异常',
  '急停按钮异常',
  '绝缘监测报警',
]
/** 字典拿不到时的等级兜底：后端 FaultLevel 就是这三档 */
const FALLBACK_LEVELS = ['一般', '严重', '危急']
/** 字典拿不到时的 SLA 兜底：与后端 LEVEL_SLA_HOURS.get(level, 72) 一致 */
const FALLBACK_SLA_HOURS = 72
/** 与网页端「故障上报」同一个图片上限，保持两端体验一致 */
const MAX_IMAGES = 6
/** 后端 fault 描述按 500 字限制（网页端同样 500） */
const MAX_DESC = 500
/** 桩是可选字段：整站级 / 通信层故障不属于某个具体的桩 */
const NO_PILE = '不指定（整站 / 通信类故障）'

/* ---------------- 基础数据 ---------------- */
const loading = ref(true)
const baseError = ref('')
const projects = ref([])
const stations = ref([])
const levels = ref(FALLBACK_LEVELS)
const slaHours = ref({})
/** onLoad 带来的参数：基础数据加载失败后重试要复用，不然「自动带出」会丢 */
let presetParams = { pileId: '', stationId: '', projectId: '', assetCode: '' }

/* ---------------- 表单 ---------------- */
const projectId = ref('')
const stationId = ref('')
const pileId = ref('')
/** 扫码带出的资产码：桩下拉的选项还没拉回来时用它显示，免得用户以为没带出来 */
const presetAssetCode = ref('')
const faultType = ref('')
const faultLevel = ref('')
const description = ref('')
const occurredDate = ref(today())
const occurredTime = ref(currentClock())
const images = ref([])
const piles = ref([])
const pileLoading = ref(false)

/* ---------------- 定位 ---------------- */
const locInfo = ref(null)
const locating = ref(false)

/* ---------------- 上传 / 提交 ---------------- */
const uploading = ref(false)
const uploadProgress = ref({ done: 0, total: 0 })
const submitting = ref(false)

/* ---------------- AI ---------------- */
const aiLoading = ref(false)
const aiResult = ref(null)

/** 当前时间 HH:mm（发生时间默认值） */
function currentClock() {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

/*
 * 下面三个 picker 都用「选项数组 + 用 id 反查下标」的方式：
 * 选中的真相是 id，不是下标。这样切换项目导致站点列表变化、
 * 或者扫码带出的桩还没出现在选项里时，都不会出现「下标指向了别的站点」这种脏选择。
 */
const projectChoices = computed(() => [
  { id: '', label: '请选择所属项目' },
  ...projects.value.map((p) => ({ id: p.id, label: p.name })),
])
const projectIndex = computed(() =>
  Math.max(0, projectChoices.value.findIndex((c) => c.id === projectId.value))
)
const projectLabel = computed(
  () => (projectChoices.value[projectIndex.value] || {}).label || '请选择所属项目'
)

/** 站点按已选项目过滤；还没选项目时给全部（现场常先按站点找） */
const stationList = computed(() =>
  projectId.value ? stations.value.filter((s) => s.project_id === projectId.value) : stations.value
)
const stationChoices = computed(() => [
  { id: '', label: projectId.value ? '请选择所属站点' : '请先选择所属项目' },
  ...stationList.value.map((s) => ({ id: s.id, label: s.name })),
])
const stationIndex = computed(() =>
  Math.max(0, stationChoices.value.findIndex((c) => c.id === stationId.value))
)
const stationLabel = computed(
  () => (stationChoices.value[stationIndex.value] || {}).label || '请选择所属站点'
)

const pileChoices = computed(() => [
  { id: '', label: NO_PILE },
  ...piles.value.map((p) => ({ id: p.id, label: `${p.asset_code} · ${p.name}` })),
])
const pileIndex = computed(() =>
  Math.max(0, pileChoices.value.findIndex((c) => c.id === pileId.value))
)
const pileLabel = computed(() => {
  const hit = pileChoices.value[pileIndex.value]
  if (hit && hit.id) return hit.label
  if (pileId.value) return `${presetAssetCode.value || '已选充电桩'} · 已从扫码带出`
  return NO_PILE
})

/** 等级 chip：带上 SLA 小时数，选之前就知道响应时限在哪 */
const levelChips = computed(() =>
  levels.value.map((name) => ({ name, hours: slaHours.value[name] || FALLBACK_SLA_HOURS }))
)

/**
 * 提交时拼在描述开头的位置前缀。
 * ★ 不去改 textarea 里的正文：现场会反复点「获取当前位置」，
 *   直接往正文前面插会叠出好几段前缀，正文也被人改得不像自己写的。
 */
const locationPrefix = computed(() => {
  const loc = locInfo.value
  if (!loc) return ''
  const text = loc.address || `${loc.latitude}, ${loc.longitude}`
  return `【位置】${text} `
})

/**
 * AI 建议等级。
 * ★ 后端的规则引擎只给「根因类别 / 检查项 / 处置措施 / SLA」，等级是硬约束
 *   （create_fault 里按描述关键词判定）。所以这里做兼容读取：报文里真带了等级建议就显示
 *   「采纳该等级」，没带就不显示一个点不动的按钮 —— 前端**不复刻**等级规则。
 */
const aiSuggestedLevel = computed(() => {
  const diagnosis = aiResult.value
  if (!diagnosis) return ''
  const candidate =
    diagnosis.suggested_level ||
    diagnosis.level_suggestion ||
    diagnosis.ai_level_suggestion ||
    diagnosis.fault_level ||
    ''
  return levels.value.indexOf(candidate) >= 0 ? candidate : ''
})

/** 分析方式：有 LLM 分析就是 RAG + LLM，否则是后端自动降级后的规则引擎结果 */
const aiMethodText = computed(() =>
  aiResult.value && aiResult.value.llm_analysis ? 'RAG + LLM' : '规则引擎（未配 LLM Key 时自动降级）'
)

/** 加载项目 / 站点 / 字典，并把 onLoad 的参数落到表单上 */
async function loadBase() {
  loading.value = true
  baseError.value = ''
  try {
    const [projectRows, stationRows, dicts] = await Promise.all([
      api.fetchProjects(),
      api.fetchStationOptions(),
      api.fetchFaultDicts(),
    ])
    projects.value = projectRows || []
    stations.value = stationRows || []
    if (dicts && (dicts.levels || []).length) levels.value = dicts.levels
    slaHours.value = (dicts && dicts.level_sla_hours) || {}
    await applyPreset()
  } catch (err) {
    // 基础数据拿不到就没法选项目/站点，整页给错误态 + 重试，不留白屏
    baseError.value = errorText(err, '项目 / 站点加载失败')
  } finally {
    loading.value = false
  }
}

/** 把 onLoad 的参数落到表单 */
async function applyPreset() {
  const { pileId: pid, stationId: sid, projectId: projId, assetCode } = presetParams
  if (projId) projectId.value = projId
  if (sid) stationId.value = sid
  if (pid) pileId.value = pid
  if (assetCode) presetAssetCode.value = assetCode
  if (stationId.value) await loadPiles()
  if (!pileId.value && assetCode) await resolveByAssetCode(assetCode)
}

/** 只有资产码时反查充电桩，效果与扫码带 pileId 一样：进来就已经选好 */
async function resolveByAssetCode(assetCode) {
  try {
    const list = await api.fetchPileOptions({ keyword: assetCode })
    const hit = (list || []).find((p) => p.asset_code === assetCode) || (list || [])[0]
    if (!hit) return
    pileId.value = hit.id
    presetAssetCode.value = hit.asset_code
    if (!stationId.value) stationId.value = hit.station_id || ''
    if (!projectId.value && stationId.value) {
      const station = stations.value.find((s) => s.id === stationId.value)
      if (station) projectId.value = station.project_id || ''
    }
    await loadPiles()
  } catch (err) {
    // 反查失败只是少省一步操作，用户仍可自己选，所以只记日志不打断
    console.warn('[fault-report] 资产码反查充电桩失败', err)
  }
}

/** 桩下拉：按项目 + 站点联动 */
async function loadPiles() {
  if (!stationId.value) {
    piles.value = []
    return
  }
  pileLoading.value = true
  try {
    piles.value =
      (await api.fetchPileOptions({
        projectId: projectId.value,
        stationId: stationId.value,
      })) || []
  } catch (err) {
    // 桩列表拉不到不能挡住上报：整站级故障本来就不需要选桩
    piles.value = []
    uni.showToast({ title: '充电桩列表加载失败，可不选桩直接上报', icon: 'none', duration: 2500 })
  } finally {
    pileLoading.value = false
  }
}

function onProjectChange(e) {
  // ★ picker 的 e.detail.value 是**下标**，不是选项值，所以要按下标取回对象再拿 id
  projectId.value = (projectChoices.value[Number(e.detail.value)] || {}).id || ''
  // 项目换了站点就不一定还适用：连带清空站点与桩，避免提交出「项目 A ＋ 站点 B」的脏数据
  stationId.value = ''
  pileId.value = ''
  piles.value = []
}

function onStationChange(e) {
  stationId.value = (stationChoices.value[Number(e.detail.value)] || {}).id || ''
  pileId.value = ''
  loadPiles()
}

function onPileChange(e) {
  pileId.value = (pileChoices.value[Number(e.detail.value)] || {}).id || ''
  const hit = piles.value.find((p) => p.id === pileId.value)
  presetAssetCode.value = hit ? hit.asset_code : ''
}

function pickType(name) {
  faultType.value = name
}

/** 再点一次取消：等级允许留空，留空由后端按描述自动判定 */
function pickLevel(name) {
  faultLevel.value = faultLevel.value === name ? '' : name
}

function onDateChange(e) {
  occurredDate.value = e.detail.value
}

function onTimeChange(e) {
  occurredTime.value = e.detail.value
}

/** 取当前定位（拿不到也要能提交，见下方提示文案） */
async function fetchLocation() {
  if (locating.value) return
  locating.value = true
  try {
    const loc = await getLocationSafe()
    if (!loc) {
      // 地下室、配电房、信号差的位置很常见，定位失败绝不能变成提交阻塞
      uni.showToast({ title: '未获取到定位，不影响提交', icon: 'none', duration: 2500 })
      return
    }
    locInfo.value = loc
    uni.showToast({ title: '已获取当前位置', icon: 'success' })
  } finally {
    locating.value = false
  }
}

/** 选图 + 逐张上传（上传中的进度由 uploadImages 的 onProgress 回调给） */
async function chooseImages() {
  if (uploading.value) return
  if (images.value.length >= MAX_IMAGES) {
    uni.showToast({ title: `最多 ${MAX_IMAGES} 张照片`, icon: 'none' })
    return
  }
  const picked = await new Promise((resolve) => {
    uni.chooseImage({
      count: MAX_IMAGES - images.value.length,
      // 手机原图常常 5-10MB，弱网下必须压缩后再传
      sizeType: ['compressed'],
      sourceType: ['camera', 'album'],
      success: (res) => resolve(res.tempFilePaths || []),
      fail: () => resolve([]),
    })
  })
  if (!picked.length) return

  uploading.value = true
  uploadProgress.value = { done: 0, total: picked.length }
  try {
    const files = await api.uploadImages({
      filePaths: picked,
      bizType: 'fault',
      onProgress: (done, total) => {
        uploadProgress.value = { done, total }
      },
    })
    files.forEach((file) => {
      // url 补全前缀用于显示；rawUrl 是相对路径，提交时给后端存
      images.value.push({ url: api.absoluteUrl(file.url), rawUrl: file.url })
    })
  } catch (err) {
    // 逐张传但整批回滚：api.uploadImages 失败就抛出，拿不到已成功的那几张，所以这里只能重选。
    // 后端是按张落盘的，重传只是多留一份附件，故障单只认下面 images 里的 URL，不会污染数据。
    uni.showModal({
      title: '照片上传失败',
      content: `第 ${uploadProgress.value.done + 1} 张没传上去：${errorText(err, '请检查网络后重试')}`,
      showCancel: false,
      confirmText: '知道了',
    })
  } finally {
    uploading.value = false
    uploadProgress.value = { done: 0, total: 0 }
  }
}

function removeImage(index) {
  images.value.splice(index, 1)
}

function previewImage(index) {
  const urls = images.value.map((item) => item.url)
  uni.previewImage({ urls, current: urls[index] })
}

/** AI 辅助诊断：类型或描述至少有一项才问得动后端 */
async function runAi() {
  if (aiLoading.value) return
  if (!faultType.value.trim() && !description.value.trim()) {
    // 后端在既没有 fault_id、也没有类型/描述时会直接报错，先拦一次省一个来回
    uni.showToast({ title: '先写点现象，AI 才有得判断', icon: 'none', duration: 2500 })
    return
  }
  aiLoading.value = true
  try {
    const res = await api.aiDiagnoseFault({
      faultType: faultType.value.trim(),
      faultLevel: faultLevel.value,
      description: description.value.trim(),
      pileAssetCode: presetAssetCode.value,
      stationId: stationId.value,
    })
    aiResult.value = (res.data && res.data.diagnosis) || null
    if (!aiResult.value) {
      uni.showToast({ title: 'AI 没有返回内容，可继续手动上报', icon: 'none', duration: 2500 })
    }
  } catch (err) {
    // AI 只是辅助：它不可用不影响上报，所以用弹窗告知、不占用错误态
    uni.showModal({
      title: 'AI 诊断失败',
      content: errorText(err, 'AI 暂时不可用，可继续手动上报'),
      showCancel: false,
      confirmText: '知道了',
    })
  } finally {
    aiLoading.value = false
  }
}

/** 采纳 AI 建议的等级 */
function adoptLevel() {
  if (!aiSuggestedLevel.value) return
  faultLevel.value = aiSuggestedLevel.value
  uni.showToast({ title: `已采用「${aiSuggestedLevel.value}」`, icon: 'none' })
}

/** 提交用的描述：位置前缀拼在最前面 */
function buildDescription() {
  return `${locationPrefix.value}${description.value.trim()}`.trim()
}

/**
 * 提交。
 * @param {boolean} isDraft true = 保存草稿（门槛低），false = 正式上报（四项必填）
 */
async function submit(isDraft) {
  if (submitting.value) return
  if (uploading.value) {
    uni.showToast({ title: '照片还在上传，请稍候', icon: 'none' })
    return
  }

  const type = faultType.value.trim()
  const desc = description.value.trim()
  if (isDraft) {
    // 草稿只要求「有内容」：现场先拍个照存着是常态
    if (!type && !desc) {
      uni.showToast({ title: '草稿也要留点信息：故障类型或描述填一项', icon: 'none', duration: 2500 })
      return
    }
  } else {
    if (!projectId.value) {
      uni.showToast({ title: '请选择所属项目', icon: 'none' })
      return
    }
    if (!stationId.value) {
      uni.showToast({ title: '请选择所属站点', icon: 'none' })
      return
    }
    if (!type) {
      uni.showToast({ title: '请选择或填写故障类型', icon: 'none' })
      return
    }
    if (!desc) {
      uni.showToast({ title: '请填写故障描述', icon: 'none' })
      return
    }
  }

  submitting.value = true
  uni.showLoading({ title: isDraft ? '保存中…' : '上报中…', mask: true })
  try {
    const res = await api.reportFault({
      projectId: projectId.value,
      stationId: stationId.value,
      pileId: pileId.value,
      faultType: type,
      // 留空 = 交给后端按描述关键词判定等级与 SLA
      faultLevel: faultLevel.value,
      description: buildDescription(),
      // ★ 传相对路径：后端存的就是它，页面显示时再用 absoluteUrl 补前缀
      images: images.value.map((item) => item.rawUrl),
      occurredAt: `${occurredDate.value} ${occurredTime.value}:00`,
      isDraft,
    })
    uni.hideLoading()
    // toast 后端原话：「故障上报成功，等待核查」/「故障草稿已保存」
    uni.showToast({
      title: res.message || (isDraft ? '草稿已保存' : '上报成功'),
      icon: 'success',
      duration: 2000,
    })
    // ★ 成功后 submitting 保持 true 直到返回上一页：
    //   这 900ms 里按钮若恢复可点，现场连点两下就会重复建两条故障单。
    await new Promise((resolve) => setTimeout(resolve, 900))
    uni.navigateBack({
      fail: () => {
        // 栈里没有上一页（H5 直接输 URL 进来）时退回故障列表，否则会停在一个按钮点不动的页面上
        submitting.value = false
        uni.redirectTo({ url: '/pages/fault/index' })
      },
    })
  } catch (err) {
    uni.hideLoading()
    submitting.value = false
    // 失败留在原地、表单数据全保留（现场重填一遍成本很高），把后端原话弹出来
    uni.showModal({
      title: isDraft ? '草稿保存失败' : '上报失败',
      content: errorText(err),
      showCancel: false,
      confirmText: '知道了',
    })
  }
}

onLoad((options) => {
  if (!requireLogin()) return
  presetParams = {
    pileId: options?.pileId || '',
    stationId: options?.stationId || '',
    projectId: options?.projectId || '',
    // 资产码可能带中文/特殊字符，跳转前做了 encodeURIComponent；
    // 用 safeDecode 而不是裸 decodeURIComponent：各平台解码次数不一致，且裸解会抛 URIError
    assetCode: safeDecode(options?.assetCode),
  }
  loadBase()
})
</script>

<template>
  <view class="page page-with-footer">
    <view class="hint-bar">
      项目、站点、故障类型、描述四项必填；<text class="strong">故障等级可以不选</text> ——
      不选时后端按描述里的关键词（起火 / 漏电 / 跳闸 / 无法充电 等）自动判定等级与响应时限。
    </view>

    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="baseError" class="error-box">
      <view class="error-text">{{ baseError }}</view>
      <button class="btn btn-primary retry-btn" @click="loadBase">重 试</button>
    </view>

    <view v-else>
      <!-- 位置：项目 → 站点 → 桩 三级联动 -->
      <view class="card">
        <view class="form-item">
          <view class="form-label form-label-required">所属项目</view>
          <picker
            :range="projectChoices"
            range-key="label"
            :value="projectIndex"
            @change="onProjectChange"
          >
            <view class="form-picker">
              <text :class="projectId ? '' : 'muted'">{{ projectLabel }}</text>
              <text class="picker-arrow">▾</text>
            </view>
          </picker>
        </view>

        <view class="form-item">
          <view class="form-label form-label-required">所属站点</view>
          <picker
            :range="stationChoices"
            range-key="label"
            :value="stationIndex"
            @change="onStationChange"
          >
            <view class="form-picker">
              <text :class="stationId ? '' : 'muted'">{{ stationLabel }}</text>
              <text class="picker-arrow">▾</text>
            </view>
          </picker>
        </view>

        <view class="form-item">
          <view class="form-label">充电桩资产码（可不选）</view>
          <picker :range="pileChoices" range-key="label" :value="pileIndex" @change="onPileChange">
            <view class="form-picker">
              <text :class="pileId ? '' : 'muted'">
                {{ pileLoading ? '充电桩加载中…' : pileLabel }}
              </text>
              <text class="picker-arrow">▾</text>
            </view>
          </picker>
          <view class="desc">
            整站级或通信层的问题（全站离线、平台与电表对不上账等）不属于某个具体的桩，留空即可。
          </view>
        </view>
      </view>

      <!-- 故障信息 -->
      <view class="card">
        <view class="form-item">
          <view class="form-label form-label-required">故障类型</view>
          <view class="chip-row">
            <view
              v-for="item in FAULT_TYPES"
              :key="item"
              class="chip"
              :class="faultType === item ? 'chip-active' : ''"
              @click="pickType(item)"
            >
              {{ item }}
            </view>
          </view>
          <input
            v-model="faultType"
            class="form-input"
            type="text"
            maxlength="64"
            placeholder="也可以直接输入，例如：枪线破损"
          />
          <view class="desc">上面的常用类型点一下就填进来；不在列表里的直接写在输入框，两处是同一个值。</view>
        </view>

        <view class="form-item">
          <view class="form-label">故障等级（不选则系统按描述自动判定）</view>
          <view class="chip-row">
            <view
              v-for="item in levelChips"
              :key="item.name"
              class="chip"
              :class="faultLevel === item.name ? 'chip-active' : ''"
              @click="pickLevel(item.name)"
            >
              {{ item.name }} · SLA {{ item.hours }}h
            </view>
          </view>
          <view class="desc">再点一次可取消选择；响应时限：危急 4h / 严重 24h / 一般 72h。</view>
        </view>

        <view class="form-item">
          <view class="form-label">发生时间</view>
          <view class="time-row">
            <view class="time-cell">
              <picker mode="date" :value="occurredDate" @change="onDateChange">
                <view class="form-picker">
                  <text>{{ occurredDate }}</text>
                  <text class="picker-arrow">▾</text>
                </view>
              </picker>
            </view>
            <view class="time-cell">
              <picker mode="time" :value="occurredTime" @change="onTimeChange">
                <view class="form-picker">
                  <text>{{ occurredTime }}</text>
                  <text class="picker-arrow">▾</text>
                </view>
              </picker>
            </view>
          </view>
          <view class="desc">默认当前时间；先发现、后补录时改成实际发生的时间。</view>
        </view>
      </view>

      <!-- 描述 -->
      <view class="card">
        <view class="form-item">
          <view class="form-label form-label-required">故障描述</view>
          <textarea
            v-model="description"
            class="form-textarea"
            :maxlength="MAX_DESC"
            placeholder="写清现象与现场判断，例如：3 号枪插枪后无输出，屏幕提示绝缘故障。含「起火、漏电、跳闸、无法充电」等关键词时系统会自动建议等级"
          />
          <view class="desc">{{ description.length }}/{{ MAX_DESC }}</view>
        </view>
      </view>

      <!-- 现场照片 -->
      <view class="card">
        <view class="section-title">
          <text>现场照片</text>
          <text class="muted">{{ images.length }}/{{ MAX_IMAGES }}</text>
        </view>
        <view class="image-grid">
          <view v-for="(img, index) in images" :key="img.rawUrl" class="img-wrap">
            <image class="grid-img" :src="img.url" mode="aspectFill" @click="previewImage(index)" />
            <view class="img-del" @click="removeImage(index)">×</view>
          </view>
          <view v-if="images.length < MAX_IMAGES" class="upload-add" @click="chooseImages">
            <text class="upload-plus">＋</text>
            <text>{{ uploading ? '上传中…' : '拍照/选图' }}</text>
          </view>
        </view>
        <view v-if="uploading" class="desc">
          正在上传第 {{ uploadProgress.done + 1 }}/{{ uploadProgress.total }} 张，传完再提交
        </view>
      </view>

      <!-- 发生位置 -->
      <view class="card">
        <view class="section-title">
          <text>发生位置</text>
        </view>
        <view class="loc-row">
          <button class="btn btn-default loc-btn" :disabled="locating" @click="fetchLocation">
            {{ locating ? '定位中…' : '获取当前位置' }}
          </button>
          <text v-if="locInfo" class="loc-value">{{ locationText(locInfo) }}</text>
          <text v-else class="muted">没定位也能提交，只是描述里不带位置</text>
        </view>
        <view v-if="locationPrefix" class="loc-note">提交时会拼到描述开头：{{ locationPrefix }}</view>
      </view>

      <!-- AI 辅助诊断 -->
      <view class="card">
        <view class="section-title">
          <text>AI 辅助诊断</text>
        </view>
        <button class="btn btn-default" :disabled="aiLoading" @click="runAi">
          {{ aiLoading ? 'AI 分析中…' : 'AI 先看看（根因 / 检查项 / 处置建议）' }}
        </button>
        <view class="desc">先写点现象；没配 LLM Key 时后端会自动降级为规则引擎，同样会给结果。</view>
      </view>

      <view v-if="aiResult" class="card">
        <view class="section-title">
          <text>AI 诊断结果</text>
          <text class="tag tag-running">{{ aiMethodText }}</text>
        </view>
        <view class="row">
          <text class="row-label">根因类别</text>
          <text class="row-value">{{ aiResult.matched_category || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">置信度</text>
          <text class="row-value">{{ percentText((aiResult.confidence || 0) * 100) }}</text>
        </view>
        <view class="row">
          <text class="row-label">SLA 时限</text>
          <text class="row-value">{{ aiResult.sla_hours || FALLBACK_SLA_HOURS }} 小时</text>
        </view>
        <view v-if="aiSuggestedLevel" class="row">
          <text class="row-label">建议等级</text>
          <text class="row-value">
            <text class="tag" :class="faultLevelClass(aiSuggestedLevel)">{{ aiSuggestedLevel }}</text>
            <text class="adopt-link" @click="adoptLevel">采纳该等级</text>
          </text>
        </view>

        <view v-if="(aiResult.possible_causes || []).length" class="ai-block">
          <view class="ai-block-title">可能根因（按可能性排序）</view>
          <view v-for="(cause, index) in aiResult.possible_causes" :key="index" class="ai-item">
            {{ index + 1 }}. {{ cause }}
          </view>
        </view>
        <view v-if="(aiResult.checks || []).length" class="ai-block">
          <view class="ai-block-title">现场检查项</view>
          <view v-for="(check, index) in aiResult.checks" :key="index" class="ai-item">· {{ check }}</view>
        </view>
        <view v-if="(aiResult.actions || []).length" class="ai-block">
          <view class="ai-block-title">建议处置措施</view>
          <view v-for="(action, index) in aiResult.actions" :key="index" class="ai-item">· {{ action }}</view>
        </view>
        <view v-if="aiResult.llm_analysis" class="ai-block">
          <view class="ai-block-title">LLM 深度分析</view>
          <view class="ai-llm">{{ aiResult.llm_analysis }}</view>
        </view>
      </view>
    </view>

    <view class="footer-bar">
      <button class="btn btn-plain" :disabled="submitting || uploading" @click="submit(true)">
        保存草稿
      </button>
      <button class="btn btn-primary" :disabled="submitting || uploading" @click="submit(false)">
        {{ submitting ? '提交中…' : '确认上报' }}
      </button>
    </view>
  </view>
</template>

<style scoped>
.time-row {
  display: flex;
  gap: 16rpx;
}

.time-cell {
  flex: 1;
}

.loc-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.loc-btn {
  flex-shrink: 0;
  margin: 0;
  padding: 0 24rpx;
  font-size: 26rpx;
  line-height: 2.4;
}

.loc-value {
  flex: 1;
  font-size: 25rpx;
  color: #4b5563;
}

.loc-note {
  margin-top: 12rpx;
  font-size: 23rpx;
  color: #8a9099;
}

/* 图片右上角的删除角标：现场误选一张要能马上去掉 */
.img-wrap {
  position: relative;
  width: 180rpx;
  height: 180rpx;
}

.img-del {
  position: absolute;
  top: -12rpx;
  right: -12rpx;
  width: 44rpx;
  height: 44rpx;
  line-height: 40rpx;
  text-align: center;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #ffffff;
  font-size: 32rpx;
}

.ai-block {
  margin-top: 18rpx;
}

.ai-block-title {
  font-size: 26rpx;
  font-weight: 600;
  margin-bottom: 8rpx;
}

.ai-item {
  font-size: 25rpx;
  color: #4b5563;
  line-height: 1.7;
}

.ai-llm {
  font-size: 25rpx;
  color: #3d5a80;
  line-height: 1.7;
  white-space: pre-wrap;
}

.adopt-link {
  color: #1677ff;
  font-size: 25rpx;
  margin-left: 16rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
