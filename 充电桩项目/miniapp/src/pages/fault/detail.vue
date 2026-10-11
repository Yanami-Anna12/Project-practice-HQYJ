<script setup>
/**
 * 故障详情 + 核查。
 *
 * 数据源：GET /faults/{id} → { fault, verifications, station, pile, sla_hours, permissions }
 *
 * ★ 权限判断顺序（两段都要过才显示核查入口）：
 *   1) 后端在详情里算好的 permissions.can_verify —— 它按**故障状态**判断（待核查/核查驳回才可核查）；
 *   2) 账号自身的权限点 fault:verify（accountProfile().canVerifyFault）。
 *   后端已经会拦（403），前端先判一次是为了不把按不动的按钮摆给运维人员看。
 *
 * ★ 详情接口只给 sla_hours（数字），SLA 截止时间要自己折算：
 *   上报时间优先、没有就用创建时间，与后端 fault_card_list 的公式一致；
 *   折算出来的字符串再交给 utils/format.js 的 isSlaOverdue() 判定，超期只有一个判定入口。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'

import * as api from '@/api'
import {
  faultLevelClass,
  faultStatusClass,
  formatDateTime,
  isSlaOverdue,
  percentText,
} from '@/utils/format'
import { accountProfile, errorText, requireLogin } from '@/utils/ui'

/** 字典拿不到时的等级兜底：后端 FaultLevel 就是这三档 */
const FALLBACK_LEVELS = ['一般', '严重', '危急']
/** 字典拿不到时的核查结论兜底：后端 VerifyResult 就是这两档 */
const FALLBACK_VERIFY_RESULTS = ['核查通过', '核查驳回']
/** 与后端 LEVEL_SLA_HOURS.get(level, 72) 一致的默认值 */
const FALLBACK_SLA_HOURS = 72
const MAX_VERIFY_IMAGES = 6
const MAX_VERIFY_DESC = 500
/** 草稿态：只有这个状态才有「确认上报」动作（与后端 permissions.can_confirm 同一口径） */
const DRAFT_STATUS = '待上报'

/* ---------------- 详情 ---------------- */
const faultId = ref('')
const fault = ref(null)
const verifications = ref([])
const station = ref(null)
const pile = ref(null)
const slaHours = ref(FALLBACK_SLA_HOURS)
const permissions = ref({ can_verify: false, can_confirm: false })
const loading = ref(true)
const errorMsg = ref('')

/* ---------------- 字典（核查选项） ---------------- */
const levels = ref(FALLBACK_LEVELS)
const verifyResults = ref(FALLBACK_VERIFY_RESULTS)
const slaHoursMap = ref({})

/* ---------------- 核查表单 ---------------- */
const showVerify = ref(false)
const verifyStatus = ref(FALLBACK_VERIFY_RESULTS[0])
const verifyLevel = ref('')
const verifyDesc = ref('')
const verifyImages = ref([])
const needDefectOrder = ref(false)
const verifySubmitting = ref(false)
const verifyUploading = ref(false)
const verifyProgress = ref({ done: 0, total: 0 })

/* ---------------- 确认上报 / AI ---------------- */
const confirming = ref(false)
const aiLoading = ref(false)
const aiResult = ref(null)

const canConfirm = computed(
  () => !!fault.value && fault.value.status === DRAFT_STATUS && !!permissions.value.can_confirm
)
const canVerify = computed(() => !!permissions.value.can_verify && accountProfile().canVerifyFault)
/** 有没有底部动作按钮：决定根节点要不要留出 footer 的高度 */
const hasActions = computed(() => canConfirm.value || canVerify.value)

/** 现场照片：后端给的是 /static/... 相对路径，必须补全前缀，微信端否则是空白图 */
const faultImages = computed(() => api.absoluteUrls(fault.value && fault.value.images))
/** 核查表单里已上传照片的绝对地址（预览用） */
const verifyImageUrls = computed(() => verifyImages.value.map((item) => item.url))

