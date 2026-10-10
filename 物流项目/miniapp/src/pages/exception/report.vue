<script setup>
/**
 * 异常上报。
 *
 * 两步提交（顺序不能反）：
 *   1. POST /api/mobile/files      —— uni.chooseImage 拿到的是本地临时路径，
 *      必须先上传换到附件 id，异常记录里存的是 id 而不是图片本身；
 *   2. POST /api/mobile/exceptions —— 带上附件 id 列表上报。
 *
 * ★ 为什么必须在页面上把两张图都传完再提交：
 *   后端 MobileExceptionCreate.photo_attachment_ids 是 int 列表，
 *   传本地路径过去只会得到 422，所以任一图片上传失败就整体不提交，
 *   并且明确指出是「第几张」失败，避免司机以为报上去了其实没有。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import * as api from '@/api'
import { EXCEPTION_TYPES, copyText } from '@/utils/format'
import { requireLogin } from '@/utils/ui'

const taskId = ref(0)
const tripKey = ref('')
const storeId = ref(null)
const planDetailId = ref(null)
const storeName = ref('')

const typeIndex = ref(0)
const remark = ref('')
/** 已选图片：{ path 本地路径, url 上传后的完整地址, attachmentId 附件 id } */
const photos = ref([])
const uploading = ref(false)
const submitting = ref(false)
const errorMsg = ref('')

const currentType = computed(() => EXCEPTION_TYPES[typeIndex.value])

function onTypeChange(e) {
  typeIndex.value = Number(e.detail.value) || 0
}

function onRemarkInput(e) {
  remark.value = e.detail.value
}

/** 选图 + 逐张上传（上传成功才有 attachmentId） */
async function chooseAndUpload() {
  if (photos.value.length >= 3) {
    uni.showToast({ title: '最多 3 张照片', icon: 'none' })
    return
  }

  const picked = await new Promise((resolve) => {
    uni.chooseImage({
      count: 3 - photos.value.length,
      // 必须压缩：后端限制 10MB，手机原图经常超；jpg/png/webp 之外的后端会拒
      sizeType: ['compressed'],
      sourceType: ['camera', 'album'],
      success: (res) => resolve(res.tempFilePaths || []),
      fail: () => resolve([]),
    })
  })
  if (!picked.length) return

  uploading.value = true
  errorMsg.value = ''
  try {
    for (let i = 0; i < picked.length; i += 1) {
      const path = picked[i]
      try {
        const res = await api.uploadImage(path)
        photos.value.push({
          path,
          url: api.absoluteUrl(res.url),
          attachmentId: res.attachment_id,
          name: res.name,
        })
      } catch (err) {
        // 逐张报告，司机知道是哪一张需要重选
        errorMsg.value = `第 ${i + 1} 张照片上传失败：${err.message || '未知错误'}`
        uni.showModal({
          title: '照片上传失败',
          content: `${errorMsg.value}\n（可重新选择照片再提交）`,
          showCancel: false,
        })
        break
      }
    }
  } finally {
    uploading.value = false
  }
}

function removePhoto(index) {
  photos.value.splice(index, 1)
}

function previewPhoto(index) {
  uni.previewImage({
    urls: photos.value.map((p) => p.url || p.path),
    current: index,
  })
}

