<template>
  <div class="uploader">
    <a-upload
      v-model:file-list="fileList"
      list-type="picture-card"
      :multiple="true"
      :max-count="maxCount"
      :before-upload="beforeUpload"
      :custom-request="doUpload"
      accept="image/*"
      @remove="onRemove"
      @preview="onPreview"
    >
      <div v-if="fileList.length < maxCount">
        <PlusOutlined />
        <div style="margin-top: 4px; font-size: 12px">上传照片</div>
      </div>
    </a-upload>

    <div class="uploader-tip">
      支持 jpg/png/webp，单张不超过 {{ info.max_image_mb || 10 }}MB，最多 {{ maxCount }} 张
      <span v-if="uploading" class="text-muted">　上传中 {{ uploadingCount }} 张…</span>
    </div>

    <a-image-preview-group>
      <a-image
        v-if="false"
        :src="previewSrc"
        :preview="{ visible: previewVisible, onVisibleChange: (v) => (previewVisible = v) }"
      />
    </a-image-preview-group>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { uploadApi } from '@/api'

const props = defineProps({
  /** v-model:value —— 已上传图片的 URL 数组 */
  value: { type: Array, default: () => [] },
  bizType: { type: String, default: 'inspection' },
  bizId: { type: String, default: undefined },
  maxCount: { type: Number, default: 12 },
})
const emit = defineEmits(['update:value'])

const fileList = ref([])
const uploadingCount = ref(0)
const previewVisible = ref(false)
const previewSrc = ref('')
const info = ref({ max_image_mb: 10, max_files_per_request: 12 })

const uploading = computed(() => uploadingCount.value > 0)

/** 把外部传入的 URL 数组同步成图片卡片（避免重复添加） */
watch(
  () => props.value,
  (urls) => {
    const list = urls || []
    const current = fileList.value.filter((f) => f.status === 'done').map((f) => f.url)
    if (list.length === current.length && list.every((u, i) => u === current[i])) return

    fileList.value = list.map((url, i) => ({
      uid: `remote-${i}-${url}`,
      name: url.split('/').pop() || `photo-${i + 1}.jpg`,
      status: 'done',
      url,
      thumbUrl: url,
    }))
  },
  { immediate: true },
)

function syncValue() {
  const urls = fileList.value
    .filter((f) => f.status === 'done' && f.url)
    .map((f) => f.url)
  emit('update:value', urls)
}

function beforeUpload(file) {
  const isImage = file.type?.startsWith('image/')
  if (!isImage) {
    message.error('只能上传图片文件')
    return false
  }
  const limitMb = info.value.max_image_mb || 10
  if (file.size / 1024 / 1024 > limitMb) {
    message.error(`图片「${file.name}」超过 ${limitMb}MB`)
    return false
  }
  return true
}

/** 自定义上传：逐张调用 /uploads/images，拿到真实 URL */
async function doUpload({ file, onSuccess, onError }) {
  uploadingCount.value += 1
  try {
    const res = await uploadApi.uploadImages([file], {
      bizType: props.bizType,
      bizId: props.bizId,
    })
    const url = res.data?.urls?.[0]
    if (!url) throw new Error('上传未返回地址')

    const target = fileList.value.find((f) => f.uid === file.uid)
    if (target) {
      target.status = 'done'
      target.url = url
      target.thumbUrl = url
    }
    onSuccess?.(res.data)
    syncValue()
  } catch (e) {
    const target = fileList.value.find((f) => f.uid === file.uid)
    if (target) target.status = 'error'
    onError?.(e)
    message.error(`「${file.name}」上传失败：${e.message || '未知错误'}`)
  } finally {
    uploadingCount.value -= 1
  }
}

function onRemove() {
  // a-upload 已从 fileList 移除，这里只需同步外部值
  setTimeout(syncValue, 0)
}

function onPreview(file) {
  previewSrc.value = file.url || file.thumbUrl
  previewVisible.value = true
}

onMounted(async () => {
  try {
    const res = await uploadApi.info()
    info.value = res.data || info.value
  } catch {
    /* 使用默认限制 */
  }
})
</script>

<style scoped>
.uploader-tip {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 4px;
  line-height: 1.7;
}
</style>