/** 分析方式：有 LLM 分析就是 RAG + LLM，否则是后端自动降级后的规则引擎结果 */
const aiMethodText = computed(() =>
  aiResult.value && aiResult.value.llm_analysis ? 'RAG + LLM' : '规则引擎（未配 LLM Key 时自动降级）'
)

function pad(n) {
  return String(n).padStart(2, '0')
}

/**
 * 解析后端时间。
 * ★ 手动拆年月日构造，不用 new Date('YYYY-MM-DD HH:mm:ss')：iOS 对该格式解析不一致，
 *   而这个时间要参与「是否超 SLA」的判断，差 8 小时就会误报。
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

/** SLA 截止时间 = 上报时间（或创建时间）＋ 等级 SLA 小时 */
const slaDeadline = computed(() => {
  if (!fault.value) return ''
  const base = parseDateTime(fault.value.reported_at || fault.value.created_at)
  if (!base) return ''
  const hours = Number(slaHours.value) || FALLBACK_SLA_HOURS
  const deadline = new Date(base.getTime() + hours * 3600 * 1000)
  return (
    `${deadline.getFullYear()}-${pad(deadline.getMonth() + 1)}-${pad(deadline.getDate())} ` +
    `${pad(deadline.getHours())}:${pad(deadline.getMinutes())}`
  )
})

/** 是否超期：判定入口只有 isSlaOverdue，页内不另写超期规则 */
const slaOverdue = computed(() => isSlaOverdue({ ...(fault.value || {}), sla_deadline: slaDeadline.value }))

/** 等级 chip 文案：带 SLA 小时数 */
function levelChipText(name) {
  return `${name} ${slaHoursMap.value[name] || FALLBACK_SLA_HOURS}h`
}

/** 某条核查记录里的照片（绝对地址） */
function verifyImagesOf(item) {
  return api.absoluteUrls(item && item.images)
}

/** 通用放大预览：详情照片与核查照片共用一个入口，省两套代码 */
function previewImages(urls, index) {
  if (!urls || !urls.length) return
  uni.previewImage({ urls, current: urls[index] })
}

/** 详情主加载 */
async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const data = (await api.fetchFault(faultId.value)) || {}
    fault.value = data.fault || null
    verifications.value = data.verifications || []
    station.value = data.station || null
    pile.value = data.pile || null
    slaHours.value = Number(data.sla_hours) || FALLBACK_SLA_HOURS
    permissions.value = data.permissions || { can_verify: false, can_confirm: false }

    // 核查等级默认带出故障本身的等级：核查多数是复核，不改等级就不用动手选
    if (!verifyLevel.value && fault.value) verifyLevel.value = fault.value.fault_level
    // 后端会把上一次的 AI 诊断结果存在故障单上，有就直接展示，不必让人到了现场再点一次
    if (!aiResult.value && fault.value && fault.value.ai_diagnosis) {
      aiResult.value = fault.value.ai_diagnosis
    }
  } catch (err) {
    errorMsg.value = errorText(err, '故障详情加载失败')
  } finally {
    loading.value = false
  }
}

/** 核查结论 / 等级字典：只影响 chip 选项，失败用兜底常量，绝不阻断详情展示 */
async function loadDicts() {
  try {
    const dicts = await api.fetchFaultDicts()
    if (dicts && (dicts.verify_results || []).length) {
      verifyResults.value = dicts.verify_results
      if (verifyResults.value.indexOf(verifyStatus.value) < 0) {
        verifyStatus.value = verifyResults.value[0]
      }
    }
    if (dicts && (dicts.levels || []).length) levels.value = dicts.levels
    slaHoursMap.value = (dicts && dicts.level_sla_hours) || {}
  } catch (err) {
    console.warn('[fault-detail] 故障字典加载失败，核查选项用默认值', err)
  }
}

/** 草稿确认上报是不可回退的状态流转（会通知核查人），先确认一次 */
function askConfirm() {
  uni.showModal({
    title: '确认上报',
    content: '确认后该故障进入「待核查」，核查人会收到通知，不能再退回草稿。',
    success: (res) => {
      if (res.confirm) doConfirm()
    },
  })
}