/** 提交异常 */
async function submit() {
  errorMsg.value = ''

  if (!taskId.value) {
    errorMsg.value = '缺少调度任务 id，无法上报（请从趟次详情进入本页）'
    return
  }
  if (!remark.value.trim()) {
    errorMsg.value = '请填写异常说明，方便调度员判断怎么处理'
    return
  }
  if (uploading.value) {
    errorMsg.value = '照片还在上传，请稍候'
    return
  }

  submitting.value = true
  uni.showLoading({ title: '上报中…', mask: true })
  try {
    // 定位同样是「有就有、没有也能报」，不阻塞
    const location = await new Promise((resolve) => {
      uni.getLocation({
        type: 'gcj02',
        success: (res) => resolve({ latitude: res.latitude, longitude: res.longitude }),
        fail: () => resolve({}),
      })
    })

    const res = await api.reportException({
      task_id: taskId.value,
      event_type: currentType.value.value,
      plan_detail_id: planDetailId.value,
      store_id: storeId.value,
      trip_key: tripKey.value,
      latitude: location.latitude,
      longitude: location.longitude,
      remark: remark.value.trim(),
      photo_attachment_ids: photos.value.map((p) => p.attachmentId).filter(Boolean),
    })

    uni.hideLoading()
    uni.showModal({
      title: '上报成功',
      content: res?.message || '异常已上报，调度员会尽快处理',
      showCancel: false,
      confirmText: '返回',
      success: () => uni.navigateBack(),
    })
  } catch (err) {
    uni.hideLoading()
    if (err.code === 0) {
      errorMsg.value = '网络不通，异常没有上报成功，请稍后重试'
    } else if (err.code === 403) {
      errorMsg.value = '当前账号没有绑定司机档案，无法上报异常'
    } else {
      errorMsg.value = err.message || '上报失败，请稍后重试'
    }
    uni.showToast({ title: '上报失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}

onLoad((options) => {
  if (!requireLogin()) return
  taskId.value = Number(options?.taskId || 0)
  tripKey.value = decodeURIComponent(options?.tripKey || '')
  storeId.value = options?.storeId ? Number(options.storeId) : null
  planDetailId.value = options?.planDetailId ? Number(options.planDetailId) : null
  storeName.value = decodeURIComponent(options?.storeName || '')
})
</script>

<template>
  <view class="page">
    <view class="card">
      <view class="row">
        <text class="row-label">关联趟次</text>
        <text class="row-value" @click="copyText(tripKey, '趟次标识已复制')">
          {{ tripKey || '—' }}
        </text>
      </view>
      <view v-if="storeName" class="row">
        <text class="row-label">关联门店</text>
        <text class="row-value">{{ storeName }}</text>
      </view>
      <view class="row">
        <text class="row-label">调度任务</text>
        <text class="row-value">{{ taskId || '—' }}</text>
      </view>
    </view>

    <!-- 异常类型 -->
    <view class="card">
      <view class="form-label">异常类型</view>
      <picker :range="EXCEPTION_TYPES" range-key="label" :value="typeIndex" @change="onTypeChange">
        <view class="picker-value">
          {{ currentType.label }}
          <text class="muted"> ▾</text>
        </view>
      </picker>
      <view class="hint muted">
        上报后进入调度员的「异常重排」待处理列表，类型用于判断处理方式。
      </view>
    </view>

    <!-- 说明 -->
    <view class="card">
      <view class="form-label">异常说明（必填）</view>
      <textarea
        class="remark"
        placeholder="例如：门店卷帘门关闭，联系不上收货人，已在门口等待 20 分钟"
        :value="remark"
        maxlength="255"
        @input="onRemarkInput"
      />
      <view class="hint muted">{{ remark.length }}/255</view>
    </view>

    <!-- 照片 -->
    <view class="card">
      <view class="form-label">现场照片（选填，最多 3 张）</view>
      <view class="photo-grid">
        <view
          v-for="(photo, index) in photos"
          :key="photo.attachmentId || photo.path"
          class="photo-item"
        >
          <image class="photo" :src="photo.url || photo.path" mode="aspectFill" @click="previewPhoto(index)" />
          <view class="photo-del" @click="removePhoto(index)">×</view>
        </view>
        <view v-if="photos.length < 3" class="photo-add" @click="chooseAndUpload">
          <text class="photo-add-icon">＋</text>
          <text class="photo-add-text">{{ uploading ? '上传中…' : '拍照/选图' }}</text>
        </view>
      </view>
      <view class="hint muted">支持 jpg / jpeg / png / webp，单张不超过 10MB。</view>
    </view>

    <view v-if="errorMsg" class="error-inline">{{ errorMsg }}</view>

    <button
      class="btn btn-primary submit-btn"
      :disabled="submitting || uploading"
      @click="submit"
    >
      {{ submitting ? '上报中…' : '提交异常上报' }}
    </button>
  </view>
</template>

<style scoped>
.form-label {
  font-size: 28rpx;
  font-weight: 600;
  margin-bottom: 16rpx;
}

.picker-value {
  background: #f5f6f8;
  border-radius: 12rpx;
  padding: 22rpx 20rpx;
  font-size: 28rpx;
}

.hint {
  font-size: 22rpx;
  margin-top: 12rpx;
}

.remark {
  width: 100%;
  box-sizing: border-box;
  height: 200rpx;
  background: #f5f6f8;
  border-radius: 12rpx;
  padding: 20rpx;
  font-size: 28rpx;
}

.photo-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.photo-item {
  position: relative;
  width: 180rpx;
  height: 180rpx;
}

.photo {
  width: 180rpx;
  height: 180rpx;
  border-radius: 12rpx;
}

.photo-del {
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

.photo-add {
  width: 180rpx;
  height: 180rpx;
  border: 2rpx dashed #c0c4cc;
  border-radius: 12rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #8a9099;
}

.photo-add-icon {
  font-size: 48rpx;
  line-height: 1;
}

.photo-add-text {
  font-size: 22rpx;
  margin-top: 8rpx;
}

.error-inline {
  color: #d03050;
  font-size: 26rpx;
  padding: 8rpx 8rpx 20rpx;
}

.submit-btn {
  margin-top: 8rpx;
}
</style>