async function doConfirm() {
  if (confirming.value) return
  confirming.value = true
  uni.showLoading({ title: '提交中…', mask: true })
  try {
    const res = await api.confirmFault(faultId.value)
    uni.hideLoading()
    uni.showToast({ title: res.message || '已确认上报', icon: 'success', duration: 2000 })
    await load()
  } catch (err) {
    uni.hideLoading()
    uni.showModal({
      title: '确认上报失败',
      content: errorText(err),
      showCancel: false,
      confirmText: '知道了',
    })
  } finally {
    confirming.value = false
  }
}

function toggleVerify() {
  showVerify.value = !showVerify.value
}

function pickVerifyStatus(name) {
  verifyStatus.value = name
}

function pickVerifyLevel(name) {
  verifyLevel.value = name
}

function onNeedDefectChange(e) {
  // ★ switch 的 e.detail.value 是布尔值（chip 才是按下标取值）
  needDefectOrder.value = !!e.detail.value
}

/** 核查照片：与上报同一套逐张上传，业务类型换成 verify 便于附件归类 */
async function chooseVerifyImages() {
  if (verifyUploading.value) return
  if (verifyImages.value.length >= MAX_VERIFY_IMAGES) {
    uni.showToast({ title: `最多 ${MAX_VERIFY_IMAGES} 张照片`, icon: 'none' })
    return
  }
  const picked = await new Promise((resolve) => {
    uni.chooseImage({
      count: MAX_VERIFY_IMAGES - verifyImages.value.length,
      sizeType: ['compressed'],
      sourceType: ['camera', 'album'],
      success: (res) => resolve(res.tempFilePaths || []),
      fail: () => resolve([]),
    })
  })
  if (!picked.length) return

  verifyUploading.value = true
  verifyProgress.value = { done: 0, total: picked.length }
  try {
    const files = await api.uploadImages({
      filePaths: picked,
      bizType: 'verify',
      onProgress: (done, total) => {
        verifyProgress.value = { done, total }
      },
    })
    files.forEach((file) => {
      verifyImages.value.push({ url: api.absoluteUrl(file.url), rawUrl: file.url })
    })
  } catch (err) {
    uni.showModal({
      title: '照片上传失败',
      content: `第 ${verifyProgress.value.done + 1} 张没传上去：${errorText(err, '请检查网络后重试')}`,
      showCancel: false,
      confirmText: '知道了',
    })
  } finally {
    verifyUploading.value = false
    verifyProgress.value = { done: 0, total: 0 }
  }
}

function removeVerifyImage(index) {
  verifyImages.value.splice(index, 1)
}

/** 提交成功后清空表单，避免下一条核查带着上一条的描述 */
function resetVerifyForm() {
  verifyDesc.value = ''
  verifyImages.value = []
  needDefectOrder.value = false
  verifyLevel.value = fault.value ? fault.value.fault_level : ''
  verifyStatus.value = verifyResults.value[0]
}

async function submitVerify() {
  if (verifySubmitting.value) return
  if (verifyUploading.value) {
    uni.showToast({ title: '核查照片还在上传，请稍候', icon: 'none' })
    return
  }
  if (verifyResults.value.indexOf(verifyStatus.value) < 0) {
    uni.showToast({ title: '请选择核查结论', icon: 'none' })
    return
  }
  if (!verifyDesc.value.trim()) {
    // 后端也校验（会返回「请填写核查描述」），先在本地拦一次省一个来回
    uni.showToast({ title: '请填写核查描述', icon: 'none' })
    return
  }

  verifySubmitting.value = true
  uni.showLoading({ title: '提交中…', mask: true })
  try {
    await api.verifyFault(faultId.value, {
      verifyStatus: verifyStatus.value,
      verifyLevel: verifyLevel.value,
      verifyDesc: verifyDesc.value.trim(),
      // ★ 传相对路径，页面显示时才补前缀
      images: verifyImages.value.map((item) => item.rawUrl),
      needDefectOrder: needDefectOrder.value,
    })
    uni.hideLoading()
    // ★ 核查接口返回的是默认 message（"success"），不像上报接口带业务提示语，
    //   所以这里用页面自己的文案，免得弹出「success」这种看不懂的提示。
    uni.showToast({ title: '核查已提交', icon: 'success', duration: 2000 })
    showVerify.value = false
    resetVerifyForm()
    await load()
  } catch (err) {
    uni.hideLoading()
    // 失败不清表单：现场写的一段核查描述重打一遍成本很高
    uni.showModal({
      title: '核查提交失败',
      content: errorText(err),
      showCancel: false,
      confirmText: '知道了',
    })
  } finally {
    verifySubmitting.value = false
  }
}

/** AI 诊断：带着故障 id 问，后端会读这条故障的历史；结果会存回故障单 */
async function runAi() {
  if (aiLoading.value || !fault.value) return
  aiLoading.value = true
  try {
    const res = await api.aiDiagnoseFault({
      faultId: faultId.value,
      faultType: fault.value.fault_type,
      faultLevel: fault.value.fault_level,
      description: fault.value.description,
      pileAssetCode: fault.value.pile_asset_code,
      stationId: fault.value.station_id,
    })
    aiResult.value = (res.data && res.data.diagnosis) || aiResult.value
  } catch (err) {
    uni.showModal({
      title: 'AI 诊断失败',
      content: errorText(err, 'AI 暂时不可用，可先按经验核查'),
      showCancel: false,
      confirmText: '知道了',
    })
  } finally {
    aiLoading.value = false
  }
}

onLoad((options) => {
  if (!requireLogin()) return
  faultId.value = options?.id || ''
  if (!faultId.value) {
    // 入口不对（例如手改过链接）就直接给错误态，不去发一个必然 404 的请求
    loading.value = false
    errorMsg.value = '缺少故障 id，请从故障列表进入本页'
    return
  }
  loadDicts()
  load()
})
</script>

<template>
  <view class="page" :class="hasActions ? 'page-with-footer' : ''">
    <view v-if="loading" class="empty">加载中…</view>

    <view v-else-if="errorMsg" class="error-box">
      <view class="error-text">{{ errorMsg }}</view>
      <button class="btn btn-primary retry-btn" @click="load">重 试</button>
    </view>

    <view v-else-if="fault">
      <!-- 超期提醒放最上面：现场核查前先知道这条是不是已经压线了 -->
      <view v-if="slaOverdue" class="danger-bar">
        该故障已超过 SLA 响应时限（{{ slaHours }} 小时），请优先处理
      </view>

      <!-- 基本信息 -->
      <view class="card">
        <view class="section-title">
          <text>{{ fault.fault_no }}</text>
          <text class="tag" :class="faultStatusClass(fault.status)">{{ fault.status }}</text>
        </view>

        <view class="row">
          <text class="row-label">故障类型</text>
          <text class="row-value">{{ fault.fault_type || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">故障等级</text>
          <text class="row-value">
            <text class="tag" :class="faultLevelClass(fault.fault_level)">{{ fault.fault_level }}</text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">SLA 截止</text>
          <text class="row-value">
            {{ slaDeadline || '—' }}（{{ slaHours }} 小时）
          </text>
        </view>
        <view class="row">
          <text class="row-label">是否超期</text>
          <text class="row-value">
            <text v-if="slaOverdue" class="tag tag-danger">已超 SLA</text>
            <text v-else class="muted">未超期</text>
          </text>
        </view>
        <view class="row">
          <text class="row-label">上报人</text>
          <text class="row-value">{{ fault.reporter_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">上报时间</text>
          <text class="row-value">{{ formatDateTime(fault.reported_at || fault.created_at, true) }}</text>
        </view>
        <view class="row">
          <text class="row-label">发生时间</text>
          <text class="row-value">{{ formatDateTime(fault.occurred_at, true) }}</text>
        </view>

        <view class="fault-desc-full">{{ fault.description || '（无描述）' }}</view>
      </view>

      <!-- 现场照片 -->
      <view class="card">
        <view class="section-title">
          <text>现场照片</text>
          <text class="muted">{{ faultImages.length }} 张</text>
        </view>
        <view v-if="faultImages.length" class="image-grid">
          <image
            v-for="(img, index) in faultImages"
            :key="img"
            class="grid-img"
            :src="img"
            mode="aspectFill"
            @click="previewImages(faultImages, index)"
          />
        </view>
        <view v-else class="empty">上报时没有上传照片</view>
      </view>

      <!-- 站点与充电桩 -->
      <view class="card">
        <view class="section-title">
          <text>站点与充电桩</text>
        </view>
        <view class="row">
          <text class="row-label">站点</text>
          <text class="row-value">{{ (station && station.name) || fault.station_name || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">站点地址</text>
          <text class="row-value">{{ (station && station.address) || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">桩资产码</text>
          <text class="row-value">
            {{ (pile && pile.asset_code) || fault.pile_asset_code || '未指定（整站 / 通信类）' }}
          </text>
        </view>
        <view class="row">
          <text class="row-label">桩名称</text>
          <text class="row-value">{{ (pile && pile.name) || '—' }}</text>
        </view>
        <view class="row">
          <text class="row-label">充电枪数</text>
          <text class="row-value">{{ pile && pile.gun_count ? pile.gun_count + ' 把' : '—' }}</text>
        </view>
      </view>

      <!-- AI 诊断：核查前先看一眼根因分析与处置建议 -->
      <view class="card">
        <view class="section-title">
          <text>AI 诊断</text>
          <text class="ai-link" @click="runAi">
            {{ aiLoading ? '分析中…' : aiResult ? '重新诊断' : '开始诊断' }}
          </text>
        </view>

        <view v-if="!aiResult" class="desc">
          现场核查前先看一眼 AI 的根因分析与处置建议；没配 LLM Key 时后端会自动降级为规则引擎，同样会给结果。
        </view>

        <view v-else>
          <view class="row">
            <text class="row-label">分析方式</text>
            <text class="row-value">
              <text class="tag tag-running">{{ aiMethodText }}</text>
            </text>
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
            <text class="row-value">{{ aiResult.sla_hours || slaHours }} 小时</text>
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

      <!-- 核查记录时间线：后端按核查时间倒序给，最近一次在最上面 -->
      <view class="card">
        <view class="section-title">
          <text>核查记录</text>
          <text class="muted">{{ verifications.length }} 条</text>
        </view>

        <view v-if="!verifications.length" class="empty">还没有核查记录</view>

        <view v-for="item in verifications" :key="item.id" class="timeline-item">
          <view class="timeline-head">
            <text class="strong">{{ item.verifier_name || '未知核查人' }}</text>
            <text class="tag" :class="faultStatusClass(item.verify_status)">{{ item.verify_status }}</text>
          </view>
          <view class="row">
            <text class="row-label">核查等级</text>
            <text class="row-value">
              <text class="tag" :class="faultLevelClass(item.verify_level)">{{ item.verify_level || '—' }}</text>
            </text>
          </view>
          <view class="row">
            <text class="row-label">核查时间</text>
            <text class="row-value">{{ formatDateTime(item.created_at, true) }}</text>
          </view>
          <view class="row">
            <text class="row-label">消缺工单</text>
            <text class="row-value">
              <text v-if="item.need_defect_order" class="tag tag-warn">已要求生成</text>
              <text v-else class="muted">不需要</text>
            </text>
          </view>
          <view class="timeline-desc">{{ item.verify_desc || '（无核查描述）' }}</view>
          <view v-if="verifyImagesOf(item).length" class="image-grid">
            <image
              v-for="(img, index) in verifyImagesOf(item)"
              :key="img"
              class="grid-img"
              :src="img"
              mode="aspectFill"
              @click="previewImages(verifyImagesOf(item), index)"
            />
          </view>
        </view>
      </view>

      <!-- 核查表单：页内展开，不引第三方组件，弱网下也少一次页面跳转 -->
      <view v-if="showVerify && canVerify" class="card">
        <view class="section-title">
          <text>故障核查</text>
        </view>

        <view class="form-item">
          <view class="form-label form-label-required">核查结论</view>
          <view class="chip-row">
            <view
              v-for="item in verifyResults"
              :key="item"
              class="chip"
              :class="verifyStatus === item ? 'chip-active' : ''"
              @click="pickVerifyStatus(item)"
            >
              {{ item }}
            </view>
          </view>
        </view>

        <view class="form-item">
          <view class="form-label">核查等级</view>
          <view class="chip-row">
            <view
              v-for="item in levels"
              :key="item"
              class="chip"
              :class="verifyLevel === item ? 'chip-active' : ''"
              @click="pickVerifyLevel(item)"
            >
              {{ levelChipText(item) }}
            </view>
          </view>
        </view>

        <view class="form-item">
          <view class="form-label form-label-required">核查描述</view>
          <textarea
            v-model="verifyDesc"
            class="form-textarea"
            :maxlength="MAX_VERIFY_DESC"
            placeholder="必填：写清现场核实到的实际情况与处置意见"
          />
          <view class="desc">{{ verifyDesc.length }}/{{ MAX_VERIFY_DESC }}</view>
        </view>

        <view class="form-item">
          <view class="form-label">核查照片</view>
          <view class="image-grid">
            <view v-for="(img, index) in verifyImages" :key="img.rawUrl" class="img-wrap">
              <image
                class="grid-img"
                :src="img.url"
                mode="aspectFill"
                @click="previewImages(verifyImageUrls, index)"
              />
              <view class="img-del" @click="removeVerifyImage(index)">×</view>
            </view>
            <view
              v-if="verifyImages.length < MAX_VERIFY_IMAGES"
              class="upload-add"
              @click="chooseVerifyImages"
            >
              <text class="upload-plus">＋</text>
              <text>{{ verifyUploading ? '上传中…' : '拍照/选图' }}</text>
            </view>
          </view>
          <view v-if="verifyUploading" class="desc">
            正在上传第 {{ verifyProgress.done + 1 }}/{{ verifyProgress.total }} 张，传完再提交
          </view>
        </view>

        <view class="form-item switch-item">
          <view class="switch-text">
            <view class="form-label">是否需要生成消缺工单</view>
            <view class="desc">核查通过且现场需要整改时打开，后端会按等级建消缺工单</view>
          </view>
          <switch :checked="needDefectOrder" @change="onNeedDefectChange" />
        </view>

        <button
          class="btn btn-primary submit-btn"
          :disabled="verifySubmitting || verifyUploading"
          @click="submitVerify"
        >
          {{ verifySubmitting ? '提交中…' : '提交核查' }}
        </button>
      </view>
    </view>

    <view v-if="hasActions" class="footer-bar">
      <button
        v-if="canConfirm"
        class="btn btn-primary"
        :disabled="confirming"
        @click="askConfirm"
      >
        {{ confirming ? '确认中…' : '确认上报' }}
      </button>
      <button v-if="canVerify" class="btn btn-default" @click="toggleVerify">
        {{ showVerify ? '收起核查表单' : '故障核查' }}
      </button>
    </view>
  </view>
</template>

<style scoped>
/* 描述是全文展示（列表页才截断两行）：保留换行，现场写多行也能读 */
.fault-desc-full {
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx solid #f0f1f3;
  color: #1f2329;
  font-size: 26rpx;
  line-height: 1.7;
  white-space: pre-wrap;
}

.timeline-item {
  padding: 20rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}

.timeline-item:last-child {
  border-bottom: none;
}

.timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8rpx;
}

.timeline-desc {
  margin-top: 12rpx;
  color: #4b5563;
  font-size: 25rpx;
  line-height: 1.7;
  white-space: pre-wrap;
}

.ai-link {
  color: #1677ff;
  font-size: 26rpx;
  font-weight: 400;
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

.switch-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.switch-text {
  flex: 1;
  padding-right: 20rpx;
}

.submit-btn {
  margin-top: 20rpx;
}

.retry-btn {
  width: 320rpx;
}
</style>
